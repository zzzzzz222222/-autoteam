"""API request/response schemas (thin DTOs; the Core models stay authoritative)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field("real", pattern="^(real|offline)$")


class TaskCreatedResponse(BaseModel):
    task_id: str
    status: str = "created"


class AgentSummary(BaseModel):
    id: str
    name: str
    status: str
    attempt: int = 1
    error: str | None = None
    duration: float | None = None


class TaskSnapshot(BaseModel):
    task_id: str
    task: str
    mode: str
    run_id: str = ""
    status: str
    agent_names: dict[str, str] = Field(default_factory=dict)
    agent_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    layers: list[list[str]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    event_count: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    created_at: float = 0
    final_artifact: dict[str, Any] | None = None


class TeamResponse(BaseModel):
    """Dynamic team built by the real Dynamic Team Core."""

    task: str
    agents: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    layers: list[list[str]] = Field(default_factory=list)
    explanation: dict[str, Any] | None = None


class ArtifactSummary(BaseModel):
    artifact_id: str
    agent_id: str
    agent_name: str = ""
    output_type: str
    title: str = ""
    content: str = ""
    structured_data: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    source_records: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactsResponse(BaseModel):
    task_id: str
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class FinalResultResponse(BaseModel):
    task_id: str
    status: str
    title: str = ""
    markdown: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[dict[str, Any]] = Field(default_factory=list)