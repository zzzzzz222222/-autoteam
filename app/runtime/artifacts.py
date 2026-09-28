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


class AgentArtifact(BaseModel):
    artifact_id: str
    agent_id: str
    task_id: str = ""
    output_type: ArtifactType
    title: str = ""
    content: str = ""  # readable markdown body
    structured_data: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # upstream artifact ids
    created_at: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


def artifact_type_for(expected_output: str) -> ArtifactType:
    return EXPECTED_OUTPUT_TO_TYPE.get(expected_output, ArtifactType.ANALYSIS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
