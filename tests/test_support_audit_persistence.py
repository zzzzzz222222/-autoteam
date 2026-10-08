"""v0.6.2 (AT-AUDIT-004 follow-up): ``support_audit`` must survive persistence.

The per-claim citation verdict lived only **in memory**: live runs carried it on
``Finding.support_audit`` (so ``finding_counts.citation_verified`` had a real
value and landed in ``metrics.json``), but ``validation/collect.py`` serialized
findings with an explicit field tuple that left it out. Reloading
``synthesis.json`` and re-running ``compute_finding_counts`` therefore produced
``citation_verified = 0`` — the live result and the offline re-check disagreed.

This module pins the whole round trip::

    live Finding -> collect -> synthesis.json -> json round trip
        -> restore -> compute_finding_counts == live counts

Fully offline: no provider, no network, no paid API, no mock source presented
as a real one.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.synthesis.claim_support import (
    audit_claim_support,
    derive_review_status,
    support_profile,
)
from app.synthesis.models import (
    EvidenceRecord,
    Finding,
    ReportBundle,
    SourceRecord,
    SynthesisResult,
)
from app.synthesis.synthesizer import compute_finding_counts
from validation.collect import collect_metrics, restore_finding_audit

COUNT_KEYS = (
    "total",
    "with_valid_evidence",
    "supported",
    "backed_count",
    "citation_verified",
    "multi_source",
    "single_source",
    "agent_consensus",
    "derived",
    "unverified",
    "unsupported",
)


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
        source_title=source_id or agent,
        source_type=source_type,
        producer_agent=agent,
    )


def finding(
    finding_id: str,
    statement: str,
    records: list[EvidenceRecord],
    *,
    claim_type: str = "",
) -> Finding:
    """Build a finding through the same derivation chain the synthesizer uses."""
    by_id = {record.evidence_id: record for record in records}
    cited = list(by_id)
    profile = support_profile(cited, by_id, claim_type=claim_type)
    audit = audit_claim_support(statement, cited, by_id)
    return Finding(
        finding_id=finding_id,
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


def mixed_records() -> list[EvidenceRecord]:
    return [
        ev("e_src", source_id="s1", snippet="Revenue grew 42% in 2025"),
        ev("e_src2", source_id="s2", snippet="Revenue grew 42% in 2025"),
        ev("e_missing", source_id="s3", snippet="baseline revenue 100M"),
        ev("e_agent1", snippet="agent a concludes X", agent="a1", source_type="offline_mock"),
        ev("e_agent2", snippet="agent b concludes X", agent="a2", source_type="offline_mock"),
        ev("e_est", source_id="s4", snippet="baseline revenue 100M"),
    ]


def mixed_findings(records: list[EvidenceRecord]) -> list[Finding]:
    """One finding per support tier, including a dangling-evidence one."""
    by = {record.evidence_id: record for record in records}
    return [
        # external source, numbers match -> citation_verified
        finding("f_source", "Revenue grew 42% in 2025", [by["e_src"], by["e_src2"]]),
        # external source, but the asserted number is absent -> not verified
        finding("f_missing", "Revenue grew 77% in 2025", [by["e_missing"]]),
        # agents agreeing, no source -> internal backing only
        finding("f_consensus", "X is true", [by["e_agent1"], by["e_agent2"]]),
        # model estimate from traceable inputs -> internal backing only
        finding(
            "f_derived",
            "Revenue was 100M",
            [by["e_est"]],
            claim_type="derived_estimate",
        ),
        # dangling evidence id -> unsupported
        finding("f_dangling", "Something unsupported", []),
    ]


def persist_and_reload(
    findings: list[Finding], records: list[EvidenceRecord]
) -> tuple[dict, dict]:
    """Run collect -> JSON round trip; return (live_counts, persisted_payload)."""
    index = {record.evidence_id: record for record in records}
    for item in findings:
        # keep one finding pointing at an id that is NOT in the evidence set
        if item.finding_id == "f_dangling":
            item.evidence_ids = ["ev_does_not_exist"]
    sources = [
        SourceRecord(
            source_id=record.source_id,
            title=record.source_title,
            url=record.source_url,
            source_type=record.source_type,
        )
        for record in records
        if record.source_id
    ]
    bundle = ReportBundle(
        task="t",
        synthesis=SynthesisResult(
            key_findings=findings,
            finding_counts=compute_finding_counts(findings, index),
            summary="summary",
        ),
        evidence=records,
        sources=sources,
        artifact_ids=["artifact_1"],
        status="completed",
        claim_audit=[
            dict(item.support_audit or {}, finding_id=item.finding_id)
            for item in findings
        ],
    )
    session = SimpleNamespace(
        run_id="run_audit_004",
        task="t",
        status="success",
        started_at=1.0,
        finished_at=2.0,
        error=None,
        plan=None,
        agent_results={},
        artifacts=[],
        final_artifact=None,
        synthesis_bundle=bundle,
        trace=None,
    )
    live = dict(compute_finding_counts(findings, index))
    metrics = collect_metrics(session, scenario_id="A", mode="offline")
    payload = json.loads(json.dumps(metrics["synthesis"]))
    return live, payload


def reconstruct(payload: dict, index: set[str]) -> dict:
    """Rebuild ``Finding`` objects from the persisted rows and recount."""
    rows = payload["findings"]
    claim_audit = payload.get("claim_audit") or []
    rebuilt: list[Finding] = []
    for row in rows:
        data = dict(row)
        data["support_audit"] = restore_finding_audit(row, claim_audit)
        rebuilt.append(Finding.model_validate(data))
    return compute_finding_counts(rebuilt, index)


# --- 1. the full round trip -------------------------------------------------


def test_live_counts_match_offline_reconstruction() -> None:
    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    offline = reconstruct(payload, {record.evidence_id for record in records})

    for key in COUNT_KEYS:
        assert offline[key] == live[key], f"{key}: offline={offline[key]} live={live[key]}"


def test_offline_reconstruction_keeps_a_real_citation_verified_value() -> None:
    """``citation_verified`` used to collapse to 0 after the round trip."""
    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    offline = reconstruct(payload, {record.evidence_id for record in records})

    assert live["citation_verified"] >= 1, live
    assert offline["citation_verified"] == live["citation_verified"]


def test_every_persisted_finding_carries_its_citation_verdict() -> None:
    records = mixed_records()
    _, payload = persist_and_reload(mixed_findings(records), records)

    assert payload["findings"]
    for row in payload["findings"]:
        assert row["support_audit"]["available"] is True, row["finding_id"]
        assert "status" in row["support_audit"], row["finding_id"]


def test_persisted_rows_stay_json_serializable_and_redacted() -> None:
    records = mixed_records()
    _, payload = persist_and_reload(mixed_findings(records), records)
    text = json.dumps(payload, ensure_ascii=False)

    assert '"support_audit"' in text
    for row in payload["findings"]:
        for key, value in row["support_audit"].items():
            if isinstance(value, str):
                assert len(value) <= 400, f"{row['finding_id']}.{key} too long"
            if isinstance(value, list):
                for entry in value:
                    assert len(str(entry)) <= 400


# --- 2. the invariants survive the round trip -------------------------------


def test_supported_is_always_a_subset_of_backed_count_offline() -> None:
    records = mixed_records()
    _, payload = persist_and_reload(mixed_findings(records), records)
    offline = reconstruct(payload, {record.evidence_id for record in records})

    assert offline["supported"] <= offline["backed_count"]


def test_total_invariant_holds_offline() -> None:
    records = mixed_records()
    _, payload = persist_and_reload(mixed_findings(records), records)
    offline = reconstruct(payload, {record.evidence_id for record in records})

    assert (
        offline["with_valid_evidence"]
        == offline["supported"] + offline["unverified"]
    )
    assert offline["total"] == len(payload["findings"])


def test_all_tiers_are_represented_in_the_fixture() -> None:
    """Guard the fixture itself: an empty tier cannot prove anything."""
    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    offline = reconstruct(payload, {record.evidence_id for record in records})

    assert live["supported"] >= 1
    assert live["agent_consensus"] == 1
    assert live["derived"] == 1
    assert live["citation_verified"] >= 1
    assert live["unverified"] >= 1
    assert live["unsupported"] == 1
    for key in ("supported", "backed_count", "agent_consensus", "derived",
                "unverified", "unsupported"):
        assert offline[key] == live[key], key


# --- 3. what the old dump used to lose --------------------------------------


def test_dropping_support_audit_from_the_row_loses_citation_verified() -> None:
    """Reproduces the pre-fix behaviour without touching production code.

    Strip the new projection *and* the ``claim_audit`` fallback from an
    otherwise identical payload: the strict verdict disappears, while the
    evidence-binding keys stay put. That is exactly the gap being closed.
    """
    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    index = {record.evidence_id: record for record in records}

    legacy = json.loads(json.dumps(payload))
    for row in legacy["findings"]:
        row.pop("support_audit", None)
    legacy["claim_audit"] = []

    before = reconstruct(legacy, set(index))
    after = reconstruct(payload, set(index))

    assert after["citation_verified"] == live["citation_verified"] >= 1
    assert before["citation_verified"] == 0
    # the info loss was silent: every other key still looked right
    assert before["total"] == after["total"]
    assert before["with_valid_evidence"] == after["with_valid_evidence"]
    assert before["supported"] == after["supported"]
    assert before["backed_count"] == after["backed_count"]


# --- 4. backward compatibility ----------------------------------------------


def test_row_level_audit_is_self_contained() -> None:
    """The point of the fix: the row alone must be enough.

    Requires no ``claim_audit`` join, no side channel — an offline reader that
    only looks at ``findings[]`` still gets the real verdict.
    """
    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    index = {record.evidence_id: record for record in records}

    rows_only = json.loads(json.dumps(payload))
    rows_only["claim_audit"] = []

    counts = reconstruct(rows_only, set(index))
    assert counts["citation_verified"] == live["citation_verified"]
    assert counts["citation_verified"] >= 1
    for key in COUNT_KEYS:
        assert counts[key] == live[key], key


def test_legacy_rows_without_support_audit_recover_via_claim_audit() -> None:
    """Pre-v0.6.2 rows still resolve because claim_audit always carried them."""
    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    index = {record.evidence_id: record for record in records}

    legacy = json.loads(json.dumps(payload))
    for row in legacy["findings"]:
        row.pop("support_audit", None)

    recovered = reconstruct(legacy, set(index))
    assert recovered["citation_verified"] == live["citation_verified"]


def test_rows_without_any_audit_trail_stay_unverified_never_verified() -> None:
    """Missing data is reported as missing — never promoted to a pass."""
    row = {"finding_id": "f_old", "support_audit": {"available": False}}
    assert restore_finding_audit(row, []) == {}
    assert restore_finding_audit({"finding_id": "f_old"}, []) == {}

    records = mixed_records()
    live, payload = persist_and_reload(mixed_findings(records), records)
    stripped = json.loads(json.dumps(payload))
    for row in stripped["findings"]:
        row.pop("support_audit", None)
    stripped["claim_audit"] = []

    counts = reconstruct(stripped, {record.evidence_id for record in records})
    assert counts["citation_verified"] == 0
    # no invention: the source-binding keys are untouched by the audit loss
    assert counts["supported"] == live["supported"]
    assert counts["total"] == live["total"]


def test_unavailable_bundle_still_returns_the_documented_shape() -> None:
    session = SimpleNamespace(
        run_id="r",
        task="t",
        status="success",
        started_at=1.0,
        finished_at=2.0,
        error=None,
        plan=None,
        agent_results={},
        artifacts=[],
        final_artifact=None,
        synthesis_bundle=None,
        trace=None,
    )
    syn = collect_metrics(session, scenario_id="A", mode="offline")["synthesis"]
    assert syn["available"] is False
    assert syn["findings"] == []
    assert restore_finding_audit({"finding_id": "x"}, []) == {}
