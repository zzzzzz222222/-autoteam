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
from app.synthesis.claim_support import (
    audit_claim_support,
    derive_review_status,
    support_profile,
)
from app.synthesis.evidence_filter import validate_evidence_references
from app.synthesis.evidence_selection import (
    MAX_EVIDENCE_PER_AGENT as MAX_EVIDENCE_PER_AGENT_DEFAULT,
)
from app.synthesis.evidence_selection import MAX_EVIDENCE_TOTAL as MAX_EVIDENCE_TOTAL_DEFAULT
from app.synthesis.evidence_selection import select_evidence
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
from app.synthesis.prompts import FULL_SCHEMA_TEXT, SHARED_RULES_TEXT

_ID_LIST_KEYS = {
    "supporting_evidence_ids",
    "evidence_ids",
    "source_ids",
    "supporting_artifact_ids",
    "supporting_insight_ids",
    "supporting_tradeoff_ids",
}


class SynthesisError(RuntimeError):
    """Synthesis could not produce a valid structured result.

    ``retry_count`` records how many corrective re-asks were spent before
    giving up, so the degraded fallback can report the real cost.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_count: int = 0,
        partial_result: "SynthesisResult | None" = None,
        stage_audit: list[dict] | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_count = retry_count
        # A staged pipeline keeps whatever earlier stages produced, so a later
        # stage failure degrades to *validated partial* output, not to nothing.
        self.partial_result = partial_result
        self.stage_audit = list(stage_audit or [])


def _excerpt(text: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


# Output-scale controls (v0.6.2). Synthesis used to ask one response for every
# category with no ceilings, which truncated on large inputs. These are
# prompt-side budgets only: the full evidence list stays in the bundle/report.
# v0.6.6: the *ranking* that fills this budget lives in ``evidence_selection``.
MAX_EVIDENCE_PER_AGENT = MAX_EVIDENCE_PER_AGENT_DEFAULT
MAX_EVIDENCE_TOTAL = MAX_EVIDENCE_TOTAL_DEFAULT
STAGE_STATEMENT_MAX_CHARS = 200

_FULL_INSTRUCTIONS = (
    FULL_SCHEMA_TEXT + chr(10) * 2 + SHARED_RULES_TEXT
)

_STAGE_FIELDS = {
    "facts": (
        "key_findings",
        "supported_findings",
        "single_source_findings",
        "contradictions",
        "uncertainties",
    ),
    "implications": ("cross_agent_insights", "tradeoffs", "recommendations"),
}
_STAGE_ORDER = ("facts", "implications")
_STAGE_CAPS = {
    "facts": "at most 6 key_findings, 4 contradictions, 5 uncertainties",
    "implications": "at most 4 cross_agent_insights, 3 tradeoffs, 5 recommendations",
}
_STAGE_ITEM_SCHEMA = {
    "facts": (
        "findings[] = {finding_id, statement, evidence_ids, supporting_agents, "
        "support_kind, claim_type, derivation}; "
        "contradictions[] = {contradiction_id, claim_a, claim_b, evidence_ids, "
        "source_ids, agents, status, resolution}; "
        "uncertainties[] = {uncertainty_id, statement, evidence_ids, kind, note}"
    ),
    "implications": (
        "insights[] = {insight_id, statement, supporting_evidence_ids, "
        "supporting_artifact_ids, producer_agents, uncertainty, claim_type, derivation}; "
        "tradeoffs[] = {tradeoff_id, dimension, option_a, option_b, gains_a, costs_a, "
        "gains_b, costs_b, evidence_ids, implications}; "
        "recommendations[] = {recommendation_id, statement, supporting_insight_ids, "
        "supporting_tradeoff_ids, supporting_evidence_ids, limitations, status, claim_type}"
    ),
}


def _stage_instructions(stage: str, fields: tuple[str, ...], extra_rules: str = "") -> str:
    lines = [
        f"STAGED SYNTHESIS - stage '{stage}'. Fill ONLY these keys: {', '.join(fields)}. "
        "Every other list MUST be [].",
        f"- Output budget: {_STAGE_CAPS[stage]}",
        f"- Keep every statement <= {STAGE_STATEMENT_MAX_CHARS} characters and every "
        "derivation to one short sentence.",
        f"- Item schema: {_STAGE_ITEM_SCHEMA[stage]}",
        "",
        SHARED_RULES_TEXT,
    ]
    return chr(10).join(lines) + extra_rules


def select_prompt_evidence(
    evidence: list[EvidenceRecord],
    *,
    per_agent: int = MAX_EVIDENCE_PER_AGENT,
    total: int = MAX_EVIDENCE_TOTAL,
) -> list[EvidenceRecord]:
    """Deterministic, bounded evidence selection for the PROMPT only.

    v0.6.6: delegates to :mod:`app.synthesis.evidence_selection`, which ranks by
    auditable value (bound snippet → unique key number → sole source → risk →
    coverage) instead of taking the first records in ``(agent, id)`` order. The
    stored records are untouched; only what the model sees is bounded.
    """
    return select_evidence(evidence, per_agent=per_agent, total=total).chosen


def build_synthesis_prompt(
    task: str,
    artifacts: list[AgentArtifact],
    evidence: list[EvidenceRecord],
    sources: list[SourceRecord],
    *,
    stage: str = "all",
    stage_fields: tuple[str, ...] | None = None,
    prior_findings: list[Finding] | None = None,
    extra_rules: str = "",
) -> str:
    """Assemble a compact, evidence-grounded prompt for the synthesis model.

    ``stage='all'`` keeps the original single-shot behaviour; a named stage asks
    for a strict subset of the schema with explicit per-category ceilings.
    """
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
    prior_lines: list[str] = []
    for prior in prior_findings or []:
        prior_lines.append(
            f"- {prior.finding_id} [{prior.support_kind}] {_excerpt(prior.statement, 200)}"
            f" (evidence: {', '.join(prior.evidence_ids) or 'none'})"
        )

    if stage == "all":
        instructions = _FULL_INSTRUCTIONS
    else:
        instructions = _stage_instructions(stage, tuple(stage_fields or ()), extra_rules)

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
        + (
            chr(10) + chr(10) + "PRIOR FINDINGS (previous stage; cite their evidence ids, "
            "do not restate them as new findings):" + chr(10) + chr(10).join(prior_lines)
            if prior_lines
            else ""
        )
        + chr(10)
        + instructions
    )


def _sanitize_finding(
    item: Finding, known: set[str], by_id: dict[str, EvidenceRecord]
) -> Finding | None:
    valid, invalid = validate_evidence_references(item.evidence_ids, known)
    if invalid and not valid:
        return None
    if invalid:
        item.notes = (item.notes + f" dropped_invalid_refs={invalid}").strip()
    item.evidence_ids = valid
    profile = support_profile(valid, by_id, claim_type=item.claim_type)
    item.support_kind = profile.support_kind
    item.evidence_count = profile.evidence_count
    item.agent_support_count = profile.agent_support_count
    item.independent_source_count = profile.independent_source_count
    item.support_level = profile.support_level
    if profile.agents:
        item.supporting_agents = profile.agents
    # v0.6.6 (A1): verify that the cited snippets actually carry the numbers the
    # finding asserts. This never edits ``evidence_ids`` — unmatched numbers are
    # reported, and a record that carries them but was not cited stays a
    # *candidate* for human review.
    audit = audit_claim_support(item.statement, valid, by_id, pool=list(by_id.values()))
    item.support_audit = audit
    item.review_status = derive_review_status(valid, by_id, audit)
    item.unsupported_parts = list(audit.get("numbers_missing") or [])
    return item


def _derive_support(
    evidence_ids: list[str], by_id: dict[str, EvidenceRecord]
) -> tuple[str, list[str]]:
    """Backward-compatible shim over :func:`support_profile`.

    ``multi_source`` now requires **two or more distinct independent sources** (a
    real cross-source check). Several agents agreeing without any bound source is
    ``multi_agent`` — the old field can no longer imply sourcing it never had.
    """
    profile = support_profile(evidence_ids, by_id)
    return profile.support_kind, profile.agents


# --- finding de-duplication (v0.6.1) ---------------------------------------
# The LLM may put the same conclusion in key_findings AND in
# supported/single_source_findings. Those lists overlap by construction, so the
# report used to render the same finding several times. Merging is deterministic
# and explainable (normalised statement equality, or token-set Jaccard above a
# high threshold) so genuinely different findings are never collapsed.
FINDING_MERGE_THRESHOLD = 0.85
_STATEMENT_NOISE = re.compile(r"[\s\*\-#_`「」【】（）()：:，,。.、;；!！?？\"'“”‘’]+")


def _normalize_statement(text: str) -> str:
    return _STATEMENT_NOISE.sub("", (text or "").lower())


def _statement_tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9._%-]*", lowered))
    cjk = re.findall(r"[一-鿿]", lowered)
    tokens.update("".join(pair) for pair in zip(cjk, cjk[1:], strict=False))
    return {token for token in tokens if len(token) > 1}


def statement_similarity(left: str, right: str) -> float:
    """Explainable similarity: identical normalised text, else token-set Jaccard."""
    norm_left, norm_right = _normalize_statement(left), _normalize_statement(right)
    if norm_left and norm_left == norm_right:
        return 1.0
    tokens_left, tokens_right = _statement_tokens(norm_left), _statement_tokens(norm_right)
    if not tokens_left or not tokens_right:
        return 0.0
    return len(tokens_left & tokens_right) / len(tokens_left | tokens_right)


def merge_findings(
    findings: list[Finding], by_id: dict[str, EvidenceRecord]
) -> tuple[list[Finding], list[dict[str, object]]]:
    """Merge duplicate findings, unioning their evidence and keeping the audit."""
    merged: list[Finding] = []
    groups: list[dict[str, object]] = []
    for item in findings:
        target = next(
            (
                existing
                for existing in merged
                if statement_similarity(existing.statement, item.statement)
                >= FINDING_MERGE_THRESHOLD
            ),
            None,
        )
        if target is None:
            merged.append(item)
            continue
        added = [ref for ref in item.evidence_ids if ref not in target.evidence_ids]
        target.evidence_ids = list(dict.fromkeys([*target.evidence_ids, *item.evidence_ids]))
        # Re-derive every support field from the *union*: merging two partial
        # citations must not leave stale counts behind (v0.6.6).
        kind, agents = _derive_support(target.evidence_ids, by_id)
        target.support_kind = kind
        target.supporting_agents = agents
        profile = support_profile(target.evidence_ids, by_id, claim_type=target.claim_type)
        target.evidence_count = profile.evidence_count
        target.agent_support_count = profile.agent_support_count
        target.independent_source_count = profile.independent_source_count
        target.support_level = profile.support_level
        marker = f"merged_from: {item.finding_id}"
        target.notes = f"{target.notes}; {marker}".strip("; ") if target.notes else marker
        groups.append(
            {
                "kept": target.finding_id,
                "merged": item.finding_id,
                "statement": item.statement[:120],
                "evidence_added": added,
                "support_kind": kind,
            }
        )
    return merged, groups


def _sanitize_insight(
    item: Insight, known: set[str], by_id: dict[str, EvidenceRecord]
) -> Insight | None:
    valid, _ = validate_evidence_references(item.supporting_evidence_ids, known)
    if not valid:
        return None
    item.supporting_evidence_ids = valid
    _, agents = _derive_support(valid, by_id)
    item.contributing_agents = agents
    # v0.6.6 (A4-A7): insights carry the same agent/source split as findings.
    profile = support_profile(valid, by_id, claim_type=item.claim_type)
    item.evidence_count = profile.evidence_count
    item.agent_support_count = profile.agent_support_count
    item.independent_source_count = profile.independent_source_count
    item.support_level = profile.support_level
    if len(agents) < 2 and not item.uncertainty:
        item.uncertainty = "single agent — not a cross-agent conclusion"
    return item


def _sanitize_contradiction(
    item: Contradiction, known: set[str], by_id: dict[str, EvidenceRecord]
) -> Contradiction | None:
    valid, _ = validate_evidence_references(item.evidence_ids, known)
    if not valid:
        return None
    item.evidence_ids = valid
    # v0.6.9 (F13/acceptance §12.8): ``source_ids`` are LLM-proposed, so they are
    # checked against the sources the run actually recorded. An unresolvable id
    # is dropped (never rendered as a valid reference) and noted for audit.
    real_sources = {record.source_id for record in by_id.values() if record.source_id}
    kept_sources = [sid for sid in (item.source_ids or []) if sid in real_sources]
    dropped_sources = [sid for sid in (item.source_ids or []) if sid not in real_sources]
    item.source_ids = list(dict.fromkeys(kept_sources))
    if dropped_sources:
        item.resolution = (
            f"{item.resolution} [dropped unresolved source_ids={dropped_sources}]"
        ).strip()
    _, agents = _derive_support(valid, by_id)
    if agents:
        item.agents = agents  # deterministic producer attribution, never invented
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


def _drop_issue(kind: str, item_id: str, refs: list[str], known: set[str]) -> str:
    """Human-readable reason for a dropped item, naming the dangling ids."""
    invalid = [ref for ref in (refs or []) if ref not in known]
    return f"dropped {kind} {item_id}: unresolved reference(s) {invalid or '[]'}"


def validate_synthesis(
    result: SynthesisResult,
    evidence: list[EvidenceRecord],
    issues: list[str] | None = None,
) -> SynthesisResult:
    """Deterministically drop / repair items with bad evidence references.

    IDs the LLM omitted are assigned here — never invented as citations.
    """
    known = {item.evidence_id for item in evidence}
    by_id = {item.evidence_id: item for item in evidence}
    cleaned = SynthesisResult(summary=result.summary, notes=result.notes)
    # v0.6.6 (A1): code-owned citation audit trail for every final finding.
    claim_audit: list[dict] = []

    for index, item in enumerate(result.key_findings, start=1):
        item.finding_id = _ensure_id("find", index, item.finding_id)
        kept = _sanitize_finding(item, known, by_id)
        if kept is not None:
            cleaned.key_findings.append(kept)
        elif issues is not None:
            issues.append(_drop_issue("finding", item.finding_id, item.evidence_ids, known))
    for index, item in enumerate(result.supported_findings, start=1):
        item.finding_id = _ensure_id("sfind", index, item.finding_id)
        kept = _sanitize_finding(item, known, by_id)
        if kept is not None:
            cleaned.supported_findings.append(kept)
        elif issues is not None:
            issues.append(f"dropped finding {item.finding_id}: unresolved reference")
    for index, item in enumerate(result.single_source_findings, start=1):
        item.finding_id = _ensure_id("ufind", index, item.finding_id)
        kept = _sanitize_finding(item, known, by_id)
        if kept is not None:
            cleaned.single_source_findings.append(kept)
        elif issues is not None:
            issues.append(f"dropped finding {item.finding_id}: unresolved reference")
    for index, item in enumerate(result.cross_agent_insights, start=1):
        item.insight_id = _ensure_id("ins", index, item.insight_id)
        kept = _sanitize_insight(item, known, by_id)
        if kept is not None:
            cleaned.cross_agent_insights.append(kept)
        elif issues is not None:
            issues.append(
                _drop_issue(
                    "insight", item.insight_id, item.supporting_evidence_ids, known
                )
            )
    for index, item in enumerate(result.contradictions, start=1):
        item.contradiction_id = _ensure_id("con", index, item.contradiction_id)
        kept = _sanitize_contradiction(item, known, by_id)
        if kept is not None:
            cleaned.contradictions.append(kept)
        elif issues is not None:
            issues.append(
                _drop_issue(
                    "contradiction", item.contradiction_id, item.evidence_ids, known
                )
            )
    for index, item in enumerate(result.uncertainties, start=1):
        item.uncertainty_id = _ensure_id("unc", index, item.uncertainty_id)
        kept = _sanitize_uncertainty(item, known)
        if kept is not None:
            cleaned.uncertainties.append(kept)
        elif issues is not None:
            issues.append(
                _drop_issue("uncertainty", item.uncertainty_id, item.evidence_ids, known)
            )
    for index, item in enumerate(result.tradeoffs, start=1):
        item.tradeoff_id = _ensure_id("trd", index, item.tradeoff_id)
        kept = _sanitize_tradeoff(item, known)
        if kept is not None:
            cleaned.tradeoffs.append(kept)
        elif issues is not None:
            issues.append(
                _drop_issue("trade-off", item.tradeoff_id, item.evidence_ids, known)
            )
    for index, item in enumerate(result.recommendations, start=1):
        item.recommendation_id = _ensure_id("rec", index, item.recommendation_id)
        kept = _sanitize_recommendation(item, known)
        if kept is not None:
            cleaned.recommendations.append(kept)

    # --- de-duplicate findings across the three overlapping lists ------------
    before_counts = {
        "key_findings": len(cleaned.key_findings),
        "supported_findings": len(cleaned.supported_findings),
        "single_source_findings": len(cleaned.single_source_findings),
    }
    merged, merge_groups = merge_findings(
        [*cleaned.key_findings, *cleaned.supported_findings, *cleaned.single_source_findings],
        by_id,
    )
    # One canonical list; the other two stay in the schema but are now empty so
    # no consumer can render the same finding twice.
    cleaned.key_findings = merged
    cleaned.supported_findings = []
    cleaned.single_source_findings = []
    dedup_audit = {
        "before": before_counts,
        "before_total": sum(before_counts.values()),
        "after": len(merged),
        "merged_groups": merge_groups,
    }
    existing_notes = cleaned.notes or ""
    cleaned.notes = (
        f"{existing_notes} | dedup: {json.dumps(dedup_audit, ensure_ascii=False)}"
        if existing_notes
        else f"dedup: {json.dumps(dedup_audit, ensure_ascii=False)}"
    )

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

    # --- v0.6.6 (A1): per-finding citation audit summary ----------------------
    for item in cleaned.key_findings:
        audit = dict(item.support_audit or {})
        audit["finding_id"] = item.finding_id
        audit["review_status"] = item.review_status
        audit["support_kind"] = item.support_kind
        audit["support_level"] = item.support_level
        audit["agent_support_count"] = item.agent_support_count
        audit["independent_source_count"] = item.independent_source_count
        claim_audit.append(audit)
    cleaned.claim_audit = claim_audit
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


# Bounded corrective retry (v0.6.1). A malformed payload is usually a
# formatting slip, so we re-ask with an explicit instruction. Every retry is a
# REAL provider call and therefore consumes the caller's LLM budget
# (CountingProvider enforces the ceiling) - retries never bypass it, and
# non-retryable failures (transport/auth/budget) are not retried at all.
SYNTHESIS_RETRY_ATTEMPTS = 2
SYNTHESIS_CORRECTION_HINT = (
    "\n\nIMPORTANT: your previous reply was rejected because it was not valid JSON "
    "matching the requested schema. Reply with ONE JSON object only - no markdown "
    "code fences, no explanation before or after, no trailing commas, no comments."
)


TRUNCATION_RECOVERY_RULES = (
    chr(10) + chr(10) +
    "IMPORTANT: the previous reply was CUT OFF because it was too long. Return a "
    "SMALLER answer: at most 2 items per list, each statement <= 120 characters, "
    "the summary <= 2 sentences, no extra commentary. Valid JSON only."
)


def _attempt_hint(attempt: int, last_category: str) -> str:
    """Corrective suffix for a re-ask (never repeats the same request verbatim)."""
    if attempt <= 1:
        return ""
    if last_category in {"truncated", "length_limit"}:
        return TRUNCATION_RECOVERY_RULES
    return SYNTHESIS_CORRECTION_HINT


# --- D2: deterministic finding classification --------------------------------
# ``supported_findings`` / ``single_source_findings`` are LLM-proposed legacy
# lists that the model routinely leaves empty, so counting them reported 0 next
# to 14 real findings. The breakdown below is derived in CODE from the real
# finding state + evidence bindings, so it can never drift from the data.
# v0.6.2 (AT-AUDIT-004): ``supported`` means backed by EXTERNAL evidence.
#
# ``agent_consensus`` (several agents agree, no source snippet) and ``derived``
# (a model-side estimate from traceable inputs) are real backing, but neither is
# external evidence: nobody outside the run said it. Counting them as
# ``supported`` made a headline read "90% supported" while the strict per-claim
# citation audit only confirmed 20%. They now land on their own keys so a
# headline number can never silently absorb them.
SUPPORTED_LEVELS = frozenset({"source_text"})
# Internal backing: real, but not "a source said it". Counted separately and
# also reported as ``unverified`` on the evidence axis.
INTERNAL_BACKING_LEVELS = frozenset({"agent_consensus", "derived"})
UNSUPPORTED_REVIEW = frozenset({"unsupported"})
# Strict per-claim verdict from ``audit_claim_support``: numeric / unit / year
# matching against the cited snippets only. Never a semantic judgement, never
# an LLM vote — so it is reported as its own axis and never merged into
# ``supported``.
CITATION_VERIFIED_STATUS = "supported_by_citation"


def compute_finding_counts(
    findings: list[object], evidence_index: dict[str, object]
) -> dict[str, int]:
    """Classify findings deterministically (never filled by the LLM).

    Two axes, never merged:

    * ``total``                 every finding synthesis produced
    * ``with_valid_evidence``   >=1 ``evidence_id`` resolvable in the evidence set
    * ``supported``             **external** backing: ``support_level ==
                                "source_text"`` and not reviewed unsupported.
                                Agent agreement and model estimates are NOT here
    * ``backed_count``          any backing tier (source text, agent consensus,
                                derived) that was not reviewed unsupported — kept
                                so the historical series stays inspectable
    * ``citation_verified``     the strict per-claim citation audit says
                                ``supported_by_citation`` (numeric / unit / year
                                match against the cited snippets)
    * ``multi_source``          ``independent_source_count`` >= 2
    * ``single_source``         exactly 1 independent source
    * ``agent_consensus``       backed only by agreeing agents (no source)
    * ``derived``               backed only by a model-side derivation
    * ``unverified``            bound evidence that did not reach external
                                backing (also counts the two internal tiers)
    * ``unsupported``           no resolvable evidence at all (dangling refs)

    Invariant: ``with_valid_evidence == supported + unverified``.
    """
    total = 0
    with_valid_evidence = 0
    supported = 0
    backed_count = 0
    citation_verified = 0
    multi_source = 0
    single_source = 0
    agent_consensus = 0
    derived = 0
    unverified = 0
    unsupported = 0
    for finding in findings or []:
        total += 1
        refs = [
            str(item)
            for item in (getattr(finding, "evidence_ids", []) or [])
            if str(item) in evidence_index
        ]
        if not refs:
            unsupported += 1
            continue
        with_valid_evidence += 1
        level = str(getattr(finding, "support_level", "") or "").strip().lower()
        review = str(getattr(finding, "review_status", "") or "").strip().lower()
        independent = getattr(finding, "independent_source_count", None)
        try:
            independent = int(independent) if independent is not None else 0
        except (TypeError, ValueError):
            independent = 0
        if independent >= 2:
            multi_source += 1
        elif independent == 1:
            single_source += 1
        # An explicit "unsupported" review outranks the support tier: a claim a
        # reviewer rejected is never counted as supported.
        if review in UNSUPPORTED_REVIEW:
            unverified += 1
            continue
        if level in SUPPORTED_LEVELS:
            supported += 1
            backed_count += 1
        elif level in INTERNAL_BACKING_LEVELS:
            # AT-AUDIT-004: agreement between agents and model-side estimates are
            # real backing, but they are not a source. They are counted on their
            # own keys and stay out of the ``supported`` headline.
            if level == "agent_consensus":
                agent_consensus += 1
            else:
                derived += 1
            backed_count += 1
            unverified += 1
        else:
            unverified += 1
        audit = getattr(finding, "support_audit", None) or {}
        if str(audit.get("status", "") or "").strip().lower() == CITATION_VERIFIED_STATUS:
            citation_verified += 1
    return {
        "total": total,
        "with_valid_evidence": with_valid_evidence,
        "supported": supported,
        "backed_count": backed_count,
        "citation_verified": citation_verified,
        "multi_source": multi_source,
        "single_source": single_source,
        "agent_consensus": agent_consensus,
        "derived": derived,
        "unverified": unverified,
        "unsupported": unsupported,
    }


# --- D3: executive summary fallback ------------------------------------------
# A statistical sentence ("cross-agent synthesis over N artifacts") is NOT an
# executive summary. When the model returns nothing, either compose a summary
# from the validated findings / insights / recommendations that synthesis already
# produced (quoting them, never inventing), or state plainly that it is
# unavailable. The status is always disclosed.
SUMMARY_STATUS_MODEL = "model"
SUMMARY_STATUS_DERIVED = "derived_from_findings"
SUMMARY_STATUS_UNAVAILABLE = "unavailable"


def derive_executive_summary(result: object) -> tuple[str, str, str]:
    """Return ``(summary, status, reason)`` for a synthesis result.

    ``status`` is one of ``model`` / ``derived_from_findings`` / ``unavailable``.
    Only already-produced, validated statements are reused - no new facts are
    introduced and no placeholder prose is emitted to inflate a counter.
    """
    existing = str(getattr(result, "summary", "") or "").strip()
    if existing:
        return existing, SUMMARY_STATUS_MODEL, ""
    findings = [
        str(getattr(item, "statement", "") or "").strip()
        for item in (getattr(result, "key_findings", []) or [])
    ]
    insights = [
        str(getattr(item, "statement", "") or "").strip()
        for item in (getattr(result, "cross_agent_insights", []) or [])
    ]
    recommendations = [
        str(getattr(item, "statement", "") or "").strip()
        for item in (getattr(result, "recommendations", []) or [])
    ]
    findings = [item for item in findings if item]
    insights = [item for item in insights if item]
    recommendations = [item for item in recommendations if item]
    if not (findings or insights or recommendations):
        return (
            "",
            SUMMARY_STATUS_UNAVAILABLE,
            "synthesis produced no summary and no findings/insights/recommendations "
            "to derive one from; the executive summary is reported as unavailable "
            "rather than filled with placeholder text",
        )
    lines: list[str] = []
    if findings:
        lines.append("主要发现：" + "；".join(findings[:3]))
    if insights:
        lines.append("关键洞察：" + "；".join(insights[:2]))
    if recommendations:
        lines.append("建议：" + "；".join(recommendations[:2]))
    return (
        "\n".join(lines),
        SUMMARY_STATUS_DERIVED,
        "model returned no summary; composed from validated findings/insights/"
        "recommendations produced by synthesis (no new facts added)",
    )


def _complete_stage(
    active: object, prompt: str, *, max_attempts: int
) -> tuple[SynthesisResult | None, int, SynthesisError | None]:
    """One structured call with bounded, category-aware retry.

    Every retry is a real provider call and therefore consumes the caller's LLM
    budget; non-retryable transport/auth/budget errors are never retried.
    """
    attempts = max(1, int(max_attempts))
    retries = 0
    last_error: SynthesisError | None = None
    last_category = ""
    for attempt in range(1, attempts + 1):
        request = prompt + _attempt_hint(attempt, last_category)
        try:
            candidate = active.structured_completion(request, SynthesisResult)
            if not isinstance(candidate, SynthesisResult):
                raise SynthesisError("provider returned a non-SynthesisResult object")
            return candidate, retries, None
        except SynthesisError as exc:
            last_error, last_category = exc, ""
        except (ValidationError, ValueError, TypeError) as exc:
            last_error = SynthesisError(f"Invalid structured response: {exc}")
            last_category = "format"
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", False))
            last_category = str(getattr(exc, "parse_category", "") or "")
            last_error = SynthesisError(f"Structured output parsing failed: {exc}")
            if not retryable:
                last_error.retry_count = retries
                return None, retries, last_error
        if attempt < attempts:
            retries += 1
    if last_error is not None:
        last_error.retry_count = retries
    return None, retries, last_error


def _merge_stage(target: SynthesisResult, source: SynthesisResult, fields: tuple[str, ...]) -> None:
    """Deterministic field-wise merge: only the stage's own categories are copied."""
    for field in fields:
        merged = list(getattr(target, field) or [])
        merged.extend(getattr(source, field) or [])
        setattr(target, field, merged)
    if not target.summary and source.summary:
        target.summary = source.summary


def _has_any_category(result: SynthesisResult) -> bool:
    fields = _STAGE_FIELDS["facts"] + _STAGE_FIELDS["implications"]
    return any(getattr(result, field) for field in fields)


def run_synthesis(
    task: str,
    artifacts: list[AgentArtifact],
    evidence: list[EvidenceRecord],
    sources: list[SourceRecord],
    provider: LLMProvider | None = None,
    max_attempts: int = SYNTHESIS_RETRY_ATTEMPTS,
    staged: bool = True,
) -> SynthesisResult:
    """LLM proposes (per stage) → Schema constrains → Code validates and merges.

    Staged mode splits the schema into two independently validated stages so a
    single response never has to carry every category:
      * ``facts``        - findings / contradictions / uncertainties
      * ``implications`` - insights / trade-offs / recommendations
    The final merge, de-duplication and reference check are pure code.
    """
    active = provider or MockLLMProvider()
    # The prompt gets a bounded, deterministic subset; the bundle keeps everything.
    # v0.6.6: the selection is audited (per-record reason + coverage before/after)
    # and the same list is reused for every stage, so one record can never be
    # counted twice as "independent" evidence.
    selection = select_evidence(evidence)
    prompt_evidence = selection.chosen

    if not staged:
        prompt = build_synthesis_prompt(task, artifacts, prompt_evidence, sources)
        proposed, retries, error = _complete_stage(active, prompt, max_attempts=max_attempts)
        if error is not None:
            raise error
        assert proposed is not None
        if not evidence:
            proposed.uncertainties.append(_no_evidence_uncertainty())
        issues: list[str] = []
        cleaned = validate_synthesis(proposed, evidence, issues)
        cleaned.retry_count = retries
        cleaned.validation_errors = issues
        cleaned.evidence_selection = selection.audit
        return cleaned

    merged = SynthesisResult()
    stage_audit: list[dict] = []
    retry_total = 0
    failure: SynthesisError | None = None

    for stage in _STAGE_ORDER:
        fields = _STAGE_FIELDS[stage]
        prompt = build_synthesis_prompt(
            task,
            artifacts,
            prompt_evidence,
            sources,
            stage=stage,
            stage_fields=fields,
            prior_findings=list(merged.key_findings),
        )
        proposed, retries, error = _complete_stage(active, prompt, max_attempts=max_attempts)
        retry_total += retries
        stage_audit.append(
            {
                "stage": stage,
                "fields": list(fields),
                "ok": error is None,
                "retries": retries,
                "error": (str(error)[:200] if error else ""),
                "prompt_chars": len(prompt),
                "evidence_sent": len(prompt_evidence),
            }
        )
        if error is not None:
            failure = error
            break
        if proposed is not None:
            _merge_stage(merged, proposed, fields)

    if failure is not None:
        # Keep earlier stages: a late failure degrades to validated PARTIAL
        # output (never presented as a complete synthesis, never fabricated).
        partial: SynthesisResult | None = None
        if _has_any_category(merged):
            issues = []
            candidate = validate_synthesis(merged, evidence, issues)
            if _has_any_category(candidate):
                candidate.retry_count = retry_total
                candidate.validation_errors = issues
                candidate.stage_audit = stage_audit
                candidate.evidence_selection = selection.audit
                partial = candidate
        failure.retry_count = retry_total
        failure.stage_audit = stage_audit
        failure.partial_result = partial
        raise failure

    if not evidence:
        merged.uncertainties.append(_no_evidence_uncertainty())
    issues = []
    cleaned = validate_synthesis(merged, evidence, issues)
    cleaned.retry_count = retry_total
    cleaned.validation_errors = issues
    cleaned.stage_audit = stage_audit
    cleaned.evidence_selection = selection.audit
    return cleaned


def _no_evidence_uncertainty() -> Uncertainty:
    return Uncertainty(
        uncertainty_id="unc_empty_evidence",
        statement="No verified evidence records were collected from agents.",
        kind="insufficient_evidence",
    )


def dump_synthesis_debug(result: SynthesisResult) -> str:
    """Developer-facing JSON dump (not user-facing chain-of-thought)."""
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
