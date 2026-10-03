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
from app.synthesis.evidence_filter import (
    collect_evidence_records,
    validate_report_references,
)
from app.synthesis.models import (
    EvidenceRecord,
    Finding,
    ReportBundle,
    SynthesisResult,
    Uncertainty,
)
from app.synthesis.source_policy import source_gaps
from app.synthesis.synthesizer import (
    SynthesisError,
    compute_finding_counts,
    derive_executive_summary,
    run_synthesis,
)


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

    conflicts: list[dict] = []
    evidence, sources = collect_evidence_records(artifacts, conflicts=conflicts)
    # v0.6.6 (A3): declarative source-gap audit — a deliverable whose declared
    # intent needs sourcing but has no bound snippet is reported, never dressed up.
    gaps = source_gaps(artifacts, evidence)
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
        if gaps:
            trace.record(
                "EVIDENCE_GAPS_FOUND",
                message=f"{len(gaps)} artifact(s) with structured evidence gaps",
                gap_count=len(gaps),
                artifacts=[gap["artifact_id"] for gap in gaps],
                reasons=[gap["reasons"][0] for gap in gaps][:10],
            )
        if conflicts:
            # v0.6.9 (F13): same identity, conflicting url/type -> split, never
            # silently overwritten. Surfaced as an auditable event.
            trace.record(
                "SOURCE_IDENTITY_CONFLICT",
                message=f"{len(conflicts)} source identity conflict(s) split",
                conflict_count=len(conflicts),
                reasons=[item["reason"][:200] for item in conflicts][:10],
            )

    failure_retry_count = 0
    try:
        synthesis = run_synthesis(task, artifacts, evidence, sources, provider=provider)
        status = "completed"
        reason = ""
    except SynthesisError as exc:
        failure_retry_count = int(getattr(exc, "retry_count", 0) or 0)
        if trace is not None:
            trace.record(
                "SYNTHESIS_FAILED",
                message="Synthesis could not produce a valid structured result",
                reason=str(exc)[:300],
                retry_count=failure_retry_count,
                error_class=type(exc).__name__,
            )
        partial = getattr(exc, "partial_result", None)
        if partial is not None:
            # Earlier stages succeeded: keep their validated output instead of
            # throwing it away for the generic per-artifact fallback.
            synthesis = partial
        else:
            synthesis = _degraded_result(task, artifacts, evidence)
            stage_audit = list(getattr(exc, "stage_audit", []) or [])
            if stage_audit:
                synthesis.stage_audit = stage_audit
        status = "degraded"
        reason = str(exc)[:300]

    _record_detail_events(trace, synthesis)

    retry_spent = int(getattr(synthesis, "retry_count", 0) or 0)
    if status != "completed":
        retry_spent = max(retry_spent, int(failure_retry_count or 0))
    # D2: authoritative finding breakdown, derived in code from the real finding
    # state + evidence bindings (the legacy LLM-proposed lists stay untouched).
    evidence_index = {
        str(getattr(item, "evidence_id", "") or ""): item for item in evidence
    }
    synthesis.finding_counts = compute_finding_counts(
        list(getattr(synthesis, "key_findings", []) or []), evidence_index
    )
    # D3: an empty executive summary must never render as a statistical sentence.
    summary_text, summary_status, summary_reason = derive_executive_summary(synthesis)
    synthesis.summary = summary_text
    synthesis.summary_status = summary_status
    synthesis.summary_reason = summary_reason
    if summary_status != "model" and trace is not None:
        event = (
            "SUMMARY_DERIVED"
            if summary_status == "derived_from_findings"
            else "SUMMARY_UNAVAILABLE"
        )
        trace.record(event, message=summary_reason)
    bundle = ReportBundle(
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
        fallback_used=status != "completed",
        fallback_reason=reason,
        retry_count=retry_spent,
        validation_errors=list(getattr(synthesis, "validation_errors", []) or []),
        stage_audit=list(getattr(synthesis, "stage_audit", []) or []),
        evidence_selection=dict(getattr(synthesis, "evidence_selection", {}) or {}),
        claim_audit=list(getattr(synthesis, "claim_audit", []) or []),
        source_gaps=gaps,
        source_conflicts=list(conflicts),
    )
    # Deterministic provenance audit — never an LLM judge. Issues are recorded
    # so the UI can say "reference missing" instead of inventing a link.
    issues = validate_report_references(bundle)
    bundle.reference_issues = issues
    if trace is not None:
        trace.record(
            "SYNTHESIS_VALIDATED",
            message=f"reference issues: {len(issues)}",
            issue_count=len(issues),
            issues=issues[:20],
        )
    return bundle


def _degraded_result(
    task: str,
    artifacts: list[AgentArtifact],
    evidence: list[EvidenceRecord],
) -> SynthesisResult:
    """Deterministic, *auditable* synthesis fallback.

    Findings are derived from the artifacts and their real evidence records only
    - nothing is invented. Every citation is a real ``evidence_id`` (validated
    below), rows without evidence stay ``unsupported``, and the same
    ``validate_synthesis`` pass (de-duplication + audit) used on the success
    path runs here too, so a degraded bundle is as traceable as a good one.
    """
    from app.synthesis.synthesizer import validate_synthesis

    by_agent: dict[str, list[EvidenceRecord]] = {}
    for item in evidence:
        by_agent.setdefault(item.producer_agent or "unknown", []).append(item)

    findings: list[Finding] = []
    for artifact in artifacts:
        producer = str(
            artifact.metadata.get("role_name") or artifact.agent_id or "unknown"
        )
        items = by_agent.get(artifact.agent_id) or by_agent.get(producer) or []
        findings.append(
            Finding(
                finding_id=f"find_fallback_{artifact.agent_id or 'agent'}",
                statement=(
                    f"[degraded synthesis] {producer} delivered a "
                    f"{artifact.output_type.value} artifact with "
                    f"{len(items)} traceable evidence record(s); cross-agent "
                    "conclusions could not be produced."
                ),
                evidence_ids=[item.evidence_id for item in items[:4]],
                supporting_agents=[producer],
                support_kind="unsupported",  # re-derived from the real refs below
                claim_type="unverified_claim",
                notes="degraded synthesis fallback (no cross-agent inference)",
            )
        )
    result = SynthesisResult(
        key_findings=findings,
        summary=(
            f"Synthesis degraded for task '{task[:100]}': cross-agent synthesis "
            "did not produce a valid structured result, so the report uses the "
            "deterministic fallback. Findings below are traceable per-artifact "
            "summaries, not cross-agent conclusions."
        ),
        uncertainties=[
            Uncertainty(
                uncertainty_id="unc_synthesis_degraded",
                statement=(
                    "Cross-agent synthesis failed, so insights, contradictions "
                    "and trade-offs may be incomplete."
                ),
                kind="insufficient_evidence",
                note="see the SYNTHESIS_FAILED event for the classified reason",
            )
        ],
        notes="degraded pipeline result",
    )
    issues: list[str] = []
    cleaned = validate_synthesis(result, evidence, issues)
    cleaned.validation_errors = issues
    return cleaned


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
