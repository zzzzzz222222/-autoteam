"""AT-AUDIT-003 regression tests: AGENT_REPLANNED must mean a real plan change.

The defect: ``AsyncDAGScheduler.run`` appended a ``ReplanEvent`` for *every*
failed agent, regardless of what the Replanner returned, and
``TaskExecutionSession`` then wrote an ``AGENT_REPLANNED`` trace event for every
one of them. The deterministic ``Replanner`` always returns
``replanned=False`` / ``topology=None``, so in practice every failure was
reported to the trace, the SSE timeline and the UI as "replanned" while the plan
never changed.

These tests drive the **real** scheduler, the **real** session and the **real**
``ExecutionTrace``. Only the Replanner dependency is swapped for a
deterministic, scripted stand-in so its outcome can be controlled. The event
decision logic and the event recording logic are never mocked.

No real LLM, no web search, no fixed sleeps to infer whether an event fired.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from app.llm.provider import MockLLMProvider
from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.runtime import session as session_module
from app.runtime.orchestrator import ResearchOrchestrator
from app.runtime.result_store import ResultStore
from app.runtime.session import execute_task
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.replan import Replanner, ReplanResult, topology_signature
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.topology.validator import TopologyValidationError

# Offline wording that makes the mock planner emit a multi-agent DAG.
MULTI_AGENT_TASK = (
    "调研 2025 年企业级 RAG 技术栈，分析市场竞争格局与技术趋势，并输出可执行的研究报告"
)
FAILED_AGENT = "data_analyst"


# --- deterministic Replanner stand-in -------------------------------------


class ScriptedReplanner(Replanner):
    """Real control flow, scripted outcome. Records every invocation."""

    def __init__(self, outcome: Callable[[Topology, str], ReplanResult]) -> None:
        self.outcome = outcome
        self.invocations: list[str] = []
        self.results: list[ReplanResult] = []

    def replan(
        self, topology: Topology, failed_agent_id: str, results: dict[str, object]
    ) -> ReplanResult:
        del results
        self.invocations.append(failed_agent_id)
        produced = self.outcome(topology, failed_agent_id)
        self.results.append(produced)
        return produced


def noop_outcome() -> Callable[[Topology, str], ReplanResult]:
    """What the built-in Replanner returns: no viable recovery plan."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del topology
        return ReplanResult(
            replanned=False,
            reason="no viable recovery plan",
            skipped_agents=[failed_agent_id],
        )

    return build


def equivalent_plan_outcome() -> Callable[[Topology, str], ReplanResult]:
    """Claims a replan but hands back exactly the plan already running."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del failed_agent_id
        return ReplanResult(
            replanned=True, reason="candidate equals current plan", topology=topology
        )

    return build


def alternate_plan_outcome() -> Callable[[Topology, str], ReplanResult]:
    """A structurally different, valid plan over the same agent set."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del failed_agent_id
        agents = list(topology.agents)
        root = topology.root_agent or agents[0]
        ordered = [root] + [agent for agent in agents if agent != root]
        edges = [
            TopologyEdge(source=ordered[index], target=ordered[index + 1])
            for index in range(len(ordered) - 1)
        ]
        return ReplanResult(
            replanned=True,
            reason="rerouted the remaining work as a chain",
            topology=Topology(
                type=TopologyType.CHAIN, agents=ordered, edges=edges, root_agent=root
            ),
        )

    return build


def invalid_candidate_outcome() -> Callable[[Topology, str], ReplanResult]:
    """A candidate that cannot pass the project's existing DAG validation."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del failed_agent_id
        agents = list(topology.agents)
        first, second = agents[0], agents[1]
        return ReplanResult(
            replanned=True,
            reason="cyclic candidate",
            topology=Topology(
                type=TopologyType.HIERARCHICAL,
                agents=agents,
                edges=[
                    TopologyEdge(source=first, target=second),
                    TopologyEdge(source=second, target=first),
                ],
                root_agent=first,
            ),
        )

    return build


def unapplied_candidate_outcome() -> Callable[[Topology, str], ReplanResult]:
    """Claims a replan but supplies no plan that could ever be applied."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del topology, failed_agent_id
        return ReplanResult(
            replanned=True, reason="candidate discarded before application", topology=None
        )

    return build


# --- harness ---------------------------------------------------------------


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


def flat_topology(agent_ids: list[str]) -> Topology:
    """One fully parallel wave (``root_agent`` must stay None — no edges)."""
    return Topology(
        type=TopologyType.HIERARCHICAL, agents=agent_ids, edges=[], root_agent=None
    )


def run_scheduler(
    agent_ids: list[str],
    replanner: ScriptedReplanner,
    failing: set[str],
    max_concurrency: int | None = None,
) -> AsyncDAGScheduler:
    scheduler = AsyncDAGScheduler(
        executor=MockAgentExecutor(delay=0.005, fail_agent_ids=failing),
        max_concurrency=max_concurrency,
        retry_policy=RetryPolicy(max_retries=1),
        replanner=replanner,
    )
    asyncio.run(
        scheduler.run(
            Task(description="test"), flat_topology(agent_ids), make_agents(agent_ids)
        )
    )
    return scheduler


def run_session(
    monkeypatch: pytest.MonkeyPatch,
    replanner: ScriptedReplanner,
    failing: set[str] | None = None,
):
    """Run the real ``execute_task`` with only the Replanner swapped."""
    original = session_module.AsyncDAGScheduler

    def factory(*args: object, **kwargs: object) -> AsyncDAGScheduler:
        kwargs.setdefault("replanner", replanner)
        return original(*args, **kwargs)

    monkeypatch.setattr(session_module, "AsyncDAGScheduler", factory)
    return execute_task(MULTI_AGENT_TASK, fail_agent_ids=failing or {FAILED_AGENT})


# --- 1. no-op must not emit an event --------------------------------------


def test_noop_replan_emits_no_event(monkeypatch: pytest.MonkeyPatch) -> None:
    replanner = ScriptedReplanner(noop_outcome())
    session = run_session(monkeypatch, replanner)

    assert replanner.invocations == [FAILED_AGENT]  # replanner_invoked == True
    assert all(result.replanned is False for result in replanner.results)
    # The existing no-op reason semantics are preserved on the ReplanResult.
    assert all(result.reason == "no viable recovery plan" for result in replanner.results)
    assert all(result.topology is None for result in replanner.results)

    assert session.trace.of_type("AGENT_REPLANNED") == []  # event count == 0


def test_noop_replan_is_still_recorded_for_observability() -> None:
    """The no-op must stay visible, just not as a successful replan."""
    replanner = ScriptedReplanner(noop_outcome())
    scheduler = run_scheduler(["A", "B", "C"], replanner, failing={"B"})

    assert len(scheduler.replan_events) == 1
    event = scheduler.replan_events[0]
    assert event.applied is False
    assert event.failed_agent_id == "B"
    assert event.reason == "no viable recovery plan"
    assert event.previous_topology is None
    assert event.new_topology is None


def test_equivalent_candidate_is_treated_as_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """replanned=True but the plan is identical -> no effective change."""
    replanner = ScriptedReplanner(equivalent_plan_outcome())
    session = run_session(monkeypatch, replanner)

    assert replanner.invocations == [FAILED_AGENT]
    assert all(result.replanned for result in replanner.results)
    assert session.trace.of_type("AGENT_REPLANNED") == []


# --- 2. a real, applied change does emit exactly one event -----------------


def test_effective_change_emits_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    replanner = ScriptedReplanner(alternate_plan_outcome())
    session = run_session(monkeypatch, replanner)

    assert replanner.invocations == [FAILED_AGENT]
    events = session.trace.of_type("AGENT_REPLANNED")
    assert len(events) == 1

    event = events[0]
    # Effective change: the candidate differs from the plan that was running.
    assert all(result.replanned for result in replanner.results)
    assert all(result.topology is not None for result in replanner.results)
    # Fields must match the real change, not a fabricated agent or run.
    assert event.agent_id == FAILED_AGENT
    assert event.run_id == session.run_id
    assert event.metadata["previous_topology"] != event.metadata["new_topology"]
    assert topology_signature(replanner.results[0].topology) == event.metadata["new_topology"]


def test_effective_change_is_flagged_applied_on_the_scheduler() -> None:
    replanner = ScriptedReplanner(alternate_plan_outcome())
    scheduler = run_scheduler(["A", "B", "C", "D"], replanner, failing={"B"})

    assert len(scheduler.replan_events) == 1
    event = scheduler.replan_events[0]
    assert event.applied is True
    assert event.failed_agent_id == "B"
    assert event.previous_topology is not None
    assert event.new_topology is not None
    assert event.previous_topology != event.new_topology


# --- 3. an invalid candidate emits no event -------------------------------


def test_invalid_candidate_emits_no_event() -> None:
    replanner = ScriptedReplanner(invalid_candidate_outcome())
    scheduler = AsyncDAGScheduler(
        executor=MockAgentExecutor(delay=0.005, fail_agent_ids={"B"}),
        retry_policy=RetryPolicy(max_retries=1),
        replanner=replanner,
    )
    # Existing error handling is unchanged: the invalid plan is rejected by the
    # project's own validator and the error propagates.
    with pytest.raises(TopologyValidationError):
        asyncio.run(
            scheduler.run(
                Task(description="test"),
                flat_topology(["A", "B", "C"]),
                make_agents(["A", "B", "C"]),
            )
        )

    assert replanner.invocations == ["B"]  # candidate_valid == False
    assert scheduler.replan_events == []  # no event was appended


def test_invalid_candidate_does_not_reach_the_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    replanner = ScriptedReplanner(invalid_candidate_outcome())
    session = run_session(monkeypatch, replanner)

    # The existing recovery path is preserved: the run fails loudly, and no
    # successful-replan event is written anywhere.
    assert session.trace.of_type("AGENT_REPLANNED") == []
    assert session.status.value == "failed"
    assert "Topology" in (session.error or "")


# --- 4. an unapplied change emits no event --------------------------------


def test_unapplied_candidate_emits_no_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """replanned=True but no plan supplied -> candidate_valid, never applied."""
    replanner = ScriptedReplanner(unapplied_candidate_outcome())
    session = run_session(monkeypatch, replanner)

    assert all(result.replanned for result in replanner.results)
    assert all(result.topology is None for result in replanner.results)
    assert session.trace.of_type("AGENT_REPLANNED") == []


def test_unapplied_candidate_is_flagged_not_applied() -> None:
    replanner = ScriptedReplanner(unapplied_candidate_outcome())
    scheduler = run_scheduler(["A", "B", "C"], replanner, failing={"B"})

    assert len(scheduler.replan_events) == 1
    assert scheduler.replan_events[0].applied is False


# --- 5. repeated no-ops never accumulate events ---------------------------


def test_repeated_noops_emit_no_events(monkeypatch: pytest.MonkeyPatch) -> None:
    replanner = ScriptedReplanner(noop_outcome())
    session = run_session(monkeypatch, replanner, failing={"data_analyst", "technology_analyst"})

    assert len(replanner.invocations) == 2  # replanner really ran twice
    assert session.trace.of_type("AGENT_REPLANNED") == []


def test_repeated_noops_on_one_context_emit_no_events() -> None:
    replanner = ScriptedReplanner(noop_outcome())
    scheduler = run_scheduler(["A", "B", "C"], replanner, failing={"B", "C"})

    assert len(replanner.invocations) == 2
    assert len(scheduler.replan_events) == 2
    assert all(event.applied is False for event in scheduler.replan_events)


# --- 6. one effective change emits exactly one event ----------------------


def test_single_effective_change_is_not_duplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    replanner = ScriptedReplanner(alternate_plan_outcome())
    session = run_session(monkeypatch, replanner)

    assert len(replanner.invocations) == 1
    assert len(session.trace.of_type("AGENT_REPLANNED")) == 1


# --- 7. run isolation (AT-AUDIT-002 compatible) ---------------------------


def test_replan_event_is_scoped_to_its_own_run(monkeypatch: pytest.MonkeyPatch) -> None:
    changing = ScriptedReplanner(alternate_plan_outcome())
    inert = ScriptedReplanner(noop_outcome())

    run_a = run_session(monkeypatch, changing)
    run_b = run_session(monkeypatch, inert)

    assert run_a.run_id != run_b.run_id

    events_a = run_a.trace.of_type("AGENT_REPLANNED")
    events_b = run_b.trace.of_type("AGENT_REPLANNED")
    assert len(events_a) == 1  # A really replanned
    assert events_b == []  # B was a no-op

    # No cross-run contamination in either direction.
    assert all(event.run_id == run_a.run_id for event in run_a.trace.events)
    assert all(event.run_id == run_b.run_id for event in run_b.trace.events)


def test_result_store_isolation_still_holds_alongside_the_fix() -> None:
    """AT-AUDIT-002's per-run partitions must be untouched by this change."""
    store = ResultStore()
    orchestrator = ResearchOrchestrator(
        provider=MockLLMProvider(), tool_mode="mock", store=store
    )
    asyncio.run(orchestrator.run(MULTI_AGENT_TASK))
    asyncio.run(orchestrator.run("分析竞争对手、市场规模、技术趋势，给出投资建议"))

    run_ids = store.runs()
    assert len(run_ids) == 2
    first, second = run_ids
    assert store.events_of(first) and store.events_of(second)
    assert all(event.run_id == first for event in store.events_of(first))
    assert all(event.run_id == second for event in store.events_of(second))


# --- 8. compatible with the AT-AUDIT-001 concurrency cap ------------------


def test_noop_replan_under_concurrency_cap() -> None:
    replanner = ScriptedReplanner(noop_outcome())
    scheduler = run_scheduler(["A", "B", "C", "D"], replanner, failing={"B"}, max_concurrency=2)

    assert scheduler.max_concurrency == 2
    assert scheduler.executor.max_concurrent <= 2  # cap not bypassed
    assert scheduler.executor.max_concurrent == 2  # still genuinely parallel
    assert len(scheduler.replan_events) == 1
    assert scheduler.replan_events[0].applied is False


def test_effective_replan_under_concurrency_cap() -> None:
    replanner = ScriptedReplanner(alternate_plan_outcome())
    scheduler = run_scheduler(["A", "B", "C", "D"], replanner, failing={"B"}, max_concurrency=2)

    assert scheduler.max_concurrency == 2
    assert scheduler.executor.max_concurrent <= 2
    assert scheduler.replan_events[0].applied is True
