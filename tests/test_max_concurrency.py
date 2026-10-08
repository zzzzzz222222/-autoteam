"""AT-AUDIT-001 regression tests: ``max_concurrency`` must actually bind.

The defect: ``AsyncDAGScheduler`` owns a working ``asyncio.Semaphore`` cap, but
the three core entry points (``execute_task``, ``ResearchOrchestrator.run``,
``run_dynamic_team``) never passed ``max_concurrency``, so the semaphore was
never created and every ready wave ran unbounded through ``asyncio.gather``.
A second, quieter bypass: non-integer values such as ``1.5`` were accepted and
made the semaphore non-binding (``Semaphore`` only gates while its internal
value compares equal to 0, so a fractional value decrements past zero forever).

These tests measure **observed** concurrency. They never sleep blindly to prove
a cap: agents park on a gate that the test releases only after it has recorded
how many of them were in flight at the same instant.

No real LLM, no web search, no mocking of the concurrency control itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Iterator

import pytest

from app.llm.provider import MockLLMProvider
from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.runtime import dynamic_team as dynamic_team_module
from app.runtime import orchestrator as orchestrator_module
from app.runtime import session as session_module
from app.runtime.dynamic_team import build_dynamic_team, run_dynamic_team
from app.runtime.orchestrator import ResearchOrchestrator
from app.runtime.result_store import ResultStore
from app.runtime.session import execute_task
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.models import ExecutionContext, ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler

# Task wording that makes the offline (mock) planner emit a multi-agent DAG with
# a genuinely parallel middle layer: 1 -> 3 -> 1.
MULTI_AGENT_TASK = (
    "调研 2025 年企业级 RAG 技术栈，分析市场竞争格局与技术趋势，并输出可执行的研究报告"
)


# --- helpers ---------------------------------------------------------------


class ConcurrencyTracker:
    """Thread-safe observed-concurrency recorder."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_observed = 0
        self.entered: list[str] = []

    @contextlib.contextmanager
    def track(self, label: str) -> Iterator[None]:
        with self._lock:
            self.active += 1
            self.entered.append(label)
            self.max_observed = max(self.max_observed, self.active)
        try:
            yield
        finally:
            with self._lock:
                self.active -= 1

    def peak(self) -> int:
        with self._lock:
            return self.max_observed

    def current(self) -> int:
        with self._lock:
            return self.active


class GateExecutor:
    """Executor that parks each agent until the test releases the gate.

    This is the controlled-synchronization counterpart of a fixed ``sleep``:
    the in-flight set is stable while parked, so the peak recorded by the test
    is the number of agents the scheduler truly allowed to run at once.
    """

    def __init__(self, tracker: ConcurrencyTracker, timeout: float = 10.0) -> None:
        self.tracker = tracker
        self.timeout = timeout
        self._gates: dict[str, asyncio.Event] = {}
        self._released = False

    def _gate_for(self, agent_id: str) -> asyncio.Event:
        gate = self._gates.get(agent_id)
        if gate is None:
            gate = asyncio.Event()
            self._gates[agent_id] = gate
            # An agent that only becomes runnable *after* the release must not
            # park on a fresh gate forever.
            if self._released:
                gate.set()
        return gate

    async def execute(self, agent: AgentSpec, context: ExecutionContext) -> dict[str, str]:
        del context
        agent_id = agent.id or "unknown"
        with self.tracker.track(agent_id):
            # Parked: the test observes the in-flight set before releasing.
            await asyncio.wait_for(self._gate_for(agent_id).wait(), timeout=self.timeout)
        return {"agent_id": agent_id}

    def release_all(self) -> None:
        self._released = True
        for gate in self._gates.values():
            gate.set()


def make_agents(agent_ids: list[str]) -> list[AgentSpec]:
    return [
        AgentSpec(
            id=agent_id,
            role=AgentRole(
                name=f"Agent {agent_id}",
                capabilities=[CapabilityName.TASK_PLANNING],
                goal="test",
            ),
        )
        for agent_id in agent_ids
    ]


def make_topology(agent_ids: list[str], edges: list[tuple[str, str]]) -> Topology:
    return Topology(
        type=TopologyType.HIERARCHICAL,
        agents=agent_ids,
        edges=[TopologyEdge(source=source, target=target) for source, target in edges],
        root_agent=agent_ids[0] if agent_ids and edges else None,
    )


def flat_topology(agent_ids: list[str]) -> Topology:
    """One fully parallel wave — the cleanest shape for measuring a cap."""
    return make_topology(agent_ids, [])


async def _settle(tracker: ConcurrencyTracker, expected: int, extra_turns: int = 50) -> None:
    """Yield to the loop until ``expected`` agents are in flight, then idle."""
    for _ in range(2000):
        if tracker.current() >= expected:
            break
        await asyncio.sleep(0)
    # Give any agent that could sneak past the cap time to do so.
    for _ in range(extra_turns):
        await asyncio.sleep(0)


async def measure_peak(
    agent_ids: list[str], cap: int | None, expected_peak: int, timeout: float = 10.0
) -> tuple[dict[str, object], int, int]:
    """Run one flat (fully parallel) wave and report the observed peak."""
    tracker = ConcurrencyTracker()
    executor = GateExecutor(tracker, timeout=timeout)
    scheduler = AsyncDAGScheduler(executor=executor, max_concurrency=cap)
    run = asyncio.ensure_future(
        scheduler.run(Task(description="test"), flat_topology(agent_ids), make_agents(agent_ids))
    )
    await _settle(tracker, expected_peak)
    peak_while_parked = tracker.peak()
    executor.release_all()
    results = await asyncio.wait_for(run, timeout=timeout)
    return results, peak_while_parked, tracker.peak()


def scheduler_spy(monkeypatch: pytest.MonkeyPatch, module: object) -> list[int | None]:
    """Record the ``max_concurrency`` each scheduler is actually built with."""
    recorded: list[int | None] = []
    original = getattr(module, "AsyncDAGScheduler")

    def factory(*args: object, **kwargs: object) -> AsyncDAGScheduler:
        instance = original(*args, **kwargs)
        recorded.append(instance.max_concurrency)
        return instance

    monkeypatch.setattr(module, "AsyncDAGScheduler", factory)
    return recorded


# --- 1. the cap actually binds --------------------------------------------


def test_cap_one_never_exceeds_one() -> None:
    results, peak_while_parked, peak_final = asyncio.run(measure_peak(["A", "B", "C", "D"], 1, 1))
    assert peak_while_parked == 1
    assert peak_final == 1
    assert all(item.status is ExecutionStatus.SUCCESS for item in results.values())


def test_cap_two_runs_exactly_two_in_parallel() -> None:
    results, peak_while_parked, peak_final = asyncio.run(
        measure_peak(["A", "B", "C", "D", "E"], 2, 2)
    )
    # == 2 (not just <= 2) proves parallelism above 1 is preserved, not serialised.
    assert peak_while_parked == 2
    assert peak_final == 2
    assert len(results) == 5
    assert all(item.status is ExecutionStatus.SUCCESS for item in results.values())


def test_cap_four_runs_exactly_four_in_parallel() -> None:
    results, peak_while_parked, peak_final = asyncio.run(
        measure_peak(["A", "B", "C", "D", "E", "F"], 4, 4)
    )
    assert peak_while_parked == 4
    assert peak_final == 4
    assert len(results) == 6


# --- 2. DAG semantics survive the cap -------------------------------------


@pytest.mark.parametrize("cap", [1, 2])
def test_dag_dependency_order_is_preserved_under_cap(cap: int) -> None:
    executor = MockAgentExecutor(delay=0.01)
    agents = make_agents(["A", "B", "C", "D"])
    topology = make_topology(["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    results = asyncio.run(
        AsyncDAGScheduler(executor=executor, max_concurrency=cap).run(
            Task(description="test"), topology, agents
        )
    )
    assert all(item.status is ExecutionStatus.SUCCESS for item in results.values())
    order = executor.execution_order
    assert order.index("A") == 0
    assert order.index("D") > order.index("B")
    assert order.index("D") > order.index("C")
    assert executor.max_concurrent <= cap


def test_parallel_children_still_parallel_when_cap_exceeds_wave() -> None:
    executor = MockAgentExecutor(delay=0.01)
    agents = make_agents(["A", "B", "C"])
    topology = make_topology(["A", "B", "C"], [("A", "B"), ("A", "C")])
    asyncio.run(
        AsyncDAGScheduler(executor=executor, max_concurrency=4).run(
            Task(description="test"), topology, agents
        )
    )
    assert executor.max_concurrent == 2  # cap 4 > wave size 2 -> both run together


# --- 3. retry must not exceed the cap -------------------------------------


def test_failure_and_retry_stay_within_cap() -> None:
    executor = MockAgentExecutor(delay=0.01, failures_before_success={"B": 2})
    scheduler = AsyncDAGScheduler(
        executor=executor,
        max_concurrency=2,
        retry_policy=RetryPolicy(max_retries=2, retry_delay=0.01),
    )
    agents = make_agents(["A", "B", "C", "D", "E"])
    results = asyncio.run(
        scheduler.run(Task(description="test"), flat_topology(["A", "B", "C", "D", "E"]), agents)
    )
    assert executor.max_concurrent <= 2
    assert results["B"].status is ExecutionStatus.SUCCESS
    assert results["B"].attempt == 3  # failed twice, then succeeded


# --- 4. argument validation: reject, never silently ignore ----------------


@pytest.mark.parametrize("bad", [0, -1, -10])
def test_non_positive_integers_are_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        AsyncDAGScheduler(executor=MockAgentExecutor(), max_concurrency=bad)


@pytest.mark.parametrize("bad", ["2", "4", 1.5, 2.0, True, [2], {"n": 2}])
def test_illegal_types_are_rejected_not_silently_accepted(bad: object) -> None:
    with pytest.raises(TypeError, match="positive integer"):
        AsyncDAGScheduler(executor=MockAgentExecutor(), max_concurrency=bad)


def test_none_is_still_an_explicitly_valid_no_limit_value() -> None:
    scheduler = AsyncDAGScheduler(executor=MockAgentExecutor(), max_concurrency=None)
    assert scheduler.max_concurrency is None


def test_fractional_cap_used_to_silently_disable_the_limit() -> None:
    """Regression: 1.5 was accepted and produced a completely unbounded wave."""
    with pytest.raises(TypeError):
        AsyncDAGScheduler(executor=MockAgentExecutor(), max_concurrency=1.5)


def test_invalid_cap_is_not_swallowed_by_execute_task() -> None:
    session = execute_task(MULTI_AGENT_TASK, max_concurrency=0)
    assert session.status.value == "failed"
    assert "max_concurrency" in (session.error or "")


# --- 5. default behaviour is unchanged ------------------------------------


def test_default_none_stays_unbounded() -> None:
    results, peak_while_parked, peak_final = asyncio.run(
        measure_peak(["A", "B", "C", "D"], None, 4)
    )
    assert peak_while_parked == 4
    assert peak_final == 4
    assert len(results) == 4


def test_legacy_positional_construction_still_works() -> None:
    scheduler = AsyncDAGScheduler(MockAgentExecutor(), 2, None, RetryPolicy(max_retries=1))
    assert scheduler.max_concurrency == 2


# --- 6. the three core entry points now forward the value -----------------


def test_execute_task_forwards_max_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = scheduler_spy(monkeypatch, session_module)
    session = execute_task(MULTI_AGENT_TASK, max_concurrency=2)
    assert recorded == [2]
    assert session.status.value != "failed"


def test_execute_task_default_forwards_none(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = scheduler_spy(monkeypatch, session_module)
    execute_task(MULTI_AGENT_TASK)
    assert recorded == [None]


def test_orchestrator_forwards_max_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = scheduler_spy(monkeypatch, orchestrator_module)
    orchestrator = ResearchOrchestrator(
        provider=MockLLMProvider(), tool_mode="mock", max_concurrency=1
    )
    asyncio.run(orchestrator.run(MULTI_AGENT_TASK))
    assert recorded == [1]


def test_run_dynamic_team_forwards_max_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = scheduler_spy(monkeypatch, dynamic_team_module)
    plan = build_dynamic_team(MULTI_AGENT_TASK, provider=MockLLMProvider())
    asyncio.run(
        run_dynamic_team(plan, provider=MockLLMProvider(), tool_mode="mock", max_concurrency=2)
    )
    assert recorded == [2]


# --- 7. compatible with the AT-AUDIT-002 per-run isolation ----------------


def test_capped_orchestrator_keeps_runs_isolated() -> None:
    store = ResultStore()
    orchestrator = ResearchOrchestrator(
        provider=MockLLMProvider(), tool_mode="mock", store=store, max_concurrency=1
    )
    asyncio.run(orchestrator.run(MULTI_AGENT_TASK))
    asyncio.run(orchestrator.run("分析竞争对手、市场规模、技术趋势，给出投资建议"))

    run_ids = store.runs()
    assert len(run_ids) == 2
    first, second = run_ids
    first_events = store.events_of(first)
    second_events = store.events_of(second)
    assert first_events and second_events
    assert all(event.run_id == first for event in first_events)
    assert all(event.run_id == second for event in second_events)
    # A capped run still delivered results, filed under its own run only.
    first_results = store.snapshot(first)["results"]
    assert first_results and all(item["status"] == "success" for item in first_results.values())
