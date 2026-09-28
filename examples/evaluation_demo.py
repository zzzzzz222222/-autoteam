import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.evaluator import TopologyBenchmark
from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology
from app.scheduler.executor import MockAgentExecutor
from app.topology.templates import build_chain, build_hierarchical, build_star
from main import configure_utf8_output


async def main() -> None:
    configure_utf8_output()
    task = Task(description="Create a market research report")
    agents = [
        AgentSpec(
            id=item,
            role=AgentRole(name=item, capabilities=[CapabilityName.TASK_PLANNING], goal="demo"),
        )
        for item in ["Researcher", "Analyst", "Writer", "Reviewer"]
    ]
    ids = [agent.id for agent in agents if agent.id]
    topologies = [
        Topology(
            type=proposal.topology_type,
            agents=ids,
            edges=proposal.edges,
            root_agent=proposal.root_agent,
        )
        for proposal in [build_chain(ids), build_star(ids), build_hierarchical(ids)]
    ]
    comparison = await TopologyBenchmark().compare(
        task, agents, topologies, lambda: MockAgentExecutor(delay=0.01)
    )
    print("AutoTeam Topology Evaluation")
    for evaluation in comparison.evaluations:
        metrics = evaluation.metrics
        print(
            f"{evaluation.topology_type.value.upper()}: duration={metrics.duration:.3f}s "
            f"success={metrics.success_rate:.0%} failures={metrics.failure_rate:.0%} "
            f"concurrency={metrics.max_concurrency} parallelism={metrics.parallelism:.0%}"
        )
    print("Shortest Duration:", [item.value for item in comparison.best_by_duration or []])
    print("Highest Parallelism:", [item.value for item in comparison.highest_parallelism or []])


if __name__ == "__main__":
    asyncio.run(main())
