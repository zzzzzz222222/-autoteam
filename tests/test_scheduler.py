import asyncio

import pytest

from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.models import ExecutionStatus
from app.scheduler.scheduler import AsyncDAGScheduler
from app.topology.validator import TopologyValidationError


def make_agent(agent_id: str) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        role=AgentRole(
            name=f"Agent {agent_id}", capabilities=[CapabilityName.TASK_PLANNING], goal="test"
        ),
    )


def make_topology(agent_ids: list[str], edges: list[tuple[str, str]]) -> Topology:
    return Topology(
        type=TopologyType.HIERARCHICAL,
        agents=agent_ids,
        edges=[TopologyEdge(source=source, target=target) for source, target in edges],
        root_agent=agent_ids[0] if agent_ids else None,
    )


def schedule(
    topology: Topology,
    executor: MockAgentExecutor,
    timeout: float | None = None,
    max_concurrency: int | None = None,
) -> dict[str, object]:
    agents = [make_agent(agent_id) for agent_id in topology.agents]
    return asyncio.run(
        AsyncDAGScheduler(executor, max_concurrency, timeout).run(
            Task(description="test"), topology, agents
        )
    )


def test_single_agent_succeeds() -> None:
    results = schedule(make_topology(["A"], []), MockAgentExecutor())
    assert results["A"].status is ExecutionStatus.SUCCESS


def test_chain_respects_execution_order() -> None:
    executor = MockAgentExecutor()
    results = schedule(make_topology(["A", "B", "C"], [("A", "B"), ("B", "C")]), executor)
    assert all(item.status is ExecutionStatus.SUCCESS for item in results.values())
    assert executor.execution_order == ["A", "B", "C"]


def test_parallel_children_execute_concurrently() -> None:
    executor = MockAgentExecutor(delay=0.01)
    schedule(make_topology(["A", "B", "C"], [("A", "B"), ("A", "C")]), executor)
    assert executor.execution_order[0] == "A"
    assert executor.max_concurrent >= 2


def test_diamond_waits_for_both_parents() -> None:
    executor = MockAgentExecutor(delay=0.01)
    results = schedule(
        make_topology(["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]),
        executor,
    )
    assert results["D"].status is ExecutionStatus.SUCCESS
    assert executor.execution_order.index("D") > executor.execution_order.index("B")
    assert executor.execution_order.index("D") > executor.execution_order.index("C")


def test_failed_upstream_skips_downstream() -> None:
    executor = MockAgentExecutor(fail_agent_ids={"B"})
    results = schedule(
        make_topology(["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]),
        executor,
    )
    assert results["B"].status is ExecutionStatus.FAILED
    assert results["C"].status is ExecutionStatus.SUCCESS
    assert results["D"].status is ExecutionStatus.SKIPPED


def test_timeout_becomes_failure() -> None:
    results = schedule(make_topology(["A"], []), MockAgentExecutor(delay=0.02), timeout=0.001)
    assert results["A"].status is ExecutionStatus.FAILED
    assert results["A"].error == "execution timeout"


def test_executor_exception_becomes_failure() -> None:
    results = schedule(make_topology(["A"], []), MockAgentExecutor(raise_agent_ids={"A"}))
    assert results["A"].status is ExecutionStatus.FAILED
    assert "exception" in (results["A"].error or "")


def test_invalid_cycle_is_rejected_before_execution() -> None:
    topology = make_topology(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
    with pytest.raises(TopologyValidationError):
        schedule(topology, MockAgentExecutor())


def test_unknown_agent_is_rejected_by_topology_model() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        make_topology(["A"], [("A", "X")])


def test_concurrency_limit_is_enforced() -> None:
    executor = MockAgentExecutor(delay=0.01)
    schedule(
        make_topology(["A", "B", "C", "D", "E"], [("A", "B"), ("A", "C"), ("A", "D"), ("A", "E")]),
        executor,
        max_concurrency=2,
    )
    assert executor.max_concurrent <= 2
    assert executor.max_concurrent == 2
