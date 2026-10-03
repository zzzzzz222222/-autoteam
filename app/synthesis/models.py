"""v0.6.0 synthesis schemas.

Everything here is Pydantic so the pipeline stays "LLM proposes → Schema
constrains → Code validates". IDs and provenance are filled by deterministic
code (``EvidenceFilter`` / pipeline) — the LLM never invents evidence ids,
source urls, or producer agents.

LLM-facing models are deliberately forgiving on *shape* (missing ids, a bare
string instead of a list) while remaining strict on *meaning* (every citation
must resolve against real evidence, checked in ``validate_synthesis``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

# Allowed data-nature tags (v0.6.0). Empty string means "unclassified" — the
# system never guesses: an unknown or missing tag is simply left unset.
CLAIM_TYPES = (
    "source_fact",          # a source states it directly (not an audit)
    "derived_estimate",     # computed/derived from traceable inputs
    "planning_assumption",  # product/business goal or forecast
    "unverified_claim",     # thin or unverifiable support
)


def normalize_claim_type(value: object) -> str:
    """Coerce to an allowed claim type, or ``""`` when it cannot be trusted."""
    text = "" if value is None else str(value).strip().lower()
    return text if text in CLAIM_TYPES else ""


# Allowed provenance-review statuses (v0.6.1). A source id only means "a link
# exists" — it never means "the source was verified to support this claim".
REVIEW_STATUSES = (
    "verified",             # a reviewer confirmed the source supports the claim
    "partially_supported",  # the source supports part of the claim
    "unsupported",          # no source supports it (or none could be bound)
    "source_unavailable",   # the cited source could not be retrieved
    "not_checked",          # a source is bound but not yet reviewed
)


def normalize_review_status(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    return text if text in REVIEW_STATUSES else "not_checked"


# Allowed support kinds (v0.6.6). ``multi_source`` now means **two or more
# distinct independent sources** — "several agents agree" has its own value so
# the old field can no longer imply unverified cross-source corroboration.
SUPPORT_KINDS = (
    "multi_source",          # >= 2 distinct independent sources
    "single_source",         # exactly 1 independent source
    "multi_agent",           # no source at all, >= 2 distinct agents agree
    "agent_restatement",     # no source, a single upstream agent states it
    "unsupported",           # nothing resolvable
)


def normalize_support_kind(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    return text if text in SUPPORT_KINDS else ""


# Allowed support tiers (v0.6.6): *how* a claim is backed, kept separate from the
# counts so "multi-agent agreement" can never be read as "multi-source".
SUPPORT_LEVELS = (
    "source_text",          # a retrieved source snippet states it
    "agent_consensus",      # several agents state it, no source snippet
    "agent_restatement",    # one upstream agent states it, no source snippet
    "derived",              # analysis derived from traceable inputs
    "planning_assumption",  # product / business plan, not a present fact
    "unknown",
)


def normalize_support_level(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    return text if text in SUPPORT_LEVELS else "unknown"


def _as_str_list(value: object) -> list[str]:
    """Coerce scalar / None / tuple payloads into ``list[str]``."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


# ---------------------------------------------------------------------------
# Evidence (normalised, provenance-complete)
# ---------------------------------------------------------------------------


class EvidenceRecord(BaseModel):
    """One evidence item after deterministic filtering.

    Traceability chain: EvidenceRecord → producer_agent / artifact_id
    → source_id → url. All identity fields are assigned by code.
    """

    evidence_id: str
    claim: str
    evidence: str = ""
    source_id: str = ""
    source_url: str = ""
    source_title: str = ""
    source_type: str = ""  # web | offline_mock | local_file
    producer_agent: str = ""
    artifact_id: str = ""
    relevance: str = ""  # free-text relation kept from the source artifact
    # v0.6.0: data nature. Empty = unclassified (never guessed).
    claim_type: str = ""
    # v0.6.1: ``verified`` is True ONLY when a review says so. A bound source id
    # means ``not_checked``; an unbound claim means ``unsupported``.
    verified: bool = False
    review_status: str = "not_checked"
    match_score: float = 0.0
    match_method: str = ""

    @field_validator("claim_type", mode="before")
    @classmethod
    def _claim_type(cls, value: object) -> str:
        return normalize_claim_type(value)

    @field_validator("review_status", mode="before")
    @classmethod
    def _review_status(cls, value: object) -> str:
        return normalize_review_status(value)

    @model_validator(mode="after")
    def _sync_verified(self) -> "EvidenceRecord":
        # The two flags can never disagree: verified is derived, not stored truth.
        if self.review_status != "verified":
            self.verified = False
        return self


class SourceRecord(BaseModel):
    """Deduplicated source with URL preserved."""

    source_id: str
    title: str = ""
    url: str = ""
    source_type: str = "offline_mock"  # web | offline_mock | local_file
    retrieved_at: str = ""
    # v0.6.9 (F13): stable, order-independent identity.
    identity: str = ""  # e.g. "web:https://a.example/1" or "offline:<artifact>:<n>:<title>"
    alt_titles: list[str] = Field(default_factory=list)  # other titles seen for the same identity
    first_seen_agent: str = ""  # order-dependent, informational only (never used for counting)
    # v0.6.6 (A9/A10): a source is only "web" when a real URL was retrieved.
    # ``access_status`` keeps the observed fetch outcome so a 403/000 is shown as
    # "could not be re-checked" instead of implying the page has no content.
    access_status: str = ""  # "" | ok | http_403 | http_000 | timeout | unavailable
    access_note: str = ""
    producer_agents: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Findings / Insights
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A statement supported by one or more evidence records."""

    model_config = {"extra": "ignore"}

    finding_id: str = ""  # assigned by code when the LLM omits it
    statement: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_agents: list[str] = Field(default_factory=list)
    # v0.6.6: re-derived by code from the cited evidence (see SUPPORT_KINDS).
    support_kind: str = "unsupported"
    notes: str = ""
    # v0.6.0: data nature + how a derived value was computed (optional).
    claim_type: str = ""
    derivation: str = ""
    # v0.6.6 (A4-A7): agent agreement and independent-source agreement are
    # recorded *separately*; ``support_level`` says which tier the claim reaches.
    evidence_count: int = 0
    agent_support_count: int = 0
    independent_source_count: int = 0
    support_level: str = "unknown"
    # v0.6.6 (A1): per-claim citation audit. ``verified`` is never produced by
    # code — a claim whose cited snippets carry every asserted number is still
    # only ``not_checked`` until a reviewer confirms the source says it.
    review_status: str = "not_checked"
    support_audit: dict = Field(default_factory=dict)
    unsupported_parts: list[str] = Field(default_factory=list)

    @field_validator(
        "evidence_ids", "supporting_agents", "unsupported_parts", mode="before"
    )
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_str_list(value)

    @field_validator(
        "finding_id", "statement", "support_kind", "notes", "derivation", mode="before"
    )
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)

    @field_validator("claim_type", mode="before")
    @classmethod
    def _claim_type(cls, value: object) -> str:
        return normalize_claim_type(value)

    @field_validator("support_kind", mode="before")
    @classmethod
    def _support_kind(cls, value: object) -> str:
        return normalize_support_kind(value)

    @field_validator("support_level", mode="before")
    @classmethod
    def _support_level(cls, value: object) -> str:
        return normalize_support_level(value)

    @field_validator("review_status", mode="before")
    @classmethod
    def _review_status(cls, value: object) -> str:
        return normalize_review_status(value)


class Insight(BaseModel):
    """A judgment that emerges from combining multiple facts.

    Not a restatement of evidence — it must combine at least two evidence
    items into a new conclusion. Uncertainty is qualitative, never a fake
    percentage score.
    """

    model_config = {"extra": "ignore"}

    insight_id: str = ""
    statement: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_artifact_ids: list[str] = Field(default_factory=list)
    producer_agents: list[str] = Field(default_factory=list)
    # v0.6.0: deterministically derived from the cited evidence producers;
    # ``producer_agents`` is kept for backward compatibility.
    contributing_agents: list[str] = Field(default_factory=list)
    uncertainty: str = ""  # e.g. "single source", "partial coverage", ""
    claim_type: str = ""
    derivation: str = ""
    # v0.6.6 (A4-A7): same separation as findings.
    evidence_count: int = 0
    agent_support_count: int = 0
    independent_source_count: int = 0
    support_level: str = "unknown"

    @field_validator(
        "supporting_evidence_ids",
        "supporting_artifact_ids",
        "producer_agents",
        "contributing_agents",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_str_list(value)

    @field_validator("support_level", mode="before")
    @classmethod
    def _support_level(cls, value: object) -> str:
        return normalize_support_level(value)

    @field_validator(
        "insight_id", "statement", "uncertainty", "derivation", mode="before"
    )
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)

    @field_validator("claim_type", mode="before")
    @classmethod
    def _claim_type(cls, value: object) -> str:
        return normalize_claim_type(value)


# ---------------------------------------------------------------------------
# Contradiction / Uncertainty
# ---------------------------------------------------------------------------


class Contradiction(BaseModel):
    """Two claims that cannot both be true given available evidence.

    ``status`` is ``resolved`` only when evidence actually settles the
    conflict; otherwise ``unresolved`` — the system must not pick a winner.
    """

    model_config = {"extra": "ignore"}

    contradiction_id: str = ""
    claim_a: str = ""
    claim_b: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    status: str = "unresolved"  # resolved | unresolved
    resolution: str = ""

    @field_validator("evidence_ids", "source_ids", "agents", mode="before")
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_str_list(value)

    @field_validator(
        "contradiction_id",
        "claim_a",
        "claim_b",
        "status",
        "resolution",
        mode="before",
    )
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)


class Uncertainty(BaseModel):
    """Where the record is thin: single-source, missing data, or vague."""

    model_config = {"extra": "ignore"}

    uncertainty_id: str = ""
    statement: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    # insufficient_evidence | single_source | conflicting | vague
    kind: str = "insufficient_evidence"
    note: str = ""

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_str_list(value)

    @field_validator("uncertainty_id", "statement", "kind", "note", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Trade-off / Recommendation
# ---------------------------------------------------------------------------


class Tradeoff(BaseModel):
    """A real tension between two options, each with gains and costs.

    Dimensions are derived from the actual task artifacts — never hardcoded.
    """

    model_config = {"extra": "ignore"}

    tradeoff_id: str = ""
    dimension: str = ""  # e.g. "cost vs capability"
    option_a: str = ""
    option_b: str = ""
    gains_a: list[str] = Field(default_factory=list)
    costs_a: list[str] = Field(default_factory=list)
    gains_b: list[str] = Field(default_factory=list)
    costs_b: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)

    @field_validator(
        "gains_a",
        "costs_a",
        "gains_b",
        "costs_b",
        "evidence_ids",
        "implications",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_str_list(value)

    @field_validator(
        "tradeoff_id", "dimension", "option_a", "option_b", mode="before"
    )
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)


class Recommendation(BaseModel):
    """A proposal that must be traceable to insights / trade-offs / evidence.

    Trace chain: Recommendation → Insight / Tradeoff → EvidenceRecord → Source.
    ``status``:
      - supported: at least one supporting evidence id
      - potential: has insight/tradeoff support but no direct evidence
      - unsupported: no usable support — may only appear as a consideration
    """

    model_config = {"extra": "ignore"}

    recommendation_id: str = ""
    statement: str = ""
    supporting_insight_ids: list[str] = Field(default_factory=list)
    supporting_tradeoff_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: str = "supported"  # supported | potential | unsupported
    claim_type: str = ""  # e.g. planning_assumption for a proposal

    @field_validator(
        "supporting_insight_ids",
        "supporting_tradeoff_ids",
        "supporting_evidence_ids",
        "limitations",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_str_list(value)

    @field_validator("recommendation_id", "statement", "status", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)

    @field_validator("claim_type", mode="before")
    @classmethod
    def _claim_type(cls, value: object) -> str:
        return normalize_claim_type(value)


# ---------------------------------------------------------------------------
# Aggregate results
# ---------------------------------------------------------------------------


def _as_items(value: object, model: type[BaseModel]) -> list:
    """Coerce a loose LLM payload into ``list[model]`` without raising."""
    if value is None:
        return []
    if isinstance(value, (dict, str)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        if isinstance(item, model):
            out.append(item)
        elif isinstance(item, dict):
            try:
                out.append(model.model_validate(item))
            except Exception:
                continue
        elif isinstance(item, str) and item.strip():
            payload = {"statement": item, "claim": item, "dimension": item}
            try:
                out.append(model.model_validate(payload))
            except Exception:
                continue
    return out


class SynthesisResult(BaseModel):
    """Structured output of one cross-agent synthesis pass."""

    model_config = {"extra": "ignore"}

    key_findings: list[Finding] = Field(default_factory=list)
    supported_findings: list[Finding] = Field(default_factory=list)
    single_source_findings: list[Finding] = Field(default_factory=list)
    cross_agent_insights: list[Insight] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    tradeoffs: list[Tradeoff] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    summary: str = ""  # executive summary text produced by synthesis
    # D3: how ``summary`` was obtained. Code-owned, never proposed by the LLM:
    # "model" | "derived_from_findings" | "unavailable".
    summary_status: str = ""
    summary_reason: str = ""  # disclosure when the summary is not model-written
    notes: str = ""  # non-user-facing diagnostics (no chain-of-thought)
    # v0.6.1: code-owned audit trail (never proposed by the LLM).
    retry_count: int = 0  # how many corrective re-asks were used
    validation_errors: list[str] = Field(default_factory=list)  # dropped/trimmed refs
    # v0.6.2: per-stage audit for the staged synthesis pipeline.
    stage_audit: list[dict] = Field(default_factory=list)
    # v0.6.6: code-owned audits (never proposed by the LLM).
    evidence_selection: dict = Field(default_factory=dict)
    claim_audit: list[dict] = Field(default_factory=list)
    source_gaps: list[dict] = Field(default_factory=list)
    # D2: deterministic finding classification, derived in code from the real
    # finding state + evidence bindings. ``supported_findings`` /
    # ``single_source_findings`` remain as the LLM-proposed legacy lists; this
    # dict is the authoritative, comparable breakdown.
    finding_counts: dict = Field(default_factory=dict)

    @field_validator("key_findings", "supported_findings", "single_source_findings", mode="before")
    @classmethod
    def _findings(cls, value: object) -> list:
        return _as_items(value, Finding)

    @field_validator("cross_agent_insights", mode="before")
    @classmethod
    def _insights(cls, value: object) -> list:
        return _as_items(value, Insight)

    @field_validator("contradictions", mode="before")
    @classmethod
    def _contradictions(cls, value: object) -> list:
        return _as_items(value, Contradiction)

    @field_validator("uncertainties", mode="before")
    @classmethod
    def _uncertainties(cls, value: object) -> list:
        return _as_items(value, Uncertainty)

    @field_validator("tradeoffs", mode="before")
    @classmethod
    def _tradeoffs(cls, value: object) -> list:
        return _as_items(value, Tradeoff)

    @field_validator("recommendations", mode="before")
    @classmethod
    def _recommendations(cls, value: object) -> list:
        return _as_items(value, Recommendation)

    @field_validator("summary", "notes", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return "" if value is None else str(value)


class ReportBundle(BaseModel):
    """Everything the final report needs, with provenance intact."""

    task: str = ""
    synthesis: SynthesisResult = Field(default_factory=SynthesisResult)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    producer_agents: list[str] = Field(default_factory=list)
    status: str = "completed"  # completed | degraded | failed
    degradation_reason: str = ""
    # v0.6.6: deterministic evidence-selection + citation + source-gap audits.
    evidence_selection: dict = Field(default_factory=dict)
    claim_audit: list[dict] = Field(default_factory=list)
    source_gaps: list[dict] = Field(default_factory=list)
    # v0.6.9 (F13): audited source-identity conflicts (same id, different source).
    source_conflicts: list[dict] = Field(default_factory=list)
    # v0.6.1: explicit fallback audit. A degraded bundle must say *why* it is
    # degraded and how many retries were attempted before giving up.
    fallback_used: bool = False
    fallback_reason: str = ""
    retry_count: int = 0
    validation_errors: list[str] = Field(default_factory=list)
    stage_audit: list[dict] = Field(default_factory=list)
    # v0.6.0: deterministic provenance issues found after synthesis (dangling
    # references, missing sources). Empty when every link resolves.
    reference_issues: list[str] = Field(default_factory=list)


class FindingIndex(BaseModel):
    """Deterministic validation outcome for synthesis items."""

    valid_evidence_ids: list[str] = Field(default_factory=list)
    invalid_references: list[str] = Field(default_factory=list)
