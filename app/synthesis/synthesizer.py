"""Cross-agent synthesis (v0.6.0).

The LLM proposes a ``SynthesisResult`` from filtered evidence + artifacts;
this module then deterministically validates every ``evidence_id`` reference.
Invalid references are dropped (or the whole item is marked invalid) — the
system never fabricates evidence to make a citation look complete.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.llm.provider import LLMProvider, MockLLMProvider
from app.runtime.artifacts import AgentArtifact
from app.synthesis.evidence_filter import validate_evidence_references
from app.synthesis.models import (
    Contradiction,
    EvidenceRecord,
    Finding,
    Insight,
    Recommendation,
    SourceRecord,
    SynthesisResult,
    Tradeoff,
    Uncertainty,
)

_ID_LIST_KEYS = {
    "supporting_evidence_ids",
    "evidence_ids",
    "source_ids",
    "supporting_artifact_ids",
    "supporting_insight_ids",
    "supporting_tradeoff_ids",
}


class SynthesisError(RuntimeError):
    """Synthesis could not produce a valid structured result."""


def _excerpt(text: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def build_synthesis_prompt(
    task: str,
    artifacts: list[AgentArtifact],
    evidence: list[EvidenceRecord],
    sources: list[SourceRecord],
) -> str:
    """Assemble a compact, evidence-grounded prompt for the synthesis model."""
    agent_lines = []
    for artifact in artifacts:
        agent_lines.append(
            f"- [{artifact.artifact_id}] agent={artifact.agent_id} "
            f"type={artifact.output_type.value} title={artifact.title!r}\n"
            f"  summary: {_excerpt(artifact.content, 280)}"
        )
    evidence_lines = []
    for item in evidence:
        evidence_lines.append(
            f"- {item.evidence_id} | agent={item.producer_agent} | "
            f"artifact={item.artifact_id} | source={item.source_id} "
            f"({item.source_type})\n"
            f"  claim: {_excerpt(item.claim, 200)}\n"
            f"  support: {_excerpt(item.evidence, 160)}"
        )
    source_lines = [
        f"- {s.source_id}: {s.title or s.url or s.source_type} "
        f"[{s.source_type}] {s.url}"
        for s in sources
    ]
    return (
        "You are the synthesis agent for a multi-agent research team.\n"
        "Combine the agents' findings into ONE cross-agent synthesis. "
        "Do NOT concatenate agent texts.\n\n"
        f"TASK:\n{task}\n\n"
        "AGENT ARTIFACTS:\n" + ("\n".join(agent_lines) or "- (none)") + "\n\n"
        "EVIDENCE RECORDS (use ONLY these evidence_ids):\n"
        + ("\n".join(evidence_lines) or "- (none)")
        + "\n\nSOURCES:\n"
        + ("\n".join(source_lines) or "- (none)")
        + """

Return JSON matching SynthesisResult with:
- summary: 3-5 sentence executive summary of the COMBINED result
- key_findings: what multiple agents together establish (findings[] with
  finding_id, statement, evidence_ids, supporting_agents, support_kind)
- supported_findings: findings backed by 2+ evidence items / agents
- single_source_findings: findings backed by exactly one source
- cross_agent_insights: judgments that COMBINE at least two evidence items
  into a new conclusion (insights[] with insight_id, statement,
  supporting_evidence_ids, supporting_artifact_ids, producer_agents,
  uncertainty)
- contradictions: claims that conflict (contradictions[] with
  contradiction_id, claim_a, claim_b, evidence_ids, source_ids, agents,
  status='resolved'|'unresolved', resolution)
- uncertainties: thin spots (uncertainties[] with uncertainty_id, statement,
  evidence_ids, kind='insufficient_evidence'|'single_source'|'conflicting'|'vague')
- tradeoffs: real tensions from THIS task (tradeoffs[] with tradeoff_id,
  dimension, option_a, option_b, gains_a, costs_a, gains_b, costs_b,
  evidence_ids, implications)
- recommendations: proposals traceable to insights/tradeoffs/evidence
  (recommendations[] with recommendation_id, statement,
  supporting_insight_ids, supporting_tradeoff_ids, supporting_evidence_ids,
  limitations, status='supported'|'potential'|'unsupported')

Rules:
1. Only cite evidence_ids listed above. Never invent ids or URLs.
2. If evidence is thin, say so in uncertainties — do not fabricate certainty.
3. Recommendations with no supporting evidence must use status='unsupported'.
4. No quality scores, no self-grading, no percentages of confidence.
5. Write statements in the same language as the TASK.
"""
    )


def _sanitize_finding(item: Finding, known: set[str]) -> Finding | None:
    valid, invalid = validate_evidence_references(item.evidence_ids, known)
    if invalid and not valid:
        return None
    if invalid:
        item.notes = (item.notes + f" dropped_invalid_refs={invalid}").strip()
    item.evidence_ids = valid
    return item


def _sanitize_insight(item: Insight, known: set[str]) -> Insight | None:
    valid, _ = validate_evidence_references(item.supporting_evidence_ids, known)
    if not valid:
        return None
    item.supporting_evidence_ids = valid
    return item


def _sanitize_contradiction(item: Contradiction, known: set[str]) -> Contradiction | None:
    valid, _ = validate_evidence_references(item.evidence_ids, known)
    if not valid:
        return None
    item.evidence_ids = valid
    return item


def _sanitize_uncertainty(item: Uncertainty, known: set[str]) -> Uncertainty | None:
    valid, _ = validate_evidence_references(item.evidence_ids, known)
    item.evidence_ids = valid
    return item  # uncertainties may cite nothing — that is the point


def _sanitize_tradeoff(item: Tradeoff, known: set[str]) -> Tradeoff | None:
    valid, _ = validate_evidence_references(item.evidence_ids, known)
    if not valid:
        return None
    item.evidence_ids = valid
    return item


def _sanitize_recommendation(item: Recommendation, known: set[str]) -> Recommendation | None:
    valid, _ = validate_evidence_references(item.supporting_evidence_ids, known)
    item.supporting_evidence_ids = valid
    if valid:
        item.status = "supported"
    elif item.supporting_insight_ids or item.supporting_tradeoff_ids:
        item.status = "potential"
    else:
        item.status = "unsupported"
    return item


def _ensure_id(prefix: str, index: int, current: str) -> str:
    return current.strip() or f"{prefix}_{index:02d}"


def validate_synthesis(
    result: SynthesisResult, evidence: list[EvidenceRecord]
) -> SynthesisResult:
    """Deterministically drop / repair items with bad evidence references.

    IDs the LLM omitted are assigned here — never invented as citations.
    """
    known = {item.evidence_id for item in evidence}
    cleaned = SynthesisResult(summary=result.summary, notes=result.notes)

    for index, item in enumerate(result.key_findings, start=1):
        item.finding_id = _ensure_id("find", index, item.finding_id)
        kept = _sanitize_finding(item, known)
        if kept is not None:
            cleaned.key_findings.append(kept)
    for index, item in enumerate(result.supported_findings, start=1):
        item.finding_id = _ensure_id("sfind", index, item.finding_id)
        kept = _sanitize_finding(item, known)
        if kept is not None:
            cleaned.supported_findings.append(kept)
    for index, item in enumerate(result.single_source_findings, start=1):
        item.finding_id = _ensure_id("ufind", index, item.finding_id)
        kept = _sanitize_finding(item, known)
        if kept is not None:
            cleaned.single_source_findings.append(kept)
    for index, item in enumerate(result.cross_agent_insights, start=1):
        item.insight_id = _ensure_id("ins", index, item.insight_id)
        kept = _sanitize_insight(item, known)
        if kept is not None:
            cleaned.cross_agent_insights.append(kept)
    for index, item in enumerate(result.contradictions, start=1):
        item.contradiction_id = _ensure_id("con", index, item.contradiction_id)
        kept = _sanitize_contradiction(item, known)
        if kept is not None:
            cleaned.contradictions.append(kept)
    for index, item in enumerate(result.uncertainties, start=1):
        item.uncertainty_id = _ensure_id("unc", index, item.uncertainty_id)
        kept = _sanitize_uncertainty(item, known)
        if kept is not None:
            cleaned.uncertainties.append(kept)
    for index, item in enumerate(result.tradeoffs, start=1):
        item.tradeoff_id = _ensure_id("trd", index, item.tradeoff_id)
        kept = _sanitize_tradeoff(item, known)
        if kept is not None:
            cleaned.tradeoffs.append(kept)
    for index, item in enumerate(result.recommendations, start=1):
        item.recommendation_id = _ensure_id("rec", index, item.recommendation_id)
        kept = _sanitize_recommendation(item, known)
        if kept is not None:
            cleaned.recommendations.append(kept)

    # keep recommendation ↔ insight / tradeoff links consistent
    insight_ids = {item.insight_id for item in cleaned.cross_agent_insights}
    tradeoff_ids = {item.tradeoff_id for item in cleaned.tradeoffs}
    for rec in cleaned.recommendations:
        rec.supporting_insight_ids = [
            ref for ref in rec.supporting_insight_ids if ref in insight_ids
        ]
        rec.supporting_tradeoff_ids = [
            ref for ref in rec.supporting_tradeoff_ids if ref in tradeoff_ids
        ]
    return cleaned


def _fallback_result(
    task: str, artifacts: list[AgentArtifact], evidence: list[EvidenceRecord]
) -> SynthesisResult:
    """Deterministic synthesis when the LLM cannot produce valid JSON.

    Still cross-references real evidence — never invents content.
    """
    by_agent: dict[str, list[EvidenceRecord]] = {}
    for item in evidence:
        by_agent.setdefault(item.producer_agent or "unknown", []).append(item)

    findings: list[Finding] = []
    for agent, items in by_agent.items():
        statement = f"{agent} contributes {len(items)} evidence-backed claim(s)"
        findings.append(
            Finding(
                finding_id=_stable("find", agent),
                statement=statement,
                evidence_ids=[i.evidence_id for i in items[:4]],
                supporting_agents=[agent],
                support_kind="single_source",
            )
        )
    summary = (
        f"Synthesis fallback: collected {len(evidence)} evidence records "
        f"from {len(artifacts)} artifacts for task: {task[:120]}"
    )
    return SynthesisResult(
        key_findings=findings,
        single_source_findings=findings,
        summary=summary,
        notes="fallback: provider did not return a valid SynthesisResult",
    )


def _stable(prefix: str, *parts: str) -> str:
    import hashlib

    return f"{prefix}_{hashlib.sha1('|'.join(parts).encode()).hexdigest()[:8]}"


def run_synthesis(
    task: str,
    artifacts: list[AgentArtifact],
    evidence: list[EvidenceRecord],
    sources: list[SourceRecord],
    provider: LLMProvider | None = None,
) -> SynthesisResult:
    """LLM proposes → Schema constrains → Code validates."""
    active = provider or MockLLMProvider()
    prompt = build_synthesis_prompt(task, artifacts, evidence, sources)
    try:
        proposed = active.structured_completion(prompt, SynthesisResult)
        if not isinstance(proposed, SynthesisResult):
            raise SynthesisError("provider returned a non-SynthesisResult object")
    except (ValidationError, SynthesisError, ValueError, TypeError) as exc:
        raise SynthesisError(f"Invalid structured response: {exc}") from exc
    except Exception as exc:  # provider/network failures surface as synthesis errors
        raise SynthesisError(f"Structured output parsing failed: {exc}") from exc

    if not evidence:
        # nothing to cite — return the proposal but force uncertainty
        proposed.uncertainties.append(
            Uncertainty(
                uncertainty_id="unc_empty_evidence",
                statement="No verified evidence records were collected from agents.",
                kind="insufficient_evidence",
            )
        )
    return validate_synthesis(proposed, evidence)


def dump_synthesis_debug(result: SynthesisResult) -> str:
    """Developer-facing JSON dump (not user-facing chain-of-thought)."""
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
