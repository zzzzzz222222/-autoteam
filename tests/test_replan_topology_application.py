"""AT-AUDIT-005 regression tests: a replanned topology must reach the scheduler.

The defect (``validation/full_audit/15_FULL_PROJECT_ISSUE_LIST.md:124-134``):
``AsyncDAGScheduler.run`` validated ``recovery.topology`` and then dropped it.
``topology`` / ``predecessors`` / ``ExecutionContext.topology`` were never
rebuilt, so the next READY pass still used the old edges and the replan had no
effect on execution at all.

The observable used throughout: a diamond ``A -> B, A -> C, B -> D, C -> D``
where ``B`` fails. Under the old plan ``D`` is SKIPPED (its parent ``B`` failed).
A replan that removes the ``B -> D`` edge makes ``D`` runnable again — so
"was the plan really applied?" has a deterministic, executable answer:

    D SKIPPED  -> the candidate was NOT applied
    D SUCCESS  -> the candidate WAS applied

These tests use the real ``AsyncDAGScheduler``, the real ``MockAgentExecutor``
and the real ``ExecutionTrace``/session path. Only the Replanner dependency is a
deterministic stand-in. No real LLM, no web search, no sleep-based assertions.
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
from app.scheduler.models import ExecutionStatus
from app.scheduler.replan import Replanner, ReplanResult, topology_signature
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.topology.validator import TopologyValidationError

MULTI_AGENT_TASK = (
    "调研 2025 年企业级 RAG 技术栈，分析市场竞争格局与技术趋势，并输出可执行的研究报告"
)

DIAMOND_EDGES = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
# Same agents, B -> D removed: D now only waits for C.
REROUTED_EDGES = [("A", "B"), ("A", "C"), ("C", "D")]


# --- helpers ---------------------------------------------------------------


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


def make_topology(
    agent_ids: list[str], edges: list[tuple[str, str]], root: str | None = "A"
) -> Topology:
    return Topology(
        type=TopologyType.HIERARCHICAL,
        agents=agent_ids,
        edges=[TopologyEdge(source=source, target=target) for source, target in edges],
        root_agent=root,
    )


class ScriptedReplanner(Replanner):
    """Deterministic Replanner stand-in; records what it saw and returned."""

    def __init__(
        self, outcome: Callable[[Topology, str], ReplanResult], executor: object = None
    ) -> None:
        self.outcome = outcome
        self.executor = executor
        self.invocations: list[str] = []
        self.seen_topologies: list[str] = []
        self.in_flight_at_call: list[int] = []
        self.results: list[ReplanResult] = []

    def replan(self, topology, failed_agent_id, results):
        del results
        self.invocations.append(failed_agent_id)
        self.seen_topologies.append(topology_signature(topology))
        if self.executor is not None:
            self.in_flight_at_call.append(getattr(self.executor, "active_count", -1))
        produced = self.outcome(topology, failed_agent_id)
        self.results.append(produced)
        return produced


def candidate_factory(edges: list[tuple[str, str]], agents: list[str] | None = None):
    """Build a Replanner outcome that proposes ``edges`` (agents default: A-D)."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del failed_agent_id
        agent_ids = agents if agents is not None else list(topology.agents)
        return ReplanResult(
            replanned=True,
            reason="rerouted the remaining work",
            topology=make_topology(agent_ids, edges),
        )

    return build


def chain_factory():
    """Replan the running plan into a chain over the very same agents."""

    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del failed_agent_id
        agents = list(topology.agents)
        root = topology.root_agent or agents[0]
        ordered = [root] + [agent for agent in agents if agent != root]
        edges = [(ordered[index], ordered[index + 1]) for index in range(len(ordered) - 1)]
        return ReplanResult(
            replanned=True,
            reason="rerouted the remaining work",
            topology=make_topology(ordered, edges, root=root),
        )

    return build


def noop_factory(reason: str = "no viable recovery plan"):
    def build(topology: Topology, failed_agent_id: str) -> ReplanResult:
        del topology
        return ReplanResult(
            replanned=False, reason=reason, skipped_agents=[failed_agent_id]
        )

    return build


def run_diamond(
    outcome,
    failing: set[str] = None,
    max_concurrency: int | None = None,
    replanner_ref: list[ScriptedReplanner] | None = None,
):
    """Run the diamond DAG; B fails by default. Returns (scheduler, executor)."""
    agent_ids = ["A", "B", "C", "D"]
    executor = MockAgentExecutor(delay=0.005, fail_agent_ids=failing or {"B"})
    replanner = ScriptedReplanner(outcome, executor=executor)
    if replanner_ref is not None:
        replanner_ref.append(replanner)
    scheduler = AsyncDAGScheduler(
        executor=executor,
        max_concurrency=max_concurrency,
        retry_policy=RetryPolicy(max_retries=1),
        replanner=replanner,
    )
    results = asyncio.run(
        scheduler.run(
            Task(description="test"),
            make_topology(agent_ids, DIAMOND_EDGES),
            make_agents(agent_ids),
        )
    )
    return scheduler, executor, results


def run_session(monkeypatch: pytest.MonkeyPatch, replanner: ScriptedReplanner):
    """Real ``execute_task`` with only the Replanner swapped."""
    original = session_module.AsyncDAGScheduler

    def factory(*args: object, **kwargs: object) -> AsyncDAGScheduler:
        kwargs.setdefault("replanner", replanner)
        return original(*args, **kwargs)

    monkeypatch.setattr(session_module, "AsyncDAGScheduler", factory)
    return execute_task(MULTI_AGENT_TASK, fail_agent_ids={"data_analyst"})


# --- A. a valid change is really applied -----------------------------------


def test_valid_candidate_is_applied_to_the_scheduling_loop() -> None:
    scheduler, _executor, results = run_diamond(candidate_factory(REROUTED_EDGES))

    # Before the fix D stayed SKIPPED because the old B->D edge was still in force.
    assert results["D"].status is ExecutionStatus.SUCCESS
    assert scheduler.replan_events[0].applied is True


def test_applied_topology_changes_the_downstream_ready_decision() -> None:
    _scheduler, executor, results = run_diamond(candidate_factory(REROUTED_EDGES))

    assert executor.call_counts["D"] == 1  # scheduled once, from the new plan
    assert results["A"].status is ExecutionStatus.SUCCESS
    assert results["C"].status is ExecutionStatus.SUCCESS
    assert results["B"].status is ExecutionStatus.FAILED


def test_previous_and_new_topology_match_the_real_plans() -> None:
    holder: list[ScriptedReplanner] = []
    scheduler, _executor, _results = run_diamond(
        candidate_factory(REROUTED_EDGES), replanner_ref=holder
    )
    event = scheduler.replan_events[0]

    assert event.previous_topology == topology_signature(
        make_topology(["A", "B", "C", "D"], DIAMOND_EDGES)
    )
    assert event.new_topology == topology_signature(
        make_topology(["A", "B", "C", "D"], REROUTED_EDGES)
    )
    assert event.previous_topology != event.new_topology
    assert event.detail == ""


def test_applied_candidate_emits_exactly_one_replan_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replanner = ScriptedReplanner(chain_factory())
    session = run_session(monkeypatch, replanner)

    events = session.trace.of_type("AGENT_REPLANNED")
    assert len(events) == 1
    assert events[0].agent_id == "data_analyst"
    assert events[0].run_id == session.run_id


# --- B. an equivalent candidate is a no-op --------------------------------


def test_equivalent_candidate_is_not_applied() -> None:
    scheduler, executor, results = run_diamond(candidate_factory(DIAMOND_EDGES))

    assert scheduler.replan_events[0].applied is False
    assert "identical" in scheduler.replan_events[0].detail
    assert results["D"].status is ExecutionStatus.SKIPPED  # old plan still in force
    assert executor.call_counts.get("D", 0) == 0


def test_noop_candidate_is_not_applied_and_keeps_failure_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replanner = ScriptedReplanner(noop_factory())
    session = run_session(monkeypatch, replanner)

    assert session.trace.of_type("AGENT_REPLANNED") == []
    assert {event.agent_id for event in session.trace.of_type("AGENT_FAILED")} == {
        "data_analyst"
    }
    assert all(result.replanned is False for result in replanner.results)


# --- C. invalid candidates -------------------------------------------------


def test_cyclic_candidate_is_rejected_and_changes_nothing() -> None:
    with pytest.raises(TopologyValidationError):
        run_diamond(
            candidate_factory([("A", "B"), ("A", "C"), ("C", "D"), ("D", "C")])
        )


def test_unknown_node_is_rejected_by_the_topology_schema() -> None:
    """An edge pointing at a node outside ``agents`` cannot even be constructed."""
    with pytest.raises(ValueError, match="endpoint"):
        make_topology(["A", "B", "C", "D"], [("A", "B"), ("A", "Z")])


def test_invalid_candidate_emits_no_replan_event(monkeypatch: pytest.MonkeyPatch) -> None:
    replanner = ScriptedReplanner(
        candidate_factory([("A", "B"), ("A", "C"), ("C", "D"), ("D", "C")])
    )
    session = run_session(monkeypatch, replanner)

    assert session.trace.of_type("AGENT_REPLANNED") == []
    assert session.status.value == "failed"
    assert "Topology" in (session.error or "")


# --- D. unsupported topology changes are refused, not half-applied --------


def test_candidate_adding_an_agent_is_refused() -> None:
    scheduler, executor, results = run_diamond(
        candidate_factory(
            [("A", "B"), ("A", "C"), ("C", "D"), ("D", "E")],
            agents=["A", "B", "C", "D", "E"],
        )
    )

    assert scheduler.replan_events[0].applied is False
    assert "agent set" in scheduler.replan_events[0].detail
    # Old plan untouched: D is still skipped, and no phantom node was executed.
    assert results["D"].status is ExecutionStatus.SKIPPED
    assert "E" not in executor.call_counts


def test_candidate_removing_an_agent_is_refused() -> None:
    scheduler, _executor, results = run_diamond(
        candidate_factory([("A", "B"), ("A", "C")], agents=["A", "B", "C"])
    )

    assert scheduler.replan_events[0].applied is False
    assert "agent set" in scheduler.replan_events[0].detail
    # D was not dropped from the run: it is still resolved (skipped), never lost.
    assert results["D"].status is ExecutionStatus.SKIPPED


def test_refused_candidate_leaves_the_scheduler_in_a_terminal_state() -> None:
    """A refused candidate must not deadlock the wave loop."""
    _scheduler, _executor, results = run_diamond(
        candidate_factory([("A", "B"), ("A", "C")], agents=["A", "B", "C"])
    )
    assert set(results) == {"A", "B", "C", "D"}
    assert all(item.status is not ExecutionStatus.PENDING for item in results.values())


# --- E. finished agents are protected -------------------------------------


def test_completed_agents_are_not_reexecuted() -> None:
    _scheduler, executor, results = run_diamond(candidate_factory(REROUTED_EDGES))

    assert executor.call_counts["A"] == 1
    assert executor.call_counts["C"] == 1
    assert results["A"].status is ExecutionStatus.SUCCESS
    assert results["C"].status is ExecutionStatus.SUCCESS
    # The failed agent is not retried by the replan either.
    assert executor.call_counts["B"] == 2  # 1 attempt + 1 retry, then FAILED


def test_results_of_finished_agents_are_preserved() -> None:
    holder: list[ScriptedReplanner] = []
    scheduler, _executor, results = run_diamond(
        candidate_factory(REROUTED_EDGES), replanner_ref=holder
    )
    finished = {key: value.status for key, value in results.items() if key != "D"}
    assert finished == {
        "A": ExecutionStatus.SUCCESS,
        "B": ExecutionStatus.FAILED,
        "C": ExecutionStatus.SUCCESS,
    }
    assert len(scheduler.replan_events) == 1


# --- F. concurrency --------------------------------------------------------


def test_replan_runs_at_a_quiescent_point() -> None:
    """The wave is fully gathered before replanning: nothing is in flight."""
    holder: list[ScriptedReplanner] = []
    run_diamond(candidate_factory(REROUTED_EDGES), replanner_ref=holder)

    assert holder[0].in_flight_at_call == [0]


def test_application_respects_the_concurrency_cap() -> None:
    scheduler, executor, results = run_diamond(
        candidate_factory(REROUTED_EDGES), max_concurrency=2
    )

    assert scheduler.max_concurrency == 2
    assert executor.max_concurrent <= 2
    assert results["D"].status is ExecutionStatus.SUCCESS


def test_application_does_not_disturb_a_running_wave() -> None:
    """Two failures in one wave: each replan sees a settled wave, no reruns."""
    holder: list[ScriptedReplanner] = []
    scheduler, executor, results = run_diamond(
        candidate_factory(REROUTED_EDGES), failing={"B", "C"}, replanner_ref=holder
    )

    assert holder[0].in_flight_at_call == [0, 0]  # never mid-flight
    assert executor.call_counts["A"] == 1  # no agent was scheduled twice
    assert results["A"].status is ExecutionStatus.SUCCESS
    assert len(scheduler.replan_events) == 2


# --- G / H. regressions for AT-AUDIT-003 / 001 / 002 ----------------------


def test_noop_still_emits_no_event_after_the_application_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AT-AUDIT-003 must survive: no-op -> no event, even now that we can apply."""
    scheduler, _executor, results = run_diamond(noop_factory())
    assert scheduler.replan_events[0].applied is False
    assert results["D"].status is ExecutionStatus.SKIPPED

    session = run_session(monkeypatch, ScriptedReplanner(noop_factory()))
    assert session.trace.of_type("AGENT_REPLANNED") == []


def test_result_store_run_isolation_still_holds() -> None:
    """AT-AUDIT-002 partitions are untouched."""
    store = ResultStore()
    orchestrator = ResearchOrchestrator(
        provider=MockLLMProvider(), tool_mode="mock", store=store
    )
    asyncio.run(orchestrator.run(MULTI_AGENT_TASK))
    asyncio.run(orchestrator.run("分析竞争对手、市场规模、技术趋势，给出投资建议"))

    run_ids = store.runs()
    assert len(run_ids) == 2
    first, second = run_ids
    assert all(event.run_id == first for event in store.events_of(first))
    assert all(event.run_id == second for event in store.events_of(second))


def test_max_concurrency_is_still_forwarded_alongside_the_fix() -> None:
    """AT-AUDIT-001 parameter pass-through is unaffected."""
    scheduler = AsyncDAGScheduler(
        executor=MockAgentExecutor(),
        max_concurrency=3,
        replanner=ScriptedReplanner(noop_factory()),
    )
    assert scheduler.max_concurrency == 3
    with pytest.raises(TypeError):
        AsyncDAGScheduler(executor=MockAgentExecutor(), max_concurrency=1.5)
