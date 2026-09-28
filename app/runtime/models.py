"""Structured outputs produced by research agents (v0.2.0).

Every agent returns a Pydantic model so the same object can be validated by the
schema layer, shared with downstream agents, rendered in the UI, and aggregated
into the final ResearchReport. This is the "Schema constrains" half of the core
design principle: the LLM proposes a structured object, the schema validates it.
"""

from pydantic import BaseModel, Field


class CompetitorInfo(BaseModel):
    name: str = ""
    focus: str = ""
    notes: str = ""


class ResearchFindings(BaseModel):
    summary: str = ""
    key_trends: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class CompetitorFindings(BaseModel):
    summary: str = ""
    competitors: list[CompetitorInfo] = Field(default_factory=list)


class TechnologyFindings(BaseModel):
    summary: str = ""
    trends: list[str] = Field(default_factory=list)


class Subtask(BaseModel):
    description: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    depends_on: list[int] = Field(default_factory=list)  # indices into the plan
    target_role: str = ""


class SubtaskPlan(BaseModel):
    goal: str = ""
    subtasks: list[Subtask] = Field(default_factory=list)


class ReportDraft(BaseModel):
    """Synthesized draft returned by the Report Writer agent before code aggregates."""

    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Final aggregated report produced by the orchestrator (code aggregates, LLM proposes)."""

    task: str = ""
    summary: str = ""
    market_overview: ResearchFindings | None = None
    competitors: CompetitorFindings | None = None
    technology: TechnologyFindings | None = None
    sources: list[str] = Field(default_factory=list)
    generated_at: str = ""


class TaskDeliverable(BaseModel):
    """Generic structured deliverable returned by dynamically generated agents (v0.3.0)."""

    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
