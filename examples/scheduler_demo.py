import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.models import ExecutionStatus
from app.scheduler.scheduler import AsyncDAGScheduler
from main import configure_utf8_output


def agent(agent_id: str, name: str) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        role=AgentRole(name=name, capabilities=[CapabilityName.TASK_PLANNING], goal="完成演示任务"),
    )


async def run_demo() -> None:
    configure_utf8_output()
    task = Task(description="生成市场调研、竞争分析与最终报告")
    agents = [
        agent("A", "Planner"),
        agent("B", "Researcher"),
        agent("C", "Analyst"),
        agent("D", "Writer"),
    ]
    topology = Topology(
        type=TopologyType.HIERARCHICAL,
        agents=[spec.id for spec in agents if spec.id],
        edges=[
            TopologyEdge(source="A", target="B"),
            TopologyEdge(source="A", target="C"),
            TopologyEdge(source="B", target="D"),
            TopologyEdge(source="C", target="D"),
        ],
        root_agent="A",
    )
    executor = MockAgentExecutor(
        delay=0.05,
        on_start=lambda agent_id: print(f"[START] {agent_id}"),
        on_done=lambda agent_id: print(f"[DONE ] {agent_id}"),
    )
    results = await AsyncDAGScheduler(executor, max_concurrency=2).run(task, topology, agents)
    print("=" * 40)
    print("AutoTeam Day 3 — Async DAG Scheduler")
    print("=" * 40)
    print("Topology: Hierarchical\nGraph: A -> B, A -> C, B -> D, C -> D\n")
    print("Execution Summary")
    for agent_id in topology.agents:
        print(f"{agent_id:<3} {results[agent_id].status.value.upper()}")
    print(f"Max Concurrency: {executor.max_concurrent}")
    print(f"Total Agents: {len(agents)}")
    print(f"Successful: {sum(item.status is ExecutionStatus.SUCCESS for item in results.values())}")
    print(f"Failed: {sum(item.status is ExecutionStatus.FAILED for item in results.values())}")
    print(f"Skipped: {sum(item.status is ExecutionStatus.SKIPPED for item in results.values())}")


if __name__ == "__main__":
    asyncio.run(run_demo())
