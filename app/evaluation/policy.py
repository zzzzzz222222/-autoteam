from app.evaluation.models import TopologyEvaluation
from app.models.topology import TopologyType


class EvaluationPolicy:
    def explain(self, evaluation: TopologyEvaluation) -> TopologyEvaluation:
        metrics = evaluation.metrics
        if metrics.edge_count <= max(metrics.agent_count - 1, 0):
            evaluation.strengths.append("simple dependency structure")
        if metrics.topology_type is TopologyType.STAR:
            evaluation.observations.append("multiple agents depend directly on the root agent")
        elif metrics.topology_type is TopologyType.HIERARCHICAL:
            evaluation.strengths.append("balanced multi-level dependency structure")
        if metrics.parallelism <= 0.25 and metrics.agent_count > 1:
            evaluation.weaknesses.append("limited parallel execution")
        if metrics.parallelism >= 0.5:
            evaluation.strengths.append("high potential parallelism")
        if metrics.success_rate == 1.0:
            evaluation.observations.append("all agents completed successfully")
        if metrics.failure_count:
            evaluation.weaknesses.append("one or more agents failed")
        if metrics.recovery_count:
            evaluation.observations.append("retry recovery occurred")
        return evaluation
