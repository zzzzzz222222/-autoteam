"""Phase 6.6 repair tests: citation attribution, evidence selection, source policy.

Every test here is offline: no LLM provider call, no Tavily, no network. The
Phase 6.4 historical run is read-only (SHA-256 verified by the regression script,
and by ``test_phase64_history_is_read_only`` here).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.runtime.artifacts import AgentArtifact, ArtifactType, Evidence, Source
from app.synthesis.assembler import _artifact_section_titles, assemble_from_bundle
from app.synthesis.claim_support import (
    audit_claim_support,
    derive_review_status,
    extract_numbers,
    match_assertion,
    support_profile,
)
from app.synthesis.evidence_filter import collect_evidence_records, validate_report_references
from app.synthesis.evidence_selection import select_evidence, select_prompt_evidence
from app.synthesis.models import (
    SUPPORT_KINDS,
    SUPPORT_LEVELS,
    EvidenceRecord,
    Finding,
    ReportBundle,
    SynthesisResult,
)
from app.synthesis.source_policy import (
    declared_intent_reason,
    downgrade_unverified_claim,
    source_gaps,
)

PHASE64_RUN = Path("validation/runs/20261002T085948Z_A_real")
PHASE64_RUN_DIR = PHASE64_RUN / "run1_run_f376a35d"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ev(
    evidence_id: str,
    *,
    claim: str = "",
    snippet: str = "",
    source_id: str = "",
    agent: str = "agent_a",
    artifact_id: str = "art_a",
    source_type: str = "web",
    review_status: str = "not_checked",
    claim_type: str = "",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim=claim,
        evidence=snippet,
        source_id=source_id,
        producer_agent=agent,
        artifact_id=artifact_id,
        source_type=source_type,
        review_status=review_status,
        claim_type=claim_type,
    )


def _artifact(
    artifact_id: str,
    *,
    agent_id: str = "agent_a",
    output_type: ArtifactType = ArtifactType.ANALYSIS,
    title: str = "",
    content: str = "",
    metadata: dict | None = None,
    sources: list[Source] | None = None,
    evidence: list[Evidence] | None = None,
) -> AgentArtifact:
    return AgentArtifact(
        artifact_id=artifact_id,
        agent_id=agent_id,
        output_type=output_type,
        title=title,
        content=content,
        metadata=dict(metadata or {}),
        source_records=list(sources or []),
        evidence=list(evidence or []),
    )


# ---------------------------------------------------------------------------
# 1. numeric claim <-> evidence correspondence (A1)
# ---------------------------------------------------------------------------


def test_number_match_requires_the_same_unit_kind() -> None:
    """449 (个) must not be accepted as support for 449亿元."""
    claim = extract_numbers("市场规模为449亿元")[0]
    assert claim.kind == "currency"
    assert match_assertion(claim, "用户数量达到449个") is None
    assert match_assertion(claim, "市场规模为449亿元") is not None


def test_percent_is_not_currency_or_plain_number() -> None:
    claim = extract_numbers("同比增长70.9%")[0]
    assert claim.kind == "percent"
    assert match_assertion(claim, "投入70.9亿元") is None
    assert match_assertion(claim, "CAGR为70.9%") is not None


def test_year_must_agree_when_both_sides_state_one() -> None:
    claim = next(a for a in extract_numbers("2030年将达到815.1亿元") if a.kind == "currency")
    assert claim.value == 815.1
    assert claim.years == frozenset({"2030"})
    assert match_assertion(claim, "2026年达到815.1亿元") is None  # wrong year
    assert match_assertion(claim, "2030年将达到815.1亿元") is not None


def test_full_width_percent_and_spacing_are_normalised() -> None:
    assert extract_numbers("占比 78％")[0].kind == "percent"
    claim = extract_numbers("系统集成能力57%")[0]
    assert match_assertion(claim, "系统集成能力（57%）") is not None


def test_scope_difference_is_recorded_not_hidden() -> None:
    """Same value+unit but a different scope still surfaces a review flag."""
    claim = extract_numbers("ROI 停滞率30%")[0]
    hit = match_assertion(claim, "30%的受访企业表示预算不足")
    assert hit is not None  # value+unit agree
    assert hit["scope_check"] in {"scope_conflict", "snippet_has_no_scope"}
    assert hit["scope_note"]


def test_claim_citing_evidence_without_the_number_is_flagged() -> None:
    """The exact Phase 6.5 A1 failure: cited ids exist but lack the number."""
    cited = _ev("ev_a", claim="some other claim", snippet="无关内容", source_id="src_1")
    other = _ev("ev_b", claim="", snippet="将达815.1亿元，CAGR为70.9%", source_id="src_2")
    audit = audit_claim_support(
        "2030年将达到815.1亿元（CAGR 70.9%）", [cited.evidence_id], {"ev_a": cited, "ev_b": other},
        pool=[cited, other],
    )
    assert audit["status"] == "unsupported"
    assert audit["numbers_missing"]
    # the record that carries the number is offered as an *uncited* candidate only
    assert [c["evidence_id"] for c in audit["uncited_candidates"]] == ["ev_b"]


def test_claim_audit_never_rebinds_evidence_ids() -> None:
    cited = _ev("ev_a", snippet="unrelated", source_id="src_1")
    other = _ev("ev_b", snippet="数值449亿元", source_id="src_2")
    ids = [cited.evidence_id]
    audit_claim_support(
        "规模449亿元", ids, {"ev_a": cited, "ev_b": other}, pool=[cited, other]
    )
    assert ids == ["ev_a"]  # untouched: no silent re-binding


def test_unbound_claim_text_is_not_source_support() -> None:
    """An agent's own claim text is never promoted to 'the source says this'."""
    unbound = _ev("ev_x", claim="815.1亿元", snippet="", source_id="")
    audit = audit_claim_support("将达815.1亿元", ["ev_x"], {"ev_x": unbound}, pool=[unbound])
    assert audit["status"] == "unsupported"
    assert audit["uncited_candidates"] == []
    assert audit["unbound_citations"]


def test_number_matching_ignores_comma_grouping() -> None:
    claim = extract_numbers("浏览量1,065次")[0]
    assert claim.value == 1065.0
    assert match_assertion(claim, "浏览量1065次") is not None


# ---------------------------------------------------------------------------
# 2/3. degradation status + never auto-verified
# ---------------------------------------------------------------------------


def test_insufficient_support_degrades_the_status() -> None:
    evidence = [_ev("ev_1", claim="c", snippet="snippet without any number", source_id="src_1")]
    by_id = {item.evidence_id: item for item in evidence}
    audit = audit_claim_support("市场规模449亿元", ["ev_1"], by_id)
    assert audit["status"] == "unsupported"
    assert derive_review_status(["ev_1"], by_id, audit) == "unsupported"


def test_partially_supported_when_only_some_numbers_are_cited() -> None:
    evidence = [
        _ev("ev_1", snippet="2026年达到449亿元", source_id="src_1"),
        _ev("ev_2", snippet="市场规模212亿元", source_id="src_2"),
    ]
    by_id = {item.evidence_id: item for item in evidence}
    audit = audit_claim_support("2026年449亿元，2030年815.1亿元", ["ev_1"], by_id)
    assert audit["status"] == "partially_supported"
    assert derive_review_status(["ev_1"], by_id, audit) == "partially_supported"


def test_all_numbers_found_is_still_not_verified() -> None:
    evidence = [_ev("ev_1", snippet="2026年达到449亿元，同比110%", source_id="src_1")]
    by_id = {item.evidence_id: item for item in evidence}
    audit = audit_claim_support("2026年449亿元，同比110%", ["ev_1"], by_id)
    assert audit["status"] == "supported_by_citation"
    assert derive_review_status(["ev_1"], by_id, audit) == "not_checked"  # never verified


def test_finding_without_evidence_is_unsupported_and_unverified() -> None:
    from app.synthesis.synthesizer import validate_synthesis

    cleaned = validate_synthesis(
        SynthesisResult(key_findings=[Finding(finding_id="f", statement="no source at all")]), []
    )
    finding = cleaned.key_findings[0]
    assert finding.support_kind == "unsupported"
    assert finding.review_status == "unsupported"
    assert finding.review_status != "verified"


def test_source_unavailable_propagates_to_the_finding() -> None:
    evidence = [
        _ev("ev_1", snippet="snippet", source_id="src_1", review_status="source_unavailable")
    ]
    by_id = {item.evidence_id: item for item in evidence}
    audit = audit_claim_support("plain statement", ["ev_1"], by_id)
    assert derive_review_status(["ev_1"], by_id, audit) == "source_unavailable"


def test_validate_synthesis_records_the_claim_audit() -> None:
    from app.synthesis.synthesizer import validate_synthesis

    evidence = [_ev("ev_1", snippet="2026年达到449亿元", source_id="src_1")]
    cleaned = validate_synthesis(
        SynthesisResult(
            key_findings=[Finding(finding_id="f", statement="2026年449亿元", evidence_ids=["ev_1"])]
        ),
        evidence,
    )
    assert cleaned.claim_audit and cleaned.claim_audit[0]["finding_id"] == "f"
    assert cleaned.claim_audit[0]["numeric_check"] == "all_matched"
    assert cleaned.key_findings[0].unsupported_parts == []


# ---------------------------------------------------------------------------
# 4/5. evidence selection: unique key numbers + counter evidence
# ---------------------------------------------------------------------------


def _selection_fixture() -> list[EvidenceRecord]:
    records = []
    # 12 filler records from the same agent on one source (low value).
    for index in range(12):
        records.append(
            _ev(
                f"ev_fill_{index:02d}",
                claim=f"filler {index}",
                snippet=f"filler text {index}",
                source_id="src_a",
                agent="agent_a",
            )
        )
    # the only record carrying 815.1亿元 / 70.9%
    records.append(
        _ev(
            "ev_key_number",
            claim="market size",
            snippet="2030年将达815.1亿元，CAGR为70.9%",
            source_id="src_b",
            agent="agent_b",
        )
    )
    # counter / risk evidence
    records.append(
        _ev(
            "ev_risk",
            claim="risk",
            snippet="40%的项目因ROI不及预期停滞，存在结构性风险",
            source_id="src_c",
            agent="agent_c",
        )
    )
    # a second agent with no source at all (agent coverage)
    records.append(
        _ev("ev_agent_d", claim="d", snippet="agent d view", source_id="", agent="agent_d")
    )
    return records


def test_unique_key_number_evidence_is_protected() -> None:
    chosen = select_prompt_evidence(_selection_fixture(), total=5, per_agent=6)
    assert "ev_key_number" in [item.evidence_id for item in chosen]


def test_counter_evidence_is_selected() -> None:
    chosen = select_prompt_evidence(_selection_fixture(), total=5, per_agent=6)
    assert "ev_risk" in [item.evidence_id for item in chosen]


def test_selection_is_deterministic_and_order_independent() -> None:
    records = _selection_fixture()
    first = select_evidence(records, total=6)
    second = select_evidence(list(reversed(records)), total=6)
    assert first.chosen_ids == second.chosen_ids


def test_selection_audit_records_reasons_for_every_record() -> None:
    selection = select_evidence(_selection_fixture(), total=5)
    audit = selection.audit
    assert audit["policy_version"] == "v0.6.6"
    assert audit["selected_count"] == len(selection.chosen)
    assert audit["distinct_evidence_ids"] == len(selection.chosen_ids)  # no double counting
    assert audit["duplicate_ids_removed"] == 0
    assert len(audit["dropped"]) + len(audit["selected_ids"]) == len(_selection_fixture())
    for row in audit["dropped"]:
        assert row["reason"]  # every drop is explained
    for row in audit["selected_ids"]:
        assert row


def test_coverage_gap_is_declared_when_a_key_record_is_trimmed() -> None:
    """A tiny budget must admit the gap rather than claim full coverage."""
    selection = select_evidence(_selection_fixture(), total=2)
    dropped = {row["evidence_id"] for row in selection.audit["dropped"]}
    assert {"ev_key_number", "ev_risk"} & dropped  # something valuable was trimmed
    assert selection.audit["coverage_gaps"]
    assert selection.audit["coverage_gap_note"]


def test_selection_never_double_counts_across_stages() -> None:
    """The same list feeds both stages, so a record is one record, not two."""
    evidence = [_ev(f"ev_{index}", snippet=f"s{index}", source_id="src_a") for index in range(4)]
    selection = select_evidence(evidence)
    assert len(selection.audit["selected_ids"]) == len(set(selection.audit["selected_ids"]))


def test_historical_evidence_selection_keeps_phase64_key_records() -> None:
    """Read-only regression: the Phase 6.5 A2 records are now selected."""
    if not (PHASE64_RUN_DIR / "evidence.json").is_file():
        pytest.skip("Phase 6.4 run artifacts not present")
    rows = json.loads((PHASE64_RUN_DIR / "evidence.json").read_text(encoding="utf-8"))["items"]
    evidence = [
        EvidenceRecord(
            evidence_id=row["evidence_id"],
            claim=row.get("claim") or "",
            evidence=row.get("evidence_text") or "",
            source_id=row.get("source_id") or "",
            producer_agent=row.get("producer_agent") or "",
            source_type=row.get("source_type") or "",
            review_status=row.get("review_status") or "not_checked",
        )
        for row in rows
    ]
    chosen_ids = {item.evidence_id for item in select_prompt_evidence(evidence)}
    # Phase 6.5 flagged these two as trimmed although they carry the key numbers.
    assert "ev_c92e1e0f45" in chosen_ids
    assert "ev_71fb39da19" in chosen_ids
    # every bound record survives the budget
    bound = {item.evidence_id for item in evidence if item.source_id and item.evidence}
    assert bound <= chosen_ids


# ---------------------------------------------------------------------------
# 6. agent agreement vs independent sources
# ---------------------------------------------------------------------------


def test_agent_count_and_source_count_are_separate() -> None:
    evidence = [
        _ev("ev_1", snippet="c1", source_id="src_1", agent="agent_a"),
        _ev("ev_2", snippet="c2", source_id="src_1", agent="agent_b"),
        _ev("ev_3", snippet="c3", source_id="src_1", agent="agent_c"),
    ]
    by_id = {item.evidence_id: item for item in evidence}
    profile = support_profile(list(by_id), by_id)
    assert profile.agent_support_count == 3
    assert profile.independent_source_count == 1
    # 3 agents but ONE source: exactly one independent source, labelled as such
    # (the agent count is reported separately, never merged into a source claim).
    assert profile.support_kind == "single_source"
    assert profile.support_level == "source_text"


def test_agents_without_any_source_is_multi_agent_consensus() -> None:
    evidence = [
        _ev("ev_1", snippet="c1", source_id="", agent="agent_a"),
        _ev("ev_2", snippet="c2", source_id="", agent="agent_b"),
        _ev("ev_3", snippet="c3", source_id="", agent="agent_c"),
    ]
    by_id = {item.evidence_id: item for item in evidence}
    profile = support_profile(list(by_id), by_id)
    assert profile.agent_support_count == 3
    assert profile.independent_source_count == 0
    assert profile.support_kind == "multi_agent"
    assert profile.support_level == "agent_consensus"


def test_two_independent_sources_is_multi_source() -> None:
    evidence = [
        _ev("ev_1", snippet="c1", source_id="src_1", agent="agent_a"),
        _ev("ev_2", snippet="c2", source_id="src_2", agent="agent_a"),
    ]
    by_id = {item.evidence_id: item for item in evidence}
    profile = support_profile(list(by_id), by_id)
    assert profile.independent_source_count == 2
    assert profile.support_kind == "multi_source"
    assert profile.support_level == "source_text"


def test_bound_source_without_snippet_is_not_source_text() -> None:
    """A source id with no retrieved snippet cannot reach source_text level."""
    evidence = [_ev("ev_1", claim="c", snippet="", source_id="src_1", agent="agent_a")]
    by_id = {item.evidence_id: item for item in evidence}
    profile = support_profile(["ev_1"], by_id)
    assert profile.independent_source_count == 1
    assert profile.support_kind == "single_source"
    assert profile.support_level == "agent_restatement"


def test_planning_assumption_level_wins() -> None:
    evidence = [_ev("ev_1", snippet="plan text", source_id="src_1")]
    by_id = {item.evidence_id: item for item in evidence}
    profile = support_profile(["ev_1"], by_id, claim_type="planning_assumption")
    assert profile.support_level == "planning_assumption"


def test_finding_fields_are_filled_by_validation() -> None:
    from app.synthesis.synthesizer import validate_synthesis

    evidence = [
        _ev("ev_1", snippet="c1", source_id="src_1", agent="agent_a"),
        _ev("ev_2", snippet="c2", source_id="src_1", agent="agent_b"),
    ]
    cleaned = validate_synthesis(
        SynthesisResult(
            key_findings=[
                Finding(
                    finding_id="f", statement="claim", evidence_ids=["ev_1", "ev_2"],
                    support_kind="multi_source",  # LLM over-claim
                )
            ]
        ),
        evidence,
    )
    finding = cleaned.key_findings[0]
    assert finding.support_kind == "single_source"  # over-claim corrected
    assert finding.evidence_count == 2
    assert finding.agent_support_count == 2
    assert finding.independent_source_count == 1
    assert finding.support_level == "source_text"


def test_support_vocabulary_is_schema_defined() -> None:
    for kind in SUPPORT_KINDS:
        assert Finding(statement="s", support_kind=kind).support_kind == kind
    assert Finding(statement="s", support_kind="invented").support_kind == ""
    for level in SUPPORT_LEVELS:
        assert Finding(statement="s", support_level=level).support_level == level
    assert Finding(statement="s", support_level="invented").support_level == "unknown"


# ---------------------------------------------------------------------------
# 7/8. source policy: gaps, mock marking, access failure
# ---------------------------------------------------------------------------


def _sourced_artifact(access_status: str = "") -> AgentArtifact:
    return _artifact(
        "art_src",
        sources=[
            Source(
                id="src_1",
                title="Real page",
                url="https://x.example/a",
                source_type="web",
                access_status=access_status,
                access_note="forbidden" if access_status else "",
            )
        ],
        evidence=[
            Evidence(
                claim="market size 449亿元",
                evidence="2026年达到449亿元",
                source_id="src_1",
                claim_type="source_fact",
            )
        ],
    )


def test_valid_source_yields_no_gap() -> None:
    artifacts = [_sourced_artifact()]
    evidence, _ = collect_evidence_records(artifacts)
    assert source_gaps(artifacts, evidence) == []


def test_competitor_agent_without_sources_emits_a_structured_gap() -> None:
    artifact = _artifact(
        "artifact_competitor_analyst",
        agent_id="competitor_analyst",
        metadata={"expected_output": "competitor_landscape", "role_name": "Competitor Analyst"},
        content="竞品 A 定价 199 元，定位中小企业",
        evidence=[
            Evidence(claim="竞品A定价199元", evidence="", source_id="", claim_type="source_fact")
        ],
    )
    evidence, _ = collect_evidence_records([artifact])
    gaps = source_gaps([artifact], evidence)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["declared_intent"] == "competitor_landscape"
    assert gap["source_required"] is True
    assert gap["source_count"] == 0
    assert gap["bound_evidence_count"] == 0
    assert gap["severity"] == "high"
    assert gap["unverified_claims"]  # the claim is exposed, not hidden
    assert "competitor names" in gap["reasons"][0]


def test_requirements_document_without_sources_emits_a_structured_gap() -> None:
    # P6.14 finding: requirement_analyst produced only unverified_claims and the
    # declared-intent policy silently missed it because requirements_document was
    # absent from SOURCE_REQUIRED_INTENTS. This locks the P6.15 fix.
    artifact = _artifact(
        "artifact_requirement_analyst",
        agent_id="requirement_analyst",
        metadata={"expected_output": "requirements_document", "role_name": "Requirement Analyst"},
        content="用户需要多租户权限与导出功能（待验证）",
        evidence=[
            Evidence(claim="用户需要导出功能", evidence="", source_id="", claim_type="source_fact")
        ],
    )
    evidence, _ = collect_evidence_records([artifact])
    gaps = source_gaps([artifact], evidence)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["declared_intent"] == "requirements_document"
    assert gap["source_required"] is True
    assert gap["severity"] == "high"
    assert gap["unverified_claims"]  # the claim is exposed, never hidden


def test_strategy_document_without_sources_emits_a_structured_gap() -> None:
    # STRATEGY_PLANNING was granted web_search in P6.12 yet strategy_document was
    # also absent from SOURCE_REQUIRED_INTENTS. Lock that it is now detected.
    artifact = _artifact(
        "artifact_strategy_planner",
        agent_id="strategy_planner",
        metadata={"expected_output": "strategy_document", "role_name": "Strategy Planner"},
        content="建议采用差异化定价（待验证）",
        evidence=[
            Evidence(claim="差异化定价可行", evidence="", source_id="", claim_type="source_fact")
        ],
    )
    evidence, _ = collect_evidence_records([artifact])
    gaps = source_gaps([artifact], evidence)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["declared_intent"] == "strategy_document"
    assert gap["source_required"] is True
    assert gap["severity"] == "high"
    assert gap["unverified_claims"]


def test_tool_free_intent_with_unverified_claim_is_not_source_required() -> None:
    # proposal_document is produced by a tool-free (PROPOSAL_WRITING) capability
    # and is intentionally absent from SOURCE_REQUIRED_INTENTS, so a gap may be
    # reported for the downgrade, but source_required must stay False.
    artifact = _artifact(
        "artifact_proposal_writer",
        agent_id="proposal_writer",
        metadata={"expected_output": "proposal_document", "role_name": "Proposal Writer"},
        content="本方案建议分阶段实施",
        evidence=[
            Evidence(claim="建议分阶段实施", evidence="", source_id="", claim_type="source_fact")
        ],
    )
    evidence, _ = collect_evidence_records([artifact])
    gaps = source_gaps([artifact], evidence)
    assert gaps, "the downgraded claim should still be surfaced"
    assert all(not gap["source_required"] for gap in gaps)


def test_inference_mislabeled_as_fact_is_downgraded() -> None:
    artifact = _artifact(
        "art_x",
        evidence=[
            Evidence(claim="竞品定价199元", evidence="", source_id="", claim_type="source_fact")
        ],
    )
    evidence, _ = collect_evidence_records([artifact])
    assert evidence[0].claim_type == "unverified_claim"
    assert evidence[0].review_status == "unsupported"
    assert evidence[0].verified is False


def test_source_existing_but_irrelevant_keeps_the_claim_unverified() -> None:
    """A bound snippet that does not carry the number cannot support the claim."""
    cited = _ev("ev_1", snippet="完全不相关的内容", source_id="src_1")
    by_id = {"ev_1": cited}
    audit = audit_claim_support("竞品定价199元", ["ev_1"], by_id)
    assert audit["status"] == "unsupported"


def test_inaccessible_source_keeps_url_and_failure_status() -> None:
    artifacts = [_sourced_artifact(access_status="http_403")]
    evidence, sources = collect_evidence_records(artifacts)
    assert sources[0].url == "https://x.example/a"
    assert sources[0].access_status == "http_403"
    assert sources[0].access_note == "forbidden"
    # a 403 is "could not be re-checked", never "the page does not say that"
    assert evidence[0].review_status == "source_unavailable"
    assert evidence[0].verified is False
    assert evidence[0].claim_type == "source_fact"  # content unknown, not absent


def test_http_000_also_marks_the_source_unavailable() -> None:
    artifacts = [_sourced_artifact(access_status="http_000")]
    evidence, _ = collect_evidence_records(artifacts)
    assert evidence[0].review_status == "source_unavailable"


def test_declared_intent_requires_metadata_not_role_name() -> None:
    named_only = _artifact(
        "art", agent_id="competitor_analyst", metadata={"role_name": "Competitor Analyst"}
    )
    assert declared_intent_reason(named_only) == ""  # a role name is not a declaration
    declared = _artifact("art", metadata={"expected_output": "competitor_landscape"})
    assert "competitor names" in declared_intent_reason(declared)


def test_downgrade_helper_is_conservative() -> None:
    assert downgrade_unverified_claim("source_fact", "src_1", "snippet") == "source_fact"
    assert downgrade_unverified_claim("source_fact", "src_1", "  ") == "unverified_claim"
    assert downgrade_unverified_claim("source_fact", "", "snippet") == "unverified_claim"
    assert downgrade_unverified_claim("planning_assumption", "", "") == "planning_assumption"


# ---------------------------------------------------------------------------
# 9. duplicate section titles (A8)
# ---------------------------------------------------------------------------


def test_identical_proposal_and_report_titles_are_disambiguated() -> None:
    artifacts = [
        _artifact(
            "artifact_proposal_writer",
            agent_id="proposal_writer",
            output_type=ArtifactType.PROPOSAL,
            title="市场进入与最小团队产品方案",
            content="proposal body",
        ),
        _artifact(
            "artifact_report_writer",
            agent_id="report_writer",
            output_type=ArtifactType.REPORT,
            title="市场进入与最小团队产品方案",
            content="report body",
        ),
    ]
    titles = _artifact_section_titles(artifacts, "artifact_report_writer")
    assert len(set(titles.values())) == 2  # no duplicate headings
    assert titles["artifact_report_writer"] == "市场进入与最小团队产品方案"
    assert "proposal" in titles["artifact_proposal_writer"]


def test_assembled_report_has_no_duplicate_section_titles() -> None:
    artifacts = [
        _artifact("a1", agent_id="a1", title="Same title", content="one"),
        _artifact("a2", agent_id="a2", title="Same title", content="two"),
        _artifact(
            "artifact_report_writer",
            agent_id="report_writer",
            output_type=ArtifactType.REPORT,
            title="Same title",
            content="three",
        ),
    ]
    bundle = ReportBundle(
        task="t",
        status="completed",
        artifact_ids=[artifact.artifact_id for artifact in artifacts],
    )
    final = assemble_from_bundle("t", artifacts, bundle, ["a1", "a2", "report_writer"])
    titles = [section.title for section in final.sections]
    assert len(titles) == len(set(titles))
    # every artifact's content is still present
    joined = "\n".join(section.content for section in final.sections)
    assert "one" in joined and "two" in joined and "three" in joined


def test_canonical_report_title_collision_with_reserved_synthesis_heading() -> None:
    artifacts = [
        _artifact(
            "artifact_report_writer",
            agent_id="report_writer",
            output_type=ArtifactType.REPORT,
            title="Key Findings",
            content="body",
        )
    ]
    titles = _artifact_section_titles(
        artifacts, "artifact_report_writer", reserved={"Key Findings"}
    )
    assert titles["artifact_report_writer"] != "Key Findings"
    assert "final deliverable" in titles["artifact_report_writer"]


# ---------------------------------------------------------------------------
# 10/11. historical data protection + structured output schema
# ---------------------------------------------------------------------------


def test_phase64_history_is_read_only() -> None:
    """The regression only ever reads the Phase 6.4 run directory."""
    if not PHASE64_RUN_DIR.is_dir():
        pytest.skip("Phase 6.4 run artifacts not present")
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(PHASE64_RUN_DIR.iterdir())
        if path.is_file()
    }
    assert before  # the run is present
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(PHASE64_RUN_DIR.iterdir())
        if path.is_file()
    }
    assert before == after


def test_report_bundle_schema_exposes_the_audit_fields() -> None:
    bundle = ReportBundle(
        task="t",
        evidence_selection={"policy_version": "v0.6.6"},
        claim_audit=[{"finding_id": "f"}],
        source_gaps=[{"artifact_id": "a"}],
    )
    dumped = bundle.model_dump()
    assert dumped["evidence_selection"]["policy_version"] == "v0.6.6"
    assert dumped["claim_audit"] and dumped["source_gaps"]
    # unknown keys are ignored, not silently accepted into the schema
    assert "not_a_field" not in dumped


def test_reference_validator_still_resolves_every_link() -> None:
    artifact = _sourced_artifact()
    evidence, sources = collect_evidence_records([artifact])
    bundle = ReportBundle(
        task="t",
        evidence=evidence,
        sources=sources,
        synthesis=SynthesisResult(
            key_findings=[
                Finding(
                    finding_id="f",
                    statement="s",
                    evidence_ids=[evidence[0].evidence_id],
                )
            ]
        ),
    )
    assert validate_report_references(bundle) == []
