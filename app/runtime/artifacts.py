"""Unified artifact system (v0.4.0).

Every dynamic agent produces one ``AgentArtifact`` — an addressable, dependency-
aware intermediate result that downstream agents read and the assembler combines
into the final deliverable. ``AgentDeliverable`` is what the LLM provider returns
for a dynamic agent; the runtime wraps it into an artifact (code fills ids,
dependencies and metadata — the LLM never does).

Offline artifacts carry ``metadata["source_type"] = "offline_mock"``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


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


class AgentDeliverable(BaseModel):
    """Structured proposal returned by the provider for a dynamic agent."""

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
