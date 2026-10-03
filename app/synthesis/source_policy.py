"""Declared-intent source policy + structured evidence gaps (v0.6.6).

Phase 6.5 (A3) found that ``competitor_analyst`` produced competitor names,
positioning and pricing judgements with **zero** source records, yet its output
was still presented as source-backed findings.

This module turns "did this deliverable have to be sourced?" into a *declarative*
check:

* the requirement comes from the subtask's declared ``expected_output``
  (``app/runtime/agent_factory.py`` -> ``AgentArtifact.metadata["expected_output"]``),
  never from a role name or an agent id;
* a gap is emitted **whenever a claim had to be downgraded** from ``source_fact``
  to ``unverified_claim`` because no retrieved snippet could back it — that path
  is intent-free and works for legacy artifacts too;
* the output is a structured gap (counts + reasons), never a fabricated source.

Nothing here calls a search API: it only inspects records that already exist.
"""

from __future__ import annotations

from app.runtime.artifacts import AgentArtifact
from app.synthesis.models import EvidenceRecord

# Declared subtask intent -> what a reader would expect to be sourced.
# Keyed on the *task declaration*, never on a role name.
#
# This map MUST stay aligned with ``CAPABILITY_TOOLS`` in
# ``app/runtime/tool_selector.py``: every intent here is produced by a capability
# that P6.12/6.13 granted ``web_search`` (the means to actually source it), so an
# artifact of that intent with zero bound evidence is a real, reportable gap.
# The two entries below (requirements_document / strategy_document) were the
# missing ones: REQUIREMENT_ANALYSIS and STRATEGY_PLANNING both received
# ``web_search`` in P6.12, yet their artifacts escaped this detector entirely —
# exactly the "requirement_analyst produced only unverified_claims" finding from
# P6.14. Adding them closes that loop without forcing retrieval (the policy only
# *detects* a missing source, it never invents one).
SOURCE_REQUIRED_INTENTS: dict[str, str] = {
    "competitor_landscape": (
        "competitor names, positioning, pricing and market judgements"
    ),
    "market_overview": "market size and growth statistics",
    "customer_insights": "customer research findings",
    "technology_trends": "technology capability and trend claims",
    "requirements_document": (
        "market-grounded requirements: user needs, use cases and constraints "
        "must be evidenced, not asserted (P6.12 granted requirement_analysis web_search)"
    ),
    "strategy_document": (
        "strategy options and rationale must be grounded in sources "
        "(P6.12 granted strategy_planning web_search)"
    ),
}


def declared_intent(artifact: AgentArtifact) -> str:
    """The subtask's declared ``expected_output`` (first one, when several)."""
    metadata = artifact.metadata or {}
    intent = str(metadata.get("expected_output") or "").strip()
    if intent:
        return intent
    outputs = metadata.get("expected_outputs")
    if isinstance(outputs, (list, tuple)):
        for item in outputs:
            if str(item).strip():
                return str(item).strip()
    return ""


def declared_intent_reason(artifact: AgentArtifact) -> str:
    return SOURCE_REQUIRED_INTENTS.get(declared_intent(artifact), "")


def source_gaps(
    artifacts: list[AgentArtifact], evidence: list[EvidenceRecord]
) -> list[dict]:
    """Structured evidence gaps per artifact. Deterministic and role-agnostic."""
    by_artifact: dict[str, list[EvidenceRecord]] = {}
    for record in evidence:
        by_artifact.setdefault(record.artifact_id, []).append(record)

    gaps: list[dict] = []
    for artifact in artifacts:
        own = by_artifact.get(artifact.artifact_id, [])
        bound = [item for item in own if item.source_id and (item.evidence or "").strip()]
        # Claims the deterministic filter had to downgrade because no retrieved
        # snippet could back them (see evidence_filter.collect_evidence_records).
        downgraded = [
            item
            for item in own
            if item.claim_type == "unverified_claim"
            and (item.claim or "").strip()
            and not item.source_id
        ]
        intent = declared_intent(artifact)
        reason = SOURCE_REQUIRED_INTENTS.get(intent, "")
        reasons: list[str] = []
        if reason and not bound:
            reasons.append(
                f"declared intent '{intent}' requires sourced {reason}, but no claim "
                f"is bound to a retrieved snippet "
                f"({len(artifact.source_records)} source record(s), "
                f"{len(bound)} bound evidence)"
            )
        if downgraded:
            reasons.append(
                f"{len(downgraded)} claim(s) asserted a source fact with no retrieved "
                "snippet and were downgraded to unverified_claim"
            )
        if not reasons:
            continue
        gaps.append(
            {
                "artifact_id": artifact.artifact_id,
                "producer_agent": artifact.agent_id,
                "role_name": str((artifact.metadata or {}).get("role_name", "")),
                "declared_intent": intent,
                "source_required": bool(reason),
                "source_count": len(artifact.source_records),
                "evidence_count": len(own),
                "bound_evidence_count": len(bound),
                "unverified_claim_count": len(downgraded),
                "unverified_claims": [item.evidence_id for item in downgraded],
                "severity": "high" if reason else "medium",
                "reasons": reasons,
                "policy": "v0.6.6 declared-intent source policy",
            }
        )
    return gaps


def downgrade_unverified_claim(claim_type: str, source_id: str, snippet: str) -> str:
    """A ``source_fact`` with no *retrieved snippet* may not stay a source fact.

    Bound means: a source id **and** the snippet that was actually retrieved.
    A bare source id (or an agent's own summary text) is not source evidence.
    """
    if claim_type == "source_fact" and not (source_id and (snippet or "").strip()):
        return "unverified_claim"
    return claim_type
