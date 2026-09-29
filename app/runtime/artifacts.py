"""Unified artifact system (v0.4.0).

Every dynamic agent produces one ``AgentArtifact`` — an addressable, dependency-
aware intermediate result that downstream agents read and the assembler combines
into the final deliverable. ``AgentDeliverable`` is what the LLM provider returns
for a dynamic agent; the runtime wraps it into an artifact (code fills ids,
dependencies and metadata — the LLM never does).

Offline artifacts carry ``metadata["source_type"] = "offline_mock"``.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ArtifactType(str, Enum):
    RESEARCH_FINDINGS = "research_findings"
    ANALYSIS = "analysis"
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    DESIGN = "design"
    DATABASE_DESIGN = "database_design"
    IMPLEMENTATION_PLAN = "implementation_plan"
    TEST_REPORT = "test_report"
    BUSINESS_ANALYSIS = "business_analysis"
    PROPOSAL = "proposal"
    REPORT = "report"


# subtask expected_output (v0.3.0 decomposer) -> artifact type
EXPECTED_OUTPUT_TO_TYPE: dict[str, ArtifactType] = {
    "market_overview": ArtifactType.RESEARCH_FINDINGS,
    "competitor_landscape": ArtifactType.ANALYSIS,
    "technology_trends": ArtifactType.ANALYSIS,
    "customer_insights": ArtifactType.RESEARCH_FINDINGS,
    "data_insights": ArtifactType.ANALYSIS,
    "financial_assessment": ArtifactType.BUSINESS_ANALYSIS,
    "strategy_document": ArtifactType.BUSINESS_ANALYSIS,
    "requirements_document": ArtifactType.REQUIREMENTS,
    "architecture_design": ArtifactType.ARCHITECTURE,
    "database_schema": ArtifactType.DATABASE_DESIGN,
    "api_specification": ArtifactType.DESIGN,
    "backend_implementation": ArtifactType.IMPLEMENTATION_PLAN,
    "test_plan": ArtifactType.TEST_REPORT,
    "final_report": ArtifactType.REPORT,
    "proposal_document": ArtifactType.PROPOSAL,
    "deliverable": ArtifactType.ANALYSIS,
    "work_plan": ArtifactType.ANALYSIS,
}


def _flatten_json(value: object) -> object:
    """Reduce a nested LLM-proposed value to a scalar/string deterministically.

    Real providers may return ``structured_data`` values (or ``sources`` items)
    that are dicts/lists rather than plain strings. Downstream consumers only
    render these as ``f"{k}={v}"`` lines, so any nested structure is safely
    flattened to a stable JSON string here — Schema constrains, Code validates.
    """
    if isinstance(value, (dict, list, tuple)):
        return _json.dumps(value, ensure_ascii=False)
    return value


class AgentDeliverable(BaseModel):
    """Structured proposal returned by the provider for a dynamic agent."""

    @field_validator("structured_data", mode="before")
    @classmethod
    def _flatten_data(cls, value):
        if isinstance(value, dict):
            return {k: _flatten_json(v) for k, v in value.items()}
        return value

    @field_validator("sources", "key_points", mode="before")
    @classmethod
    def _flatten_list(cls, value):
        if isinstance(value, list):
            return [_flatten_json(item) for item in value]
        return value

    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    structured_data: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)


class Source(BaseModel):
    """A retrievable provenance record. Offline sources have no URL and are
    always marked ``offline_mock`` — real URLs are never fabricated."""

    id: str
    title: str = ""
    url: str = ""
    source_type: str = "offline_mock"  # "web" | "offline_mock" | "local_file"
    retrieved_at: str = ""


class Evidence(BaseModel):
    """A claim backed by a registered source. ``source_id`` must exist in the
    artifact's ``source_records`` (validated by ``app.runtime.validation``)."""

    claim: str
    evidence: str = ""
    source_id: str


class ToolCall(BaseModel):
    """Schema for an LLM-requested tool invocation (never free text)."""

    tool_name: str

    @field_validator("arguments", mode="before")
    @classmethod
    def _flatten_arguments(cls, value):
        """Real providers emit scalar arg values (e.g. ``max_results: 10``) that
        are ints/floats, not strings. Tools read ``arguments.get(...)`` and
        tolerate non-``str`` only if coerced, so flatten every value to ``str``
        here — Schema constrains, Code validates."""
        if isinstance(value, dict):
            return {k: _flatten_json(v) for k, v in value.items()}
        return value

    arguments: dict[str, str] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """One decision round for a real-LLM agent: call a tool, or finish."""

    action: str = "finish"  # "call_tool" | "finish"
    tool_call: ToolCall | None = None
    deliverable: AgentDeliverable | None = None


class AgentArtifact(BaseModel):
    artifact_id: str
    agent_id: str
    task_id: str = ""
    output_type: ArtifactType
    title: str = ""
    content: str = ""  # readable markdown body
    structured_data: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    source_records: list[Source] = Field(default_factory=list)  # v0.5.0 provenance
    evidence: list[Evidence] = Field(default_factory=list)  # v0.5.0 claims+refs
    dependencies: list[str] = Field(default_factory=list)  # upstream artifact ids
    created_at: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


def artifact_type_for(expected_output: str) -> ArtifactType:
    return EXPECTED_OUTPUT_TO_TYPE.get(expected_output, ArtifactType.ANALYSIS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
