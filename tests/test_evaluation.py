import asyncio

from app.evaluation.evaluator import TopologyBenchmark, TopologyEvaluator
from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.retry import RetryPolicy
from app.topology.templates import build_chain, build_hierarchical, build_star


def setup() -> tuple[Task, list[AgentSpec], list[Topology]]:
    agents = [
        AgentSpec(
            id=item,
            role=AgentRole(name=item, capabilities=[CapabilityName.TASK_PLANNING], goal="test"),
        )
        for item in ["A", "B", "C", "D"]
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
    return Task(description="test"), agents, topologies


def test_evaluator_executes_validated_topology() -> None:
    task, agents, topologies = setup()
    evaluation = asyncio.run(
        TopologyEvaluator().evaluate(task, agents, topologies[0], MockAgentExecutor(delay=0.001))
    )
    assert evaluation.metrics.success_rate == 1.0
    assert evaluation.metrics.max_concurrency == 1


def test_benchmark_compares_all_candidates_independently() -> None:
    task, agents, topologies = setup()
    comparison = asyncio.run(
        TopologyBenchmark().compare(
            task, agents, topologies, lambda: MockAgentExecutor(delay=0.001)
        )
    )
    assert len(comparison.evaluations) == 3
    assert comparison.highest_parallelism is not None
    assert comparison.best_by_success_rate is not None


def test_evaluation_records_retry_recovery() -> None:
    task, agents, topologies = setup()
    evaluation = asyncio.run(
        TopologyEvaluator().evaluate(
            task,
            agents,
            topologies[0],
            MockAgentExecutor(failures_before_success={"B": 1}),
            retry_policy=RetryPolicy(max_retries=1),
        )
    )
    assert evaluation.metrics.recovery_count == 1
