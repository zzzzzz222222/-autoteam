"""Deterministic, value-based evidence selection for the synthesis prompt (v0.6.6).

Phase 6.5 (A2) found that the prompt received only the first N evidence records
in ``(producer_agent, evidence_id)`` order, so a record carrying the *only* copy
of a key number (815.1亿元 / 70.9%; the WorkMate benchmarks) was trimmed away
while unrelated records from other agents were still sent.

Selection is now driven by auditable *features* instead of an agent quota, in the
priority order required by the repair brief:

1. evidence bound to a **retrieved snippet** (source-level support),
2. evidence carrying a **unique key number** or the **only record of a source**,
3. **counter / risk evidence** (negative or limiting signals),
4. **independent-source** and **agent** coverage guarantees,
5. everything else, by score.

The stored records are never modified — selection only decides what the prompt
sees. Every selected/dropped decision is recorded with its reason, together with
the before/after coverage of agents, sources, numeric evidence and risk evidence,
so a trimmed prompt can never be reported as complete coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.synthesis.claim_support import extract_numbers
from app.synthesis.models import EvidenceRecord

# Total prompt budget stays configurable/compatible; the per-agent value is now a
# *cap* applied after value ranking (it used to be the primary allocation rule).
MAX_EVIDENCE_PER_AGENT = 6
MAX_EVIDENCE_TOTAL = 30
MIN_EVIDENCE_PER_AGENT = 1

# Counter-evidence / risk wording. Heuristic by nature: it only affects ranking,
# never a factual claim, and the reason string is written into the audit.
_RISK_RE = re.compile(
    r"(风险|挑战|失败|失败率|下滑|下降|负增长|停滞|不足|缺口|质疑|争议|然而|但是|"
    r"相反|亏损|延迟|超预算|未达|不及预期|顾虑|障碍|瓶颈|"
    r"risk|decline|fail|however|challenge)",
    re.IGNORECASE,
)

# Feature weights (documented so the ranking is explainable, not magic).
W_BOUND = 3
W_UNIQUE_NUMBER = 2
W_SOLE_SOURCE = 2
W_WEB_SOURCE = 1
W_RISK = 1
MAX_UNIQUE_NUMBER_BONUS = 4


@dataclass
class EvidenceFeatures:
    bound: bool = False
    numbers: list = field(default_factory=list)
    unique_numbers: list = field(default_factory=list)
    sole_record_for_source: bool = False
    web_source: bool = False
    risk: bool = False
    score: int = 0

    def as_dict(self) -> dict:
        return {
            "bound": self.bound,
            "unique_numbers": list(self.unique_numbers),
            "sole_record_for_source": self.sole_record_for_source,
            "web_source": self.web_source,
            "risk": self.risk,
            "score": self.score,
        }

    def reasons(self) -> list[str]:
        out: list[str] = []
        if self.bound:
            out.append("retrieved snippet bound to a source")
        if self.unique_numbers:
            out.append("carries unique key number(s): " + ", ".join(self.unique_numbers))
        if self.sole_record_for_source:
            out.append("only evidence record for its source")
        if self.web_source:
            out.append("real web source")
        if self.risk:
            out.append("counter / risk evidence")
        return out


def _snippet(record: EvidenceRecord) -> str:
    return (record.evidence or "").strip()


def _is_bound(record: EvidenceRecord) -> bool:
    return bool(record.source_id) and bool(_snippet(record))


def compute_features(evidence: list[EvidenceRecord]) -> dict[str, EvidenceFeatures]:
    """Feature vector per record. Pure function of the record set (order-free)."""
    # How often does each (value, range, unit-kind) key occur across *retrieved
    # snippets*? A key seen once is "unique" and worth keeping for the prompt.
    key_counts: dict[tuple, int] = {}
    per_record_numbers: dict[str, list] = {}
    for record in evidence:
        numbers = extract_numbers(_snippet(record))
        per_record_numbers[record.evidence_id] = numbers
        for number in numbers:
            key_counts[number.key] = key_counts.get(number.key, 0) + 1

    source_counts: dict[str, int] = {}
    for record in evidence:
        if record.source_id:
            source_counts[record.source_id] = source_counts.get(record.source_id, 0) + 1

    features: dict[str, EvidenceFeatures] = {}
    for record in evidence:
        numbers = per_record_numbers[record.evidence_id]
        unique = [number.describe() for number in numbers if key_counts.get(number.key, 0) == 1]
        bound = _is_bound(record)
        feature = EvidenceFeatures(
            bound=bound,
            numbers=numbers,
            unique_numbers=unique[:MAX_UNIQUE_NUMBER_BONUS],
            sole_record_for_source=bool(
                record.source_id and source_counts.get(record.source_id) == 1
            ),
            web_source=(record.source_type or "") == "web",
            risk=bool(_RISK_RE.search(_snippet(record))),
        )
        score = 0
        if feature.bound:
            score += W_BOUND
        score += min(len(feature.unique_numbers), MAX_UNIQUE_NUMBER_BONUS) * W_UNIQUE_NUMBER
        if feature.sole_record_for_source:
            score += W_SOLE_SOURCE
        if feature.web_source:
            score += W_WEB_SOURCE
        if feature.risk:
            score += W_RISK
        feature.score = score
        features[record.evidence_id] = feature
    return features


def _coverage(records: list[EvidenceRecord], features: dict[str, EvidenceFeatures]) -> dict:
    return {
        "records": len(records),
        "agents": len({r.producer_agent for r in records if r.producer_agent}),
        "sources": len({r.source_id for r in records if r.source_id}),
        "bound": sum(1 for r in records if _is_bound(r)),
        "numeric": sum(1 for r in records if features[r.evidence_id].numbers),
        "unique_numeric": sum(1 for r in records if features[r.evidence_id].unique_numbers),
        "risk": sum(1 for r in records if features[r.evidence_id].risk),
    }


@dataclass
class EvidenceSelection:
    """Chosen records plus the full selection audit (never drops silently)."""

    chosen: list[EvidenceRecord] = field(default_factory=list)
    audit: dict = field(default_factory=dict)

    @property
    def chosen_ids(self) -> list[str]:
        return [record.evidence_id for record in self.chosen]


def select_evidence(
    evidence: list[EvidenceRecord],
    *,
    total: int = MAX_EVIDENCE_TOTAL,
    per_agent: int = MAX_EVIDENCE_PER_AGENT,
    min_per_agent: int = MIN_EVIDENCE_PER_AGENT,
) -> EvidenceSelection:
    """Rank by auditable value, guarantee coverage, then fill to ``total``."""
    if not evidence:
        empty = _coverage([], {})
        return EvidenceSelection(
            chosen=[],
            audit={
                "policy_version": "v0.6.6",
                "total": total,
                "per_agent_cap": per_agent,
                "before": 0,
                "selected_count": 0,
                "distinct_evidence_ids": 0,
                "duplicate_ids_removed": 0,
                "selected_ids": [],
                "coverage_before": empty,
                "coverage_after": empty,
                "coverage_gaps": [],
                "coverage_gap_note": "",
                "dropped": [],
                "dropped_count": 0,
            },
        )

    features = compute_features(evidence)
    # Deterministic order that never depends on the caller's input order.
    ranked = sorted(
        evidence, key=lambda item: (-features[item.evidence_id].score, item.evidence_id)
    )

    selected: list[EvidenceRecord] = []
    selected_ids: set[str] = set()
    reasons: dict[str, list[str]] = {}

    def take(record: EvidenceRecord, reason: str) -> bool:
        if record.evidence_id in selected_ids or len(selected) >= total:
            return False
        selected.append(record)
        selected_ids.add(record.evidence_id)
        reasons.setdefault(record.evidence_id, []).append(reason)
        return True

    # (a) independent-source coverage: the best record of every bound source.
    for source_id in sorted({r.source_id for r in evidence if r.source_id}):
        if len(selected) >= total:
            break
        best = next(item for item in ranked if item.source_id == source_id)
        take(best, f"coverage: highest-value record for source {source_id}")

    # (b) key-number protection: keep a record carrying a unique number while no
    #     other selected record already covers that same number.
    claimed_numbers: set[tuple] = set()
    for record in selected:
        claimed_numbers.update(n.key for n in features[record.evidence_id].numbers)
    for record in ranked:
        if len(selected) >= total:
            break
        if not features[record.evidence_id].unique_numbers:
            continue
        fresh = [n for n in features[record.evidence_id].numbers if n.key not in claimed_numbers]
        if fresh and take(record, "protected: unique key number(s)"):
            claimed_numbers.update(n.key for n in fresh)

    # (c) agent coverage: every producing agent keeps at least one voice.
    for agent in sorted({r.producer_agent for r in evidence if r.producer_agent}):
        if len(selected) >= total:
            break
        if sum(1 for r in selected if r.producer_agent == agent) >= min_per_agent:
            continue
        best = next(item for item in ranked if item.producer_agent == agent)
        take(best, "coverage: agent keeps a voice")

    # (d) fill the rest by score, honouring the per-agent cap.
    per_agent_count: dict[str, int] = {}
    for record in selected:
        per_agent_count[record.producer_agent] = (
            per_agent_count.get(record.producer_agent, 0) + 1
        )
    for record in ranked:
        if len(selected) >= total:
            break
        if record.evidence_id in selected_ids:
            continue
        agent = record.producer_agent
        if per_agent_count.get(agent, 0) >= per_agent:
            continue
        if take(record, "selected by value score"):
            per_agent_count[agent] = per_agent_count.get(agent, 0) + 1

    # --- audit -------------------------------------------------------------
    dropped: list[dict] = []
    coverage_gaps: list[dict] = []
    for record in ranked:
        feature = features[record.evidence_id]
        row = {
            "evidence_id": record.evidence_id,
            "producer_agent": record.producer_agent,
            "source_id": record.source_id,
            "selected": record.evidence_id in selected_ids,
            "score": feature.score,
            "features": feature.as_dict(),
            "reasons": reasons.get(record.evidence_id, []),
        }
        if not row["selected"]:
            over_cap = per_agent_count.get(record.producer_agent, 0) >= per_agent
            row["reason"] = (
                f"per-agent cap ({per_agent}) reached for {record.producer_agent}"
                if over_cap
                else f"prompt budget ({total}) exhausted"
            )
            dropped.append(row)
            if feature.unique_numbers or feature.sole_record_for_source or feature.risk:
                coverage_gaps.append(
                    {
                        "evidence_id": record.evidence_id,
                        "source_id": record.source_id,
                        "producer_agent": record.producer_agent,
                        "unique_numbers": list(feature.unique_numbers),
                        "sole_record_for_source": feature.sole_record_for_source,
                        "risk": feature.risk,
                        "reason": row["reason"],
                    }
                )
        else:
            row["reason"] = "; ".join(row["reasons"]) or "selected"

    chosen = sorted(
        selected, key=lambda item: (-features[item.evidence_id].score, item.evidence_id)
    )
    chosen_ids = [record.evidence_id for record in chosen]
    audit = {
        "policy_version": "v0.6.6",
        "criteria": [
            "bound retrieved snippet (source-level support)",
            "unique key number",
            "sole record for its source",
            "real web source",
            "counter / risk evidence",
            "agent + independent-source coverage guarantees",
        ],
        "total": total,
        "per_agent_cap": per_agent,
        "before": len(evidence),
        "selected_count": len(chosen),
        "distinct_evidence_ids": len(set(chosen_ids)),
        "duplicate_ids_removed": len(chosen_ids) - len(set(chosen_ids)),
        "selected_ids": chosen_ids,
        "coverage_before": _coverage(evidence, features),
        "coverage_after": _coverage(chosen, features),
        "coverage_gaps": coverage_gaps,
        "coverage_gap_note": (
            ""
            if not coverage_gaps
            else "the prompt budget trimmed evidence that carries unique numbers, "
            "sole-source coverage or risk signals - coverage is NOT complete"
        ),
        "dropped": dropped,
        "dropped_count": len(dropped),
    }
    return EvidenceSelection(chosen=chosen, audit=audit)


def select_prompt_evidence(
    evidence: list[EvidenceRecord],
    *,
    total: int = MAX_EVIDENCE_TOTAL,
    per_agent: int = MAX_EVIDENCE_PER_AGENT,
) -> list[EvidenceRecord]:
    """Backward-compatible wrapper: the chosen records only."""
    return select_evidence(evidence, total=total, per_agent=per_agent).chosen
