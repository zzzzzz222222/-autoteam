"""Synthesis pipeline orchestration (v0.6.0).

    AgentArtifact[]
        ↓
    EvidenceFilter (deterministic)
        ↓
    EvidenceRecord[] / SourceRecord[]
        ↓
    Cross-Agent Synthesis (LLM proposes, Schema constrains, Code validates)
        ↓
    ReportBundle (insights / contradictions / trade-offs / recommendations)

``run_synthesis_pipeline`` never raises for content problems — it returns a
``ReportBundle`` with ``status`` set so the session can degrade to the legacy
assembler. Infrastructure errors are recorded in ``degradation_reason``.
"""

from __future__ import annotations

from app.llm.provider import LLMProvider
from app.runtime.artifacts import AgentArtifact
from app.runtime.events import ExecutionTrace
from app.synthesis.evidence_filter import collect_evidence_records
from app.synthesis.models import ReportBundle, SynthesisResult
from app.synthesis.synthesizer import SynthesisError, run_synthesis


def run_synthesis_pipeline(
    task: str,
    artifacts: list[AgentArtifact],
    provider: LLMProvider | None = None,
    trace: ExecutionTrace | None = None,
) -> ReportBundle:
    """Filter evidence, run cross-agent synthesis, and package the result."""
    if not artifacts:
        if trace is not None:
            trace.record(
                "SYNTHESIS_FAILED",
                message="no artifacts available for synthesis",
            )
        return ReportBundle(task=task, status="failed", degradation_reason="no artifacts")

    if trace is not None:
        trace.record(
            "SYNTHESIS_STARTED",
            message=f"synthesizing {len(artifacts)} artifacts",
            artifact_count=len(artifacts),
        )

    evidence, sources = collect_evidence_records(artifacts)
    if trace is not None:
        trace.record(
            "EVIDENCE_FILTERED",
            message=f"{len(evidence)} evidence / {len(sources)} sources after filtering",
            evidence_count=len(evidence),
            source_count=len(sources),
            producer_agents=sorted(
                {item.producer_agent for item in evidence if item.producer_agent}
            ),
        )

    try:
        synthesis = run_synthesis(task, artifacts, evidence, sources, provider=provider)
        status = "completed"
        reason = ""
    except SynthesisError as exc:
        if trace is not None:
            trace.record(
                "SYNTHESIS_FAILED",
                message="Synthesis could not produce a valid structured result",
                reason=str(exc)[:300],
            )
        synthesis = _degraded_result(task, artifacts, evidence)
        status = "degraded"
        reason = str(exc)[:300]

    _record_detail_events(trace, synthesis)

    return ReportBundle(
        task=task,
        synthesis=synthesis,
        evidence=evidence,
        sources=sources,
        artifact_ids=[artifact.artifact_id for artifact in artifacts],
        producer_agents=sorted(
            {item.producer_agent for item in evidence if item.producer_agent}
        ),
        status=status,
        degradation_reason=reason,
    )


def _degraded_result(task: str, artifacts, evidence) -> SynthesisResult:
    """Minimal structured result so the report still has a synthesis section."""
    from app.synthesis.models import Finding, Uncertainty

    findings = [
        Finding(
            finding_id=f"find_art_{index + 1:02d}",
            statement=(
                f"Artifact {artifact.artifact_id} ({artifact.output_type.value}) "
                f"produced by {artifact.agent_id}."
            ),
            evidence_ids=[],
            supporting_agents=[artifact.agent_id],
            support_kind="unsupported",
        )
        for index, artifact in enumerate(artifacts)
    ]
    return SynthesisResult(
        key_findings=findings,
        summary=(
            f"Synthesis degraded for task '{task[:100]}': "
            "legacy assembly used; cross-agent insights unavailable."
        ),
        uncertainties=[
            Uncertainty(
                uncertainty_id="unc_synthesis_degraded",
                statement=(
                    "Cross-agent synthesis failed, so insights, contradictions "
                    "and trade-offs may be incomplete."
                ),
                kind="insufficient_evidence",
                note="see SYNTHESIS_FAILED event for the reason",
            )
        ],
        notes="degraded pipeline result",
    )


def _record_detail_events(trace: ExecutionTrace | None, result: SynthesisResult) -> None:
    if trace is None:
        return
    if result.cross_agent_insights:
        trace.record(
            "INSIGHT_EXTRACTED",
            message=f"{len(result.cross_agent_insights)} insight(s)",
            insight_ids=[item.insight_id for item in result.cross_agent_insights],
            supporting_evidence_ids=[
                list(item.supporting_evidence_ids) for item in result.cross_agent_insights
            ],
        )
    if result.contradictions:
        trace.record(
            "CONTRADICTION_FOUND",
            message=f"{len(result.contradictions)} contradiction(s)",
            contradiction_ids=[item.contradiction_id for item in result.contradictions],
            statuses=[item.status for item in result.contradictions],
        )
    if result.tradeoffs:
        trace.record(
            "TRADEOFF_FOUND",
            message=f"{len(result.tradeoffs)} trade-off(s)",
            tradeoff_ids=[item.tradeoff_id for item in result.tradeoffs],
            dimensions=[item.dimension for item in result.tradeoffs],
        )
    trace.record(
        "SYNTHESIS_COMPLETED",
        message=(
            f"insights={len(result.cross_agent_insights)} "
            f"contradictions={len(result.contradictions)} "
            f"tradeoffs={len(result.tradeoffs)} "
            f"recommendations={len(result.recommendations)}"
        ),
        insight_count=len(result.cross_agent_insights),
        contradiction_count=len(result.contradictions),
        tradeoff_count=len(result.tradeoffs),
        recommendation_count=len(result.recommendations),
    )
