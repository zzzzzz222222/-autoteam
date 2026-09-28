from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.agent import AgentSpec
from app.models.task import Task
from app.models.topology import Topology


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentResult(BaseModel):
    agent_id: str
    status: ExecutionStatus
    output: Any | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    duration: float | None = None
    attempt: int = 1
    attempts: list["ExecutionAttempt"] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_duration(self) -> "AgentResult":
        if self.started_at is not None and self.finished_at is not None:
            self.duration = self.finished_at - self.started_at
        return self


class ExecutionAttempt(BaseModel):
    agent_id: str
    attempt: int
    status: ExecutionStatus
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    duration: float | None = None

    @model_validator(mode="after")
    def calculate_duration(self) -> "ExecutionAttempt":
        if self.started_at is not None and self.finished_at is not None:
            self.duration = self.finished_at - self.started_at
        return self


class ExecutionContext:
    """Read-only execution data made available to an AgentExecutor."""

    def __init__(
        self,
        task: Task,
        topology: Topology,
        agents: Mapping[str, AgentSpec],
        results: Mapping[str, AgentResult],
    ) -> None:
        self.task = task
        self.topology = topology
        self.agents = agents
        self._results = results

    @property
    def results(self) -> Mapping[str, AgentResult]:
        return self._results

    def get_result(self, agent_id: str) -> AgentResult | None:
        return self._results.get(agent_id)

    def get_upstream_results(self, agent_id: str) -> dict[str, AgentResult]:
        upstream = {edge.source for edge in self.topology.edges if edge.target == agent_id}
        return {source: self._results[source] for source in upstream if source in self._results}
