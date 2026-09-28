import asyncio

from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.models import ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler


def test_replan_records_exhaustion_and_preserves_successes() -> None:
    agents = [
        AgentSpec(
            id=item,
            role=AgentRole(name=item, capabilities=[CapabilityName.TASK_PLANNING], goal="test"),
        )
        for item in ["A", "B", "C", "D"]
    ]
    topology = Topology(
        type=TopologyType.HIERARCHICAL,
        agents=["A", "B", "C", "D"],
        edges=[
            TopologyEdge(source="A", target="B"),
            TopologyEdge(source="A", target="C"),
            TopologyEdge(source="B", target="D"),
            TopologyEdge(source="C", target="D"),
        ],
        root_agent="A",
    )
    executor = MockAgentExecutor(fail_agent_ids={"B"})
    scheduler = AsyncDAGScheduler(executor, retry_policy=RetryPolicy(max_retries=1))
    results = asyncio.run(scheduler.run(Task(description="test"), topology, agents))
    assert results["A"].status is ExecutionStatus.SUCCESS
    assert results["B"].attempt == 2
    assert results["C"].status is ExecutionStatus.SUCCESS
    assert results["D"].status is ExecutionStatus.SKIPPED
    assert scheduler.replan_events[0].failed_agent_id == "B"
