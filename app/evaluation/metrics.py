from app.evaluation.models import TopologyExecutionMetrics
from app.models.topology import Topology
from app.scheduler.models import AgentResult, ExecutionStatus
from app.topology.validator import calculate_metrics


class TopologyMetricsCollector:
    def collect(
        self,
        topology: Topology,
        results: dict[str, AgentResult],
        duration: float,
        max_concurrency: int,
    ) -> TopologyExecutionMetrics:
        agent_count = len(topology.agents)
        statuses = [results.get(agent_id) for agent_id in topology.agents]
        success_count = sum(
            item is not None and item.status is ExecutionStatus.SUCCESS for item in statuses
        )
        failure_count = sum(
            item is not None and item.status is ExecutionStatus.FAILED for item in statuses
        )
        skipped_count = sum(
            item is not None and item.status is ExecutionStatus.SKIPPED for item in statuses
        )
        recovery_count = sum(
            item is not None and item.status is ExecutionStatus.SUCCESS and item.attempt > 1
            for item in statuses
        )
        structure = calculate_metrics(topology)
        return TopologyExecutionMetrics(
            topology_type=topology.type,
            agent_count=agent_count,
            edge_count=len(topology.edges),
            duration=duration,
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=skipped_count,
            success_rate=success_count / agent_count if agent_count else 0.0,
            failure_rate=failure_count / agent_count if agent_count else 0.0,
            recovery_count=recovery_count,
            max_concurrency=max_concurrency,
            parallelism=structure.parallelism,
            completed=success_count + failure_count + skipped_count == agent_count,
        )
