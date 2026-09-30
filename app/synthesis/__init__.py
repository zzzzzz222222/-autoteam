"""v0.6.0 Agent Team Synthesis.

Post-scheduler pipeline that turns independent agent artifacts into
evidence-filtered, cross-agent synthesis results:

    AgentArtifact[]
      → EvidenceFilter (deterministic)
      → Cross-Agent Synthesis (LLM proposes, Schema constrains, Code validates)
      → Insight / Contradiction / Uncertainty / Trade-off / Recommendation
      → ReportBundle → FinalArtifact

This package never joins the DAG and never replaces the scheduler. It runs in
``execute_task`` after artifacts are collected, and degrades to the legacy
``ArtifactAssembler`` when synthesis itself fails.
"""

from app.synthesis.models import (
    Contradiction,
    EvidenceRecord,
    Finding,
    Insight,
    Recommendation,
    ReportBundle,
    SynthesisResult,
    Tradeoff,
    Uncertainty,
)
from app.synthesis.pipeline import run_synthesis_pipeline

__all__ = [
    "Contradiction",
    "EvidenceRecord",
    "Finding",
    "Insight",
    "Recommendation",
    "ReportBundle",
    "SynthesisResult",
    "Tradeoff",
    "Uncertainty",
    "run_synthesis_pipeline",
]
