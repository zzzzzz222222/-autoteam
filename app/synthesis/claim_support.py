"""Deterministic claim ↔ evidence support auditing (v0.6.6).

Phase 6.5 (A1) found that a finding could cite *real* evidence ids whose
snippet did not contain the numbers the finding asserted. Reference validation
only ever checked that an id existed — never that the cited text supported the
statement. This module adds the missing code-level check.

Rules (deliberately conservative — under-support is safe, over-support is not):

* a number only "matches" when the **value** and the **unit kind** agree, and
  when the year sets of the statement clause and the evidence clause are
  compatible;
* source-level support can only come from a **retrieved snippet**
  (``EvidenceRecord.evidence``) that is bound to a source id — an agent's own
  claim text is never promoted to "the source says this";
* nothing is written back to ``Finding.evidence_ids``: a record that carries a
  missing number but was not cited is reported as an **uncited candidate**,
  never silently bound to the claim.

Nothing here calls an LLM and nothing here scores prose quality; every value is
derived from text with a fixed rule that is explainable in the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.synthesis.models import SUPPORT_LEVELS, EvidenceRecord  # noqa: F401 (re-export)

# --- unit vocabulary --------------------------------------------------------
# "成" (Chinese fraction) and "%" are kept as *different* kinds on purpose: a
# conservative matcher must never equate "4成" with "40%" on its own.
_PERCENT_UNITS = {"%", "％", "个百分点"}
_CURRENCY_UNITS = {"亿元", "万元", "亿", "万", "元", "美元"}
_COUNT_UNITS = {"家", "个", "人"}
_DURATION_UNITS = {"个月", "天", "小时", "分钟", "秒", "月"}
_RATIO_UNITS = {"倍"}
_FRACTION_UNITS = {"成"}

# Scope markers are recorded for human review, never used to *grant* support.
_SCOPE_MARKERS = (
    "同比", "环比", "CAGR", "年均", "复合增长", "占比", "渗透率", "覆盖率",
    "增长率", "增速", "规模", "预算", "投资", "回报率", "ROI", "无回报",
    "试点", "满意度", "失败率", "份额", "市占", "排名", "预计", "预测",
    "目标", "上限", "下限", "平均", "中位",
)

_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
# Number, optional adjacent range (shared unit), optional unit.
_TOKEN_RE = re.compile(
    rf"(?P<value>{_NUMBER})"
    rf"(?:\s*(?:[-–—~～]|至|到)\s*(?P<hi>{_NUMBER}))?"
    rf"\s*(?P<unit>%|％|个百分点|亿元|万元|亿|万|美元|元|倍|成|家|个|人|个月|年|月|天|小时|分钟|秒)?"
)
_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})\s*年")
_CLAUSE_SPLIT_RE = re.compile(r"[。．；;!！?？\n·]")

# A year may sit this far from its number inside the same clause and still be
# read as "the same statistic" (snippets often write "2030年...将达815.1亿元").
_MAX_SCOPE_WINDOW = 12


def _clean_number(raw: str) -> float:
    return float((raw or "").replace(",", "").strip() or 0.0)


def _kind_for(value_raw: str, unit: str) -> str:
    unit = unit or ""
    if unit in _PERCENT_UNITS:
        return "percent"
    if unit in _CURRENCY_UNITS:
        return "currency"
    if unit in _COUNT_UNITS:
        return "count"
    if unit in _DURATION_UNITS:
        return "duration"
    if unit in _RATIO_UNITS:
        return "ratio"
    if unit in _FRACTION_UNITS:
        return "fraction"
    if unit == "年" and re.fullmatch(r"(1[89]\d{2}|20\d{2})", value_raw.replace(",", "")):
        return "year"
    return "plain"


@dataclass(frozen=True)
class NumericAssertion:
    """One number found in text, with the context needed to compare it."""

    raw: str
    value: float
    kind: str
    hi: float | None = None
    years: frozenset[str] = frozenset()
    scope: frozenset[str] = frozenset()

    @property
    def key(self) -> tuple:
        return (self.value, self.hi, self.kind)

    def describe(self) -> str:
        return f"{self.raw}[{self.kind}]"


def _split_clauses(text: str) -> list[tuple[str, frozenset[str]]]:
    """Split into (clause, years-in-clause) so a year binds to its own statistic."""
    out: list[tuple[str, frozenset[str]]] = []
    for clause in _CLAUSE_SPLIT_RE.split(text or ""):
        if not clause.strip():
            continue
        years = frozenset(_YEAR_RE.findall(clause))
        out.append((clause, years))
    return out


def _scope_near(clause: str, start: int, end: int) -> frozenset[str]:
    window = clause[max(0, start - _MAX_SCOPE_WINDOW): end + _MAX_SCOPE_WINDOW]
    return frozenset(marker for marker in _SCOPE_MARKERS if marker in window)


def extract_numbers(text: str) -> list[NumericAssertion]:
    """All numeric assertions in ``text``, de-duplicated by (value, range, kind)."""
    found: dict[tuple, NumericAssertion] = {}
    for clause, years in _split_clauses(text):
        for match in _TOKEN_RE.finditer(clause):
            raw_value = match.group("value")
            unit = match.group("unit") or ""
            value = _clean_number(raw_value)
            hi_raw = match.group("hi")
            # A bare number followed by a range dash belongs to the range token.
            kind = _kind_for(raw_value, unit)
            if kind == "plain" and hi_raw is not None:
                kind = _kind_for(hi_raw, unit)
            assertion = NumericAssertion(
                raw=(raw_value + ("-" + hi_raw if hi_raw else "") + unit).strip(),
                value=value,
                hi=_clean_number(hi_raw) if hi_raw else None,
                kind=kind,
                years=years,
                scope=_scope_near(clause, match.start(), match.end()),
            )
            found.setdefault(assertion.key, assertion)
    return list(found.values())


def _years_compatible(left: NumericAssertion, right: NumericAssertion) -> bool:
    """A statement year must be confirmed by the evidence when both sides have one."""
    if not left.years or not right.years:
        return True
    return bool(left.years & right.years)


def _scope_check(left: NumericAssertion, right: NumericAssertion) -> tuple[str, str]:
    """Statistical-scope comparison: recorded, never silently ignored.

    Scope wording is free-form, so this is a *review flag*, not a hard gate: a
    conflict downgrades the witness confidence to ``medium`` and is rendered in
    the report so a human confirms the statistic's scope. Value, unit kind and
    year remain hard gates (``match_assertion``).
    """
    if left.scope and right.scope and not (left.scope & right.scope):
        return (
            "scope_conflict",
            f"scope differs (claim={sorted(left.scope)} snippet={sorted(right.scope)})",
        )
    if left.scope and not right.scope:
        return "snippet_has_no_scope", "snippet carries no scope marker for the number"
    return "confirmed", ""


def match_assertion(assertion: NumericAssertion, text: str) -> dict | None:
    """Return a match record when ``text`` states the same statistic, else None."""
    for candidate in extract_numbers(text):
        if candidate.kind != assertion.kind:
            continue
        if abs(candidate.value - assertion.value) > 1e-9:
            continue
        if not _years_compatible(assertion, candidate):
            continue
        scope_check, scope_note = _scope_check(assertion, candidate)
        return {
            "matched_raw": candidate.raw,
            "value": assertion.value,
            "kind": assertion.kind,
            "years": sorted(assertion.years & candidate.years)
            or sorted(assertion.years)
            or sorted(candidate.years),
            "scope_check": scope_check,
            "scope_note": scope_note,
        }
    return None


def _snippet_of(record: EvidenceRecord) -> str:
    return (record.evidence or "").strip()


def is_source_backed(record: EvidenceRecord) -> bool:
    """A cited record can support a *source* claim only with a bound snippet."""
    return bool(record.source_id) and bool(_snippet_of(record))


def _excerpt(text: str, limit: int = 160) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def audit_claim_support(
    statement: str,
    cited_ids: list[str],
    by_id: dict[str, EvidenceRecord],
    *,
    pool: list[EvidenceRecord] | None = None,
) -> dict:
    """Traceable per-claim support audit. Read-only: never edits ``cited_ids``."""
    assertions = extract_numbers(statement)
    checks: list[dict] = []
    witnesses: dict[tuple, dict] = {}
    unbound_cited: list[dict] = []

    for ref in cited_ids:
        record = by_id.get(ref)
        if record is None:
            continue
        snippet = _snippet_of(record)
        backed = is_source_backed(record)
        row = {
            "evidence_id": record.evidence_id,
            "source_id": record.source_id or "",
            "producer_agent": record.producer_agent or "",
            "source_backed": backed,
            "review_status": record.review_status or "not_checked",
            "snippet": _excerpt(snippet),
            "numbers_found": [],
            "numbers_missing": [],
            "scope_warnings": [],
            "match_reason": "",
            "check_status": "no_numbers" if not assertions else "",
        }
        if not backed:
            row["match_reason"] = (
                "no retrieved snippet bound to a source — an agent statement "
                "cannot support a source-level claim"
            )
        for assertion in assertions:
            hit = match_assertion(assertion, snippet) if backed else None
            if hit:
                row["numbers_found"].append(assertion.describe())
                if hit["scope_note"]:
                    row["scope_warnings"].append(f"{assertion.describe()}: {hit['scope_note']}")
                witnesses.setdefault(
                    assertion.key,
                    {
                        "number": assertion.describe(),
                        "value": assertion.value,
                        "kind": assertion.kind,
                        "evidence_id": record.evidence_id,
                        "source_id": record.source_id or "",
                        # v0.6.9 (F13): carry the source type so the rendered
                        # citation audit cannot present a stub as a web source.
                        "source_type": record.source_type or "",
                        "match_reason": "value+unit+year match in retrieved snippet",
                        "scope_check": hit["scope_check"],
                        "scope_note": hit["scope_note"],
                        "confidence": "high" if hit["scope_check"] == "confirmed" else "medium",
                    },
                )
            else:
                row["numbers_missing"].append(assertion.describe())
        if not backed:
            row["check_status"] = "unbound_citation"
        elif assertions and len(row["numbers_found"]) == len(assertions):
            row["check_status"] = "all_matched"
        elif row["numbers_found"]:
            row["check_status"] = "partial"
        else:
            row["check_status"] = "none"
        if not backed:
            unbound_cited.append(
                {"evidence_id": record.evidence_id, "producer_agent": record.producer_agent}
            )
        checks.append(row)

    missing = [a for a in assertions if a.key not in witnesses]

    uncited: list[dict] = []
    if missing and pool:
        cited = set(cited_ids)
        for record in pool:
            if record.evidence_id in cited or not is_source_backed(record):
                continue
            snippet = _snippet_of(record)
            hits, conflicts, unflagged = [], [], []
            for a in missing:
                hit = match_assertion(a, snippet)
                if not hit:
                    continue
                hits.append(a.describe())
                if hit["scope_check"] == "scope_conflict":
                    conflicts.append(f"{a.describe()}: {hit['scope_note']}")
                elif hit["scope_check"] == "snippet_has_no_scope":
                    unflagged.append(f"{a.describe()}: snippet carries no scope marker")
            if hits:
                uncited.append(
                    {
                        "evidence_id": record.evidence_id,
                        "source_id": record.source_id or "",
                        "producer_agent": record.producer_agent or "",
                        "numbers": hits,
                        "scope_conflicts": conflicts,
                        "scope_unflagged": unflagged,
                        "snippet": _excerpt(snippet),
                        "note": "carries the missing number but was NOT cited by the model",
                    }
                )

    if not assertions:
        status = "no_numeric_claim"
    elif not witnesses:
        status = "unsupported"
    elif missing:
        status = "partially_supported"
    else:
        status = "supported_by_citation"

    return {
        "claim_text": statement,
        "assertions": [
            {"number": a.describe(), "value": a.value, "kind": a.kind, "years": sorted(a.years),
             "scope": sorted(a.scope)}
            for a in assertions
        ],
        "checks": checks,
        "witnesses": [witnesses[a.key] for a in assertions if a.key in witnesses],
        "numbers_supported": [a.describe() for a in assertions if a.key in witnesses],
        "numbers_missing": [a.describe() for a in missing],
        "uncited_candidates": uncited,
        "unbound_citations": unbound_cited,
        "scope_flags": sorted(
            {w["scope_note"] for w in witnesses.values() if w["scope_note"]}
        ),
        "status": status,
        "numeric_check": {
            "no_numeric_claim": "no_numbers",
            "supported_by_citation": "all_matched",
            "partially_supported": "partial",
            "unsupported": "none",
        }[status],
    }


def derive_review_status(
    evidence_ids: list[str],
    by_id: dict[str, EvidenceRecord],
    audit: dict,
) -> str:
    """Finding-level review status. ``verified`` is never produced here."""
    if not evidence_ids:
        return "unsupported"
    bound = [by_id[ref] for ref in evidence_ids if ref in by_id]
    if not bound:
        return "unsupported"
    if any((item.review_status or "") == "source_unavailable" for item in bound):
        return "source_unavailable"
    if audit.get("status") == "unsupported":
        return "unsupported"
    if audit.get("status") == "partially_supported":
        return "partially_supported"
    return "not_checked"


# ---------------------------------------------------------------------------
# Support profile: multi-agent agreement vs independent-source agreement
# ---------------------------------------------------------------------------

# ``SUPPORT_LEVELS`` lives in models.py (imported above) so the schema and this
# module can never drift apart.


@dataclass
class SupportProfile:
    evidence_count: int = 0
    agent_support_count: int = 0
    independent_source_count: int = 0
    support_kind: str = "unsupported"
    support_level: str = "unknown"
    agents: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    source_backed_count: int = 0


def support_profile(
    evidence_ids: list[str],
    by_id: dict[str, EvidenceRecord],
    *,
    claim_type: str = "",
) -> SupportProfile:
    """Split "several agents agree" from "independent sources agree" (A4-A7).

    ``support_kind`` (backward-compatible field) is re-derived here so that
    ``multi_source`` can only ever mean **two or more distinct source ids**:

    * ``multi_source``       - >= 2 distinct independent sources
    * ``single_source``      - exactly 1 independent source
    * ``multi_agent``        - no source at all, >= 2 distinct agents agree
    * ``agent_restatement``  - no source, one agent only
    * ``unsupported``        - nothing resolvable
    """
    resolved = [by_id[ref] for ref in evidence_ids if ref in by_id]
    agents = sorted({item.producer_agent for item in resolved if item.producer_agent})
    sources = sorted({item.source_id for item in resolved if item.source_id})
    backed = [item for item in resolved if is_source_backed(item)]

    if not resolved:
        kind = "unsupported"
    elif len(sources) >= 2:
        kind = "multi_source"
    elif len(sources) == 1:
        kind = "single_source"
    elif len(agents) >= 2:
        kind = "multi_agent"
    else:
        kind = "agent_restatement"

    # Precedence is fixed and documented so the report never implies more than
    # the strongest support actually available.
    if claim_type == "planning_assumption":
        level = "planning_assumption"
    elif claim_type == "derived_estimate":
        level = "derived"
    elif sources and backed:
        level = "source_text"
    elif len(agents) >= 2:
        level = "agent_consensus"
    elif resolved:
        level = "agent_restatement"
    else:
        level = "unknown"

    return SupportProfile(
        evidence_count=len(resolved),
        agent_support_count=len(agents),
        independent_source_count=len(sources),
        support_kind=kind,
        support_level=level,
        agents=agents,
        source_ids=sources,
        source_backed_count=len(backed),
    )
