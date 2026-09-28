from pydantic import BaseModel, Field

from app.models.topology import TopologyType


class TopologyExecutionMetrics(BaseModel):
    topology_type: TopologyType
    agent_count: int
    edge_count: int
    duration: float
    success_count: int
    failure_count: int
    skipped_count: int
    success_rate: float
    failure_rate: float
    recovery_count: int
    max_concurrency: int
    parallelism: float
    completed: bool


class TopologyEvaluation(BaseModel):
    topology_type: TopologyType
    metrics: TopologyExecutionMetrics
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)


class TopologyComparison(BaseModel):
    evaluations: list[TopologyEvaluation] = Field(default_factory=list)
    best_by_duration: list[TopologyType] | None = None
    best_by_success_rate: list[TopologyType] | None = None
    highest_parallelism: list[TopologyType] | None = None
    most_reliable: list[TopologyType] | None = None
