import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from main import configure_utf8_output


async def scenario(failures: int) -> None:
    agents = [
        AgentSpec(
            id=item,
            role=AgentRole(name=item, capabilities=[CapabilityName.TASK_PLANNING], goal="demo"),
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
    executor = MockAgentExecutor(failures_before_success={"B": failures})
    scheduler = AsyncDAGScheduler(executor, retry_policy=RetryPolicy(max_retries=2))
    results = await scheduler.run(Task(description="Recovery demo"), topology, agents)
    print({agent_id: result.status.value for agent_id, result in results.items()})
    if scheduler.replan_events:
        event = scheduler.replan_events[0]
        print(f"[REPLAN] {event.failed_agent_id}: {event.reason}")


async def main() -> None:
    configure_utf8_output()
    print("AutoTeam Day 4 — Retry & Replan\nRetry succeeds on attempt 2:")
    await scenario(1)
    print("Retry exhausted; downstream is skipped:")
    await scenario(3)


if __name__ == "__main__":
    asyncio.run(main())
