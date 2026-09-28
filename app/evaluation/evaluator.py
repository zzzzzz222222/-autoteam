import time
from collections.abc import Callable

from app.evaluation.metrics import TopologyMetricsCollector
from app.evaluation.models import TopologyComparison, TopologyEvaluation
from app.evaluation.policy import EvaluationPolicy
from app.models.agent import AgentSpec
from app.models.task import Task
from app.models.topology import Topology, TopologyType
from app.scheduler.executor import AgentExecutor
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.topology.validator import TopologyValidator


class TopologyEvaluator:
    def __init__(
        self,
        collector: TopologyMetricsCollector | None = None,
        policy: EvaluationPolicy | None = None,
    ) -> None:
        self.collector = collector or TopologyMetricsCollector()
        self.policy = policy or EvaluationPolicy()

    async def evaluate(
        self,
        task: Task,
        agents: list[AgentSpec],
        topology: Topology,
        executor: AgentExecutor,
        *,
        max_concurrency: int | None = None,
        timeout: float | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> TopologyEvaluation:
        TopologyValidator().validate(topology)
        scheduler = AsyncDAGScheduler(executor, max_concurrency, timeout, retry_policy)
        started = time.perf_counter()
        results = await scheduler.run(task, topology, agents)
        duration = time.perf_counter() - started
        observed = int(getattr(executor, "max_concurrent", 0))
        metrics = self.collector.collect(topology, results, duration, observed)
        return self.policy.explain(TopologyEvaluation(topology_type=topology.type, metrics=metrics))


class TopologyBenchmark:
    def __init__(self, evaluator: TopologyEvaluator | None = None) -> None:
        self.evaluator = evaluator or TopologyEvaluator()

    async def compare(
        self,
        task: Task,
        agents: list[AgentSpec],
        topologies: list[Topology],
        executor_factory: Callable[[], AgentExecutor],
        **scheduler_config: object,
    ) -> TopologyComparison:
        evaluations = []
        for topology in topologies:
            evaluations.append(
                await self.evaluator.evaluate(
                    task, agents, topology, executor_factory(), **scheduler_config
                )
            )
        return self._comparison(evaluations)

    def compare_evaluations(self, evaluations: list[TopologyEvaluation]) -> TopologyComparison:
        """Build a comparison from evaluations that were collected elsewhere.

        Used when a caller (for example the UI) already owns the execution results
        and only needs the Day 5 comparison rules applied to them.
        """
        return self._comparison(evaluations)

    @staticmethod
    def _leaders(
        evaluations: list[TopologyEvaluation], field: str, reverse: bool = False
    ) -> list[TopologyType] | None:
        if not evaluations:
            return None
        values = [getattr(item.metrics, field) for item in evaluations]
        target = max(values) if reverse else min(values)
        return sorted(
            [item.topology_type for item in evaluations if getattr(item.metrics, field) == target],
            key=lambda item: item.value,
        )

    def _comparison(self, evaluations: list[TopologyEvaluation]) -> TopologyComparison:
        return TopologyComparison(
            evaluations=evaluations,
            best_by_duration=self._leaders(evaluations, "duration"),
            best_by_success_rate=self._leaders(evaluations, "success_rate", True),
            highest_parallelism=self._leaders(evaluations, "parallelism", True),
            most_reliable=self._leaders(evaluations, "failure_rate"),
        )
