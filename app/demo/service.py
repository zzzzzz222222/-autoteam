"""Pure-Python orchestration used by the Streamlit UI and the UI tests.

This module is an adapter: it wires the existing Day 1-5 components together and
converts their outputs into plain dictionaries / dataclasses that are easy to
render. Nothing here re-implements team formation, topology generation, DAG
validation, scheduling, retry, replan or evaluation.
"""

import time
from dataclasses import dataclass, field
from enum import Enum

from app.allocator.role_allocator import RoleAllocator
from app.analyzer.task_analyzer import TaskAnalyzer
from app.demo.tasks import DEFAULT_TASK_DESCRIPTION
from app.evaluation.evaluator import TopologyBenchmark
from app.evaluation.metrics import TopologyMetricsCollector
from app.evaluation.models import TopologyComparison, TopologyEvaluation
from app.evaluation.policy import EvaluationPolicy
from app.models.agent import AgentSpec
from app.models.task import Task, TaskAnalysis
from app.models.topology import Topology
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.models import AgentResult, ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.topology.generator import TopologyGenerator
from app.topology.validator import calculate_metrics

DEFAULT_DELAY = 0.05


class FailureMode(str, Enum):
    """Failure injections supported by the UI demo."""

    NONE = "none"
    RETRY_SUCCESS = "retry_success"
    RETRY_EXHAUSTED = "retry_exhausted"


@dataclass(frozen=True)
class RunConfig:
    """How the demo should execute a topology."""

    delay: float = DEFAULT_DELAY
    max_concurrency: int | None = None
    failure_mode: FailureMode = FailureMode.NONE
    failure_agent_id: str | None = None


@dataclass(frozen=True)
class TeamBlueprint:
    """Result of Day 1: task analysis plus the allocated agent team."""

    task: Task
    analysis: TaskAnalysis
    agents: list[AgentSpec]

    @property
    def capabilities(self) -> list[str]:
        return [capability.value for capability in self.analysis.required_capabilities]

    def agent_ids(self) -> list[str]:
        return [agent.id for agent in self.agents if agent.id is not None]

    def labels(self) -> dict[str, str]:
        return {agent.id: agent.role.name for agent in self.agents if agent.id is not None}


@dataclass(frozen=True)
class ExecutionRun:
    """Result of one topology execution, ready to be rendered."""

    topology: Topology
    results: dict[str, AgentResult]
    duration: float
    max_concurrency: int
    started_at: float
    replan_events: list[str] = field(default_factory=list)
    failure_agent_id: str | None = None

    def status_of(self, agent_id: str) -> str:
        result = self.results.get(agent_id)
        return result.status.value if result else ExecutionStatus.PENDING.value

    def skip_reason(self, agent_id: str) -> str:
        result = self.results.get(agent_id)
        if result is None or result.status is not ExecutionStatus.SKIPPED:
            return ""
        detail = result.error or "upstream dependency unavailable"
        return f"Skipped because {detail}."

    def retried_agents(self) -> list[str]:
        return [
            agent_id
            for agent_id in self.topology.agents
            if (self.results.get(agent_id) is not None and len(self.results[agent_id].attempts) > 1)
        ]


def build_team(description: str) -> TeamBlueprint:
    """Day 1: task description -> capability analysis -> allocated agent team."""
    task = Task(description=description.strip() or DEFAULT_TASK_DESCRIPTION)
    analysis = TaskAnalyzer().analyze(task)
    return TeamBlueprint(task=task, analysis=analysis, agents=RoleAllocator().allocate(analysis))


def build_candidates(team: TeamBlueprint) -> list[Topology]:
    """Day 2: agent team -> validated Chain / Star / Hierarchical candidates."""
    return TopologyGenerator().generate_candidates(team.task, team.agents)


def topology_summary(topology: Topology) -> dict[str, object]:
    """Structural metrics of a candidate, computed by the existing validator."""
    metrics = calculate_metrics(topology)
    return {
        "type": topology.type.value,
        "agents": metrics.agent_count,
        "edges": metrics.edge_count,
        "steps": metrics.step_count,
        "parallelism": metrics.parallelism,
        "layers": [list(layer) for layer in topology.parallel_layers],
        "edges_text": ", ".join(f"{edge.source} -> {edge.target}" for edge in topology.edges),
    }


def suggest_failure_agent(topology: Topology) -> str | None:
    """Pick an agent whose failure is visible: it must have downstream dependents."""
    if not topology.agents:
        return None
    sources = {edge.source for edge in topology.edges}
    preferred = [agent_id for agent_id in topology.agents if agent_id in sources]
    if not preferred:
        return topology.agents[-1]
    if len(preferred) > 1:
        return preferred[1]
    return preferred[0]


def _retry_policy(config: RunConfig) -> RetryPolicy:
    if config.failure_mode is FailureMode.RETRY_SUCCESS:
        return RetryPolicy(max_retries=2)
    if config.failure_mode is FailureMode.RETRY_EXHAUSTED:
        return RetryPolicy(max_retries=1)
    return RetryPolicy(max_retries=0)


def _build_executor(config: RunConfig) -> MockAgentExecutor:
    """Build the offline mock executor described by ``config``."""
    target = config.failure_agent_id
    if config.failure_mode is FailureMode.NONE or not target:
        return MockAgentExecutor(delay=config.delay)
    if config.failure_mode is FailureMode.RETRY_SUCCESS:
        return MockAgentExecutor(delay=config.delay, failures_before_success={target: 1})
    return MockAgentExecutor(delay=config.delay, fail_agent_ids={target})


async def run_topology(team: TeamBlueprint, topology: Topology, config: RunConfig) -> ExecutionRun:
    """Execute one topology through the existing async DAG scheduler."""
    executor = _build_executor(config)
    scheduler = AsyncDAGScheduler(
        executor,
        max_concurrency=config.max_concurrency,
        retry_policy=_retry_policy(config),
    )
    started = time.perf_counter()
    results = await scheduler.run(team.task, topology, team.agents)
    duration = time.perf_counter() - started
    replan_events = [
        f"{event.failed_agent_id}: {event.reason}" for event in scheduler.replan_events
    ]
    return ExecutionRun(
        topology=topology,
        results=results,
        duration=duration,
        max_concurrency=int(executor.max_concurrent),
        started_at=started,
        replan_events=replan_events,
        failure_agent_id=(
            config.failure_agent_id if config.failure_mode is not FailureMode.NONE else None
        ),
    )


async def run_all(
    team: TeamBlueprint, topologies: list[Topology], config: RunConfig
) -> list[ExecutionRun]:
    return [await run_topology(team, topology, config) for topology in topologies]


def evaluate_runs(runs: list[ExecutionRun]) -> TopologyComparison:
    """Day 5: turn finished runs into metrics plus a metric-specific comparison.

    Reuses the existing collector and policy so the numbers shown next to an
    execution come from that exact execution instead of a second replay.
    """
    evaluations = [
        EvaluationPolicy().explain(
            TopologyEvaluation(
                topology_type=run.topology.type,
                metrics=TopologyMetricsCollector().collect(
                    run.topology, run.results, run.duration, run.max_concurrency
                ),
            )
        )
        for run in runs
    ]
    return TopologyBenchmark().compare_evaluations(evaluations)
