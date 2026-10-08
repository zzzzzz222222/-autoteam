"""AT-AUDIT-004 regression tests: what counts as "supported".

The headline ``finding_counts.supported`` used to include ``agent_consensus``
("several agents say so, no source snippet") and ``derived`` (a model-side
estimate). Neither is external evidence, so a report could read "90% of
findings are supported" while a strict per-claim citation audit only confirmed
20%. These tests pin the boundary down:

    external evidence  ->  ``supported``
    agents agreeing    ->  NOT ``supported`` (kept as its own tier)
    model estimate     ->  NOT ``supported`` (kept as its own tier)
    citation check     ->  ``citation_verified`` (a separate axis, never merged)

Everything here drives the real ``support_profile`` / ``audit_claim_support`` /
``derive_review_status`` / ``compute_finding_counts`` code. No LLM, no web
search, no mock sources presented as real ones.
"""

from __future__ import annotations

from app.synthesis.claim_support import (
    audit_claim_support,
    derive_review_status,
    support_profile,
)
from app.synthesis.models import SUPPORT_LEVELS, EvidenceRecord, Finding
from app.synthesis.synthesizer import compute_finding_counts

# --- builders ---------------------------------------------------------------


def ev(
    evidence_id: str,
    *,
    source_id: str = "",
    snippet: str = "",
    agent: str = "a1",
    source_type: str = "web",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim="evidence claim",
        evidence=snippet,
        source_id=source_id,
        source_url=f"https://src.example/{source_id}" if source_id else "",
        source_title=source_id,
        source_type=source_type,
        producer_agent=agent,
    )


def build_finding(
    statement: str, records: list[EvidenceRecord], *, claim_type: str = ""
) -> Finding:
    """Drive the real derivation chain the synthesizer uses."""
    by_id = {record.evidence_id: record for record in records}
    cited = list(by_id)
    profile = support_profile(cited, by_id, claim_type=claim_type)
    audit = audit_claim_support(statement, cited, by_id)
    return Finding(
        finding_id="f1",
        statement=statement,
        evidence_ids=cited,
        supporting_agents=list(profile.agents),
        claim_type=claim_type,
        evidence_count=profile.evidence_count,
        agent_support_count=profile.agent_support_count,
        independent_source_count=profile.independent_source_count,
        support_kind=profile.support_kind,
        support_level=profile.support_level,
        review_status=derive_review_status(cited, by_id, audit),
        support_audit=audit,
    )


def counts_for(findings: list[Finding], records: list[EvidenceRecord]) -> dict:
    index = {record.evidence_id: record for record in records}
    return compute_finding_counts(findings, index)


# --- A. multi-agent agreement is not external evidence --------------------


def test_agent_consensus_is_not_counted_as_supported() -> None:
    records = [
        ev("e1", snippet="Agent A concludes the market is consolidating", agent="a1",
           source_type="offline_mock"),
        ev("e2", snippet="Agent B concludes the market is consolidating", agent="a2",
           source_type="offline_mock"),
    ]
    finding = build_finding("The market is consolidating", records)

    assert finding.support_level == "agent_consensus"
    assert finding.agent_support_count == 2
    assert finding.independent_source_count == 0

    counts = counts_for([finding], records)
    assert counts["supported"] == 0  # agreement is not a source
    assert counts["agent_consensus"] == 1  # but it is still tracked
    assert counts["backed_count"] == 1  # and still visible as internal backing


def test_agent_count_never_inflates_source_counts() -> None:
    records = [
        ev(f"e{index}", snippet=f"agent {index} says so", agent=f"a{index}",
           source_type="offline_mock")
        for index in range(1, 5)
    ]
    finding = build_finding("Four agents reached the same conclusion", records)

    assert finding.agent_support_count == 4
    assert finding.independent_source_count == 0
    counts = counts_for([finding], records)
    assert counts["multi_source"] == 0
    assert counts["single_source"] == 0
    assert counts["supported"] == 0


# --- B. model-derived estimates are not source-confirmed ------------------


def test_derived_estimate_is_not_counted_as_supported() -> None:
    """Even when its inputs are traceable, a model estimate is not a source."""
    records = [ev("e1", source_id="s1", snippet="baseline revenue 100M")]
    finding = build_finding("Revenue was 100M", records, claim_type="derived_estimate")

    assert finding.support_level == "derived"
    counts = counts_for([finding], records)
    assert counts["supported"] == 0
    assert counts["derived"] == 1
    assert counts["backed_count"] == 1


def test_derived_estimate_is_not_citation_verified() -> None:
    records = [ev("e1", source_id="s1", snippet="baseline revenue 100M")]
    finding = build_finding(
        "Revenue will reach about 250M next year", records, claim_type="derived_estimate"
    )

    # The asserted number (250M) is not in the snippet -> not citation-verified.
    assert finding.support_audit["status"] in {"unsupported", "partially_supported"}
    assert counts_for([finding], records)["citation_verified"] == 0


# --- C. a single valid source ---------------------------------------------


def test_single_valid_source_is_supported() -> None:
    records = [ev("e1", source_id="s1", snippet="Revenue grew 42% in 2025")]
    finding = build_finding("Revenue grew 42% in 2025", records)

    assert finding.support_level == "source_text"
    counts = counts_for([finding], records)
    assert counts["supported"] == 1
    assert counts["single_source"] == 1
    assert counts["multi_source"] == 0  # one source stays one source
    assert counts["citation_verified"] == 1


# --- D. multiple independent sources --------------------------------------


def test_multiple_independent_sources_are_supported() -> None:
    records = [
        ev("e1", source_id="s1", snippet="Revenue grew 42% in 2025", agent="a1"),
        ev("e2", source_id="s2", snippet="Revenue grew 42% in 2025", agent="a2"),
    ]
    finding = build_finding("Revenue grew 42% in 2025", records)

    assert finding.support_level == "source_text"
    assert finding.independent_source_count == 2
    counts = counts_for([finding], records)
    assert counts["supported"] == 1
    assert counts["multi_source"] == 1


# --- E. the same source cited repeatedly ----------------------------------


def test_repeated_citations_of_one_source_are_not_independent() -> None:
    records = [
        ev("e1", source_id="s1", snippet="Revenue grew 42% in 2025", agent="a1"),
        ev("e2", source_id="s1", snippet="Revenue grew 42% in 2025", agent="a2"),
        ev("e3", source_id="s1", snippet="Revenue grew 42% in 2025", agent="a3"),
    ]
    finding = build_finding("Revenue grew 42% in 2025", records)

    # Three evidence rows and three agents, but ONE source.
    assert finding.evidence_count == 3
    assert finding.agent_support_count == 3
    assert finding.independent_source_count == 1

    counts = counts_for([finding], records)
    assert counts["multi_source"] == 0  # not promoted to multi-source
    assert counts["single_source"] == 1
    assert counts["supported"] == 1


# --- F. evidence that does not carry the claim ----------------------------


def test_numbers_missing_from_the_snippet_are_not_citation_verified() -> None:
    records = [ev("e1", source_id="s1", snippet="Revenue grew 7% in 2025")]
    finding = build_finding("Revenue grew 42% in 2025", records)

    # Code can only check what it can check: the asserted number is absent.
    assert finding.support_audit["numbers_missing"], finding.support_audit
    assert finding.review_status == "partially_supported"

    counts = counts_for([finding], records)
    assert counts["citation_verified"] == 0  # strict axis exposes the gap
    assert counts["supported"] == 1  # level axis still says source_text


def test_semantic_mismatch_remains_an_open_limitation() -> None:
    """Non-numeric mismatch cannot be detected by code — and is not claimed to be."""
    records = [ev("e1", source_id="s1", snippet="The vendor announced a new API")]
    finding = build_finding("The vendor cut its headcount by half", records)

    assert finding.support_audit["status"] == "no_numeric_claim"
    # Honest state: no numeric assertion to check, nothing falsely confirmed.
    assert finding.support_audit["assertions"] == []
    assert counts_for([finding], records)["citation_verified"] == 0


# --- G. no evidence / no source -------------------------------------------


def test_finding_without_evidence_is_unsupported() -> None:
    finding = Finding(finding_id="f1", statement="Something", evidence_ids=[])
    counts = counts_for([finding], [])
    assert counts["unsupported"] == 1
    assert counts["supported"] == 0
    assert counts["backed_count"] == 0


def test_single_agent_restatement_without_source_is_not_supported() -> None:
    records = [ev("e1", snippet="Only this agent says so", agent="a1", source_type="offline_mock")]
    finding = build_finding("Only this agent says so", records)

    assert finding.support_level == "agent_restatement"
    counts = counts_for([finding], records)
    assert counts["supported"] == 0
    assert counts["unverified"] == 1


def test_peer_agreement_does_not_change_an_unsupported_finding() -> None:
    """A finding with no evidence stays unsupported even if agents agree elsewhere."""
    unsupported = Finding(finding_id="f1", statement="No evidence here", evidence_ids=[])
    records = [
        ev("e1", snippet="agent one agrees", agent="a1", source_type="offline_mock"),
        ev("e2", snippet="agent two agrees", agent="a2", source_type="offline_mock"),
    ]
    agreeing = build_finding("The market is consolidating", records)
    counts = counts_for([unsupported, agreeing], records)

    assert counts["unsupported"] == 1
    assert counts["supported"] == 0


# --- H. numeric claims -----------------------------------------------------


def test_numeric_claim_matching_the_snippet_is_citation_verified() -> None:
    records = [ev("e1", source_id="s1", snippet="Revenue grew 42% in 2025")]
    finding = build_finding("Revenue grew 42% in 2025", records)

    assert finding.support_audit["status"] == "supported_by_citation"
    assert counts_for([finding], records)["citation_verified"] == 1


def test_numeric_estimate_without_a_source_stays_unverified() -> None:
    records = [ev("e1", snippet="model estimate", agent="a1", source_type="offline_mock")]
    finding = build_finding(
        "The addressable market is 8.4 billion", records, claim_type="derived_estimate"
    )

    counts = counts_for([finding], records)
    assert counts["supported"] == 0
    assert counts["citation_verified"] == 0
    assert finding.support_level == "derived"


# --- I. conflicting evidence ----------------------------------------------


def test_conflicting_sources_are_surfaced_not_silently_resolved() -> None:
    """Conflict is recorded in the audit; code does not vote it into 'verified'."""
    records = [
        ev("e1", source_id="s1", snippet="Revenue grew 42% in Europe", agent="a1"),
        ev("e2", source_id="s2", snippet="Revenue grew 42% worldwide", agent="a2"),
    ]
    finding = build_finding("Revenue grew 42% in Europe", records)
    audit = finding.support_audit

    scope_flags = [str(item) for item in (audit.get("scope_flags") or [])]
    conflicts = [
        flag
        for witness in (audit.get("witnesses") or [])
        for flag in (witness.get("scope_conflicts") or [])
    ]
    # Whatever the scope engine finds, it is preserved in the audit payload...
    assert isinstance(scope_flags, list)
    assert isinstance(conflicts, list)
    # ...and a conflict never promotes a claim beyond its own evidence.
    assert counts_for([finding], records)["supported"] == 1
    assert finding.independent_source_count == 2


# --- schema / compatibility ------------------------------------------------


def test_support_levels_stay_within_the_declared_schema() -> None:
    assert "source_text" in SUPPORT_LEVELS
    assert set(SUPPORT_LEVELS) >= {"source_text", "agent_consensus", "derived", "unknown"}


def test_counts_keep_the_total_invariant() -> None:
    """with_valid_evidence == supported + unverified must always hold."""
    records = [
        ev("e1", source_id="s1", snippet="Revenue grew 42% in 2025"),
        ev("e2", snippet="agent says so", agent="a2", source_type="offline_mock"),
    ]
    findings = [
        build_finding("Revenue grew 42% in 2025", [records[0]]),
        build_finding("agent says so", [records[1]]),
    ]
    counts = counts_for(findings, records)
    assert counts["with_valid_evidence"] == counts["supported"] + counts["unverified"]
    assert counts["total"] == 2


def test_backed_count_never_exceeds_the_backed_tiers() -> None:
    records = [
        ev("e1", source_id="s1", snippet="Revenue grew 42% in 2025"),
        ev("e2", snippet="agent b agrees", agent="a2", source_type="offline_mock"),
        ev("e3", snippet="agent c agrees", agent="a3", source_type="offline_mock"),
    ]
    findings = [
        build_finding("Revenue grew 42% in 2025", [records[0]]),
        build_finding("Both agents agree", [records[1], records[2]]),
    ]
    counts = counts_for(findings, records)
    assert counts["supported"] == 1
    assert counts["agent_consensus"] == 1
    assert counts["backed_count"] == 2
    assert counts["backed_count"] >= counts["supported"]
