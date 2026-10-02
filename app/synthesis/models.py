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

from pydantic import BaseModel, Field, field_validator

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
    verified: bool = True

    @field_validator("claim_type", mode="before")
    @classmethod
    def _claim_type(cls, value: object) -> str:
        return normalize_claim_type(value)


class SourceRecord(BaseModel):
    """Deduplicated source with URL preserved."""

    source_id: str
    title: str = ""
    url: str = ""
    source_type: str = "offline_mock"
    retrieved_at: str = ""
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
    support_kind: str = "multi_source"  # multi_source | single_source | unsupported
    notes: str = ""
    # v0.6.0: data nature + how a derived value was computed (optional).
    claim_type: str = ""
    derivation: str = ""

    @field_validator("evidence_ids", "supporting_agents", mode="before")
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
    notes: str = ""  # non-user-facing diagnostics (no chain-of-thought)

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
    # v0.6.0: deterministic provenance issues found after synthesis (dangling
    # references, missing sources). Empty when every link resolves.
    reference_issues: list[str] = Field(default_factory=list)


class FindingIndex(BaseModel):
    """Deterministic validation outcome for synthesis items."""

    valid_evidence_ids: list[str] = Field(default_factory=list)
    invalid_references: list[str] = Field(default_factory=list)
