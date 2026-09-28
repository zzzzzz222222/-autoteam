from app.evaluation.metrics import TopologyMetricsCollector
from app.models.topology import Topology, TopologyType
from app.scheduler.models import AgentResult, ExecutionStatus


def test_metrics_handle_recovery_and_zero_agents() -> None:
    collector = TopologyMetricsCollector()
    empty = Topology(type=TopologyType.CHAIN, agents=[], edges=[])
    assert collector.collect(empty, {}, 0.1, 0).success_rate == 0.0
    topology = Topology(type=TopologyType.CHAIN, agents=["A", "B"], edges=[])
    results = {
        "A": AgentResult(agent_id="A", status=ExecutionStatus.SUCCESS, attempt=2),
        "B": AgentResult(agent_id="B", status=ExecutionStatus.SKIPPED),
    }
    metrics = collector.collect(topology, results, 0.1, 1)
    assert (
        metrics.recovery_count == 1 and metrics.skipped_count == 1 and metrics.failure_rate == 0.0
    )
