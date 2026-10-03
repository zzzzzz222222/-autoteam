"""Regression tests for the Phase-5 NEEDS_REWORK fixes.

Covers deterministic claim→source binding, honest provenance statuses, finding
de-duplication, item-level synthesis persistence, and the report rendering
guards. Fully offline: no provider, no network, no paid API.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.runtime.agent_runtime import match_claim_to_snippet, relevance_score
from app.runtime.artifacts import (
    AgentArtifact,
    ArtifactType,
)
from app.runtime.artifacts import (
    Evidence as RuntimeEvidence,
)
from app.runtime.artifacts import (
    Source as RuntimeSource,
)
from app.synthesis.assembler import assemble_from_bundle
from app.synthesis.evidence_filter import (
    collect_evidence_records,
    validate_evidence_references,
    validate_report_references,
)
from app.synthesis.models import (
    Contradiction,
    EvidenceRecord,
    Finding,
    Insight,
    Recommendation,
    ReportBundle,
    SourceRecord,
    SynthesisResult,
    Tradeoff,
    Uncertainty,
)
from app.synthesis.synthesizer import (
    statement_similarity,
    validate_synthesis,
)
from validation.collect import collect_metrics

# ---------------------------------------------------------------------------
# fixtures / builders
# ---------------------------------------------------------------------------

CLAIM_WITH_NUMBERS = (
    "市场规模与增速：2025年中国企业级AI Agent投资55.9亿元，"
    "2030年预计达815.1亿元，CAGR 70.9%"
)
RELATED_SNIPPET = "中国企业级AI Agent投资2025年为55.9亿元，2030年预计815.1亿元，CAGR 70.9%。"
UNRELATED_SNIPPET = "Upwork surveyed 750 U.S. business leaders about AI agent adoption in Q1 2026."


def _runtime_artifact(
    agent_id: str,
    *,
    sources: list[tuple[str, str, str]],
    claims: list[tuple[str, str, str]],
    output_type: ArtifactType = ArtifactType.ANALYSIS,
) -> AgentArtifact:
    return AgentArtifact(
        artifact_id=f"artifact_{agent_id}",
        agent_id=agent_id,
        output_type=output_type,
        title=f"{agent_id} output",
        content="body content for the artifact",
        metadata={"role_name": agent_id.replace("_", " ").title()},
        source_records=[
            RuntimeSource(id=sid, title=f"title {sid}", url=url, source_type="web")
            for sid, url, _ in [(s[0], s[1], s[2]) for s in sources]
        ],
        evidence=[
            RuntimeEvidence(claim=claim, evidence=text, source_id=sid)
            for claim, text, sid in claims
        ],
    )


def _evidence_pair() -> tuple[list[EvidenceRecord], list[SourceRecord]]:
    """Two agents, two different sources, one claim each."""
    artifacts = [
        _runtime_artifact(
            "agent_a",
            sources=[("src_a", "https://a.example/x", "snippet a55.9")],
            claims=[("claim a about 55.9", "snippet a55.9", "src_a")],
        ),
        _runtime_artifact(
            "agent_b",
            sources=[("src_b", "https://b.example/y", "snippet b83.7")],
            claims=[("claim b about 83.7", "snippet b83.7", "src_b")],
        ),
    ]
    return collect_evidence_records(artifacts)


def _default_evidence() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            evidence_id="ev_1",
            claim="claim one",
            evidence="snippet one",
            source_id="source_001",
            source_title="Source One",
            source_url="https://one.example/a",
            source_type="web",
            producer_agent="agent_a",
            artifact_id="artifact_agent_a",
            review_status="not_checked",
        ),
        EvidenceRecord(
            evidence_id="ev_2",
            claim="claim two",
            evidence="snippet two",
            source_id="source_002",
            source_title="Source Two",
            source_url="https://two.example/b",
            source_type="web",
            producer_agent="agent_b",
            artifact_id="artifact_agent_b",
            review_status="not_checked",
        ),
    ]


def _bundle(
    *,
    findings: list[Finding] | None = None,
    insights: list[Insight] | None = None,
    contradictions: list[Contradiction] | None = None,
    uncertainties: list[Uncertainty] | None = None,
    tradeoffs: list[Tradeoff] | None = None,
    recommendations: list[Recommendation] | None = None,
    evidence: list[EvidenceRecord] | None = None,
) -> tuple[ReportBundle, list[EvidenceRecord]]:
    if evidence is None:
        evidence = _default_evidence()
    sources = [
        SourceRecord(
            source_id=item.source_id,
            title=item.source_title,
            url=item.source_url,
            source_type="web",
        )
        for item in evidence
    ]
    bundle = ReportBundle(
        task="t",
        synthesis=SynthesisResult(
            key_findings=findings or [],
            cross_agent_insights=insights or [],
            contradictions=contradictions or [],
            uncertainties=uncertainties or [],
            tradeoffs=tradeoffs or [],
            recommendations=recommendations or [],
            summary="summary text",
        ),
        evidence=evidence,
        sources=sources,
        artifact_ids=["artifact_agent_a", "artifact_agent_b"],
        status="completed",
    )
    return bundle, evidence


# ---------------------------------------------------------------------------
# 1/2. deterministic claim -> source binding (no round-robin)
# ---------------------------------------------------------------------------


def test_matcher_binds_claim_to_the_supporting_snippet_not_position() -> None:
    candidates = [("src_unrelated", UNRELATED_SNIPPET), ("src_related", RELATED_SNIPPET)]
    index, score, numeric, lexical = match_claim_to_snippet(CLAIM_WITH_NUMBERS, candidates)
    assert index == 1  # position 0 is the decoy; order must not decide
    assert score > 0 and numeric >= 0.6
    # reversed order gives the same logical binding
    reversed_index, *_ = match_claim_to_snippet(
        CLAIM_WITH_NUMBERS, list(reversed(candidates))
    )
    assert reversed_index == 0


def test_matcher_leaves_unrelated_claim_unbound() -> None:
    candidates = [("src_a", RELATED_SNIPPET), ("src_b", UNRELATED_SNIPPET)]
    index, score, _numeric, _lexical = match_claim_to_snippet(
        "完全无关的主张，讨论的是别的主题", candidates
    )
    assert index is None
    score, numeric, lexical = relevance_score(CLAIM_WITH_NUMBERS, UNRELATED_SNIPPET)
    assert numeric == 0.0  # numbers decide: none of the claim's numbers appear


def test_unbound_evidence_is_unsupported_and_never_verified() -> None:
    """An unmatched claim must stay unbound instead of borrowing a source."""
    from app.llm.provider import MockLLMProvider
    from app.runtime.agent_runtime import AgentRuntime
    from app.runtime.artifacts import AgentDeliverable
    from app.tools.registry import SearchResult, ToolRegistry, ToolResult

    runtime = AgentRuntime(provider=MockLLMProvider(), tool_registry=ToolRegistry(mode="mock"))
    collected = [
        ToolResult(
            query="q",
            tool="web_search",
            offline=False,
            kind="web",
            results=[UNRELATED_SNIPPET],
            search_results=[
                SearchResult(
                    title="unrelated", url="https://x.example/a", snippet=UNRELATED_SNIPPET
                )
            ],
        )
    ]
    deliverable = AgentDeliverable(
        title="t", summary="s", key_points=[CLAIM_WITH_NUMBERS], sources=[]
    )
    _sources, evidence = runtime._collect_evidence(
        collected, deliverable, agent_id="a", artifact_id="art_a"
    )
    assert evidence
    assert evidence[0].source_id == ""
    assert evidence[0].review_status == "unsupported"
    assert evidence[0].claim_type == "unverified_claim"


def test_bound_evidence_prefers_the_matching_snippet() -> None:
    """The runtime binds the claim to the snippet that actually contains it."""
    from app.llm.provider import MockLLMProvider
    from app.runtime.agent_runtime import AgentRuntime
    from app.runtime.artifacts import AgentDeliverable
    from app.tools.registry import SearchResult, ToolRegistry, ToolResult

    runtime = AgentRuntime(provider=MockLLMProvider(), tool_registry=ToolRegistry(mode="mock"))
    collected = [
        ToolResult(
            query="q",
            tool="web_search",
            offline=False,
            kind="web",
            results=[],
            search_results=[
                SearchResult(title="decoy", url="https://x/a", snippet=UNRELATED_SNIPPET),
                SearchResult(title="real", url="https://x/b", snippet=RELATED_SNIPPET),
            ],
        )
    ]
    deliverable = AgentDeliverable(
        title="t", summary="s", key_points=[CLAIM_WITH_NUMBERS], sources=[]
    )
    sources, evidence = runtime._collect_evidence(
        collected, deliverable, agent_id="a", artifact_id="art_a"
    )
    assert len(sources) == 2
    assert evidence[0].source_id == sources[1].id
    assert evidence[0].review_status == "not_checked"
    assert evidence[0].claim_type == "source_fact"


def test_bound_evidence_is_not_checked_never_verified() -> None:
    """A bound source means 'not checked yet' - never 'verified'."""
    artifact = _runtime_artifact(
        "agent_y",
        sources=[("src_y", "https://y.example/a", "snippet y")],
        claims=[("claim y", "snippet y", "src_y")],
    )
    evidence, sources = collect_evidence_records([artifact])
    assert evidence
    # v0.6.9 (F13): the canonical source id is derived from the source identity
    # (normalised URL), not from the artifact-local label. The invariant under
    # test is unchanged: the evidence is bound to a real source record, and that
    # binding never implies "verified".
    assert sources and sources[0].url == "https://y.example/a"
    assert sources[0].source_type == "web"
    for item in evidence:
        assert item.source_id == sources[0].source_id
        assert item.source_url == "https://y.example/a"
        assert item.review_status == "not_checked"
        assert item.verified is False



    valid, invalid = validate_evidence_references(["ev_1", "ev_missing", "ev_1"], {"ev_1"})
    assert valid == ["ev_1"]
    assert invalid == ["ev_missing"]


def test_report_reference_validator_flags_dangling_ids() -> None:
    finding = Finding(
        finding_id="find_1", statement="s", evidence_ids=["ev_1"], support_kind="single_source"
    )
    bundle, _ = _bundle(findings=[finding])
    assert validate_report_references(bundle) == []

    bad = Finding(
        finding_id="find_2", statement="s2", evidence_ids=["ev_nope"], support_kind="single_source"
    )
    bundle.synthesis.key_findings.append(bad)
    issues = validate_report_references(bundle)
    assert any("ev_nope" in issue for issue in issues)


# ---------------------------------------------------------------------------
# 4/5. support classification honesty
# ---------------------------------------------------------------------------


def test_single_source_finding_cannot_claim_multi_source() -> None:
    evidence, _ = _evidence_pair()
    one = Finding(
        finding_id="f",
        statement="only one source backs this",
        evidence_ids=[evidence[0].evidence_id],
        support_kind="multi_source",  # LLM over-claim
    )
    cleaned = validate_synthesis(SynthesisResult(key_findings=[one]), evidence)
    assert cleaned.key_findings[0].support_kind == "single_source"


def test_finding_without_evidence_is_unsupported() -> None:
    evidence, _ = _evidence_pair()
    none = Finding(finding_id="f", statement="no support", evidence_ids=[])
    cleaned = validate_synthesis(SynthesisResult(key_findings=[none]), evidence)
    assert cleaned.key_findings[0].support_kind == "unsupported"


# ---------------------------------------------------------------------------
# 6/7. finding de-duplication
# ---------------------------------------------------------------------------


def test_duplicate_findings_are_merged_and_keep_all_evidence() -> None:
    evidence, _ = _evidence_pair()
    a = Finding(
        finding_id="find_01",
        statement=CLAIM_WITH_NUMBERS,
        evidence_ids=[evidence[0].evidence_id],
    )
    b = Finding(
        finding_id="sfind_01",
        statement=CLAIM_WITH_NUMBERS + "。",  # same conclusion, listed twice
        evidence_ids=[evidence[1].evidence_id],
    )
    cleaned = validate_synthesis(
        SynthesisResult(key_findings=[a], supported_findings=[b]), evidence
    )
    assert len(cleaned.key_findings) == 1
    merged = cleaned.key_findings[0]
    assert set(merged.evidence_ids) == {evidence[0].evidence_id, evidence[1].evidence_id}
    assert merged.support_kind == "multi_source"  # 2 agents re-derived from the union
    assert "merged_from" in merged.notes
    assert cleaned.supported_findings == [] and cleaned.single_source_findings == []
    audit = json.loads(cleaned.notes.split("dedup: ", 1)[1])
    assert audit["before_total"] == 2 and audit["after"] == 1 and audit["merged_groups"]


def test_similar_but_different_findings_are_not_merged() -> None:
    left = "中小企业市场高速增长，2025年投资55.9亿元"
    right = "中小企业项目失败率高，30%–40%的项目因ROI停滞"
    assert statement_similarity(left, right) < 0.85
    evidence, _ = _evidence_pair()
    cleaned = validate_synthesis(
        SynthesisResult(
            key_findings=[
                Finding(finding_id="f1", statement=left, evidence_ids=[evidence[0].evidence_id]),
                Finding(finding_id="f2", statement=right, evidence_ids=[evidence[1].evidence_id]),
            ]
        ),
        evidence,
    )
    assert len(cleaned.key_findings) == 2


# ---------------------------------------------------------------------------
# 8/9. contradictions and recommendations keep their chains
# ---------------------------------------------------------------------------


def test_contradiction_keeps_both_sides_and_evidence() -> None:
    evidence, _ = _evidence_pair()
    item = Contradiction(
        contradiction_id="con_1",
        claim_a="公有云SaaS足够安全",
        claim_b="部分客户需要私有化部署",
        evidence_ids=[e.evidence_id for e in evidence],
        status="unresolved",
    )
    cleaned = validate_synthesis(SynthesisResult(contradictions=[item]), evidence)
    kept = cleaned.contradictions[0]
    assert kept.claim_a and kept.claim_b  # both sides survive
    assert set(kept.evidence_ids) == {e.evidence_id for e in evidence}
    assert len(kept.agents) == 2  # both producers derived from the cited evidence


def test_recommendation_keeps_refs_status_and_limitations() -> None:
    evidence, _ = _evidence_pair()
    insight = Insight(
        insight_id="ins_1",
        statement="insight",
        supporting_evidence_ids=[e.evidence_id for e in evidence],
    )
    trade = Tradeoff(tradeoff_id="t_1", dimension="d", evidence_ids=[evidence[0].evidence_id])
    rec = Recommendation(
        recommendation_id="rec_1",
        statement="recommendation",
        supporting_insight_ids=["ins_1"],
        supporting_tradeoff_ids=["t_1"],
        supporting_evidence_ids=[evidence[0].evidence_id, "ev_missing"],
        limitations=["no pricing evidence"],
    )
    cleaned = validate_synthesis(
        SynthesisResult(cross_agent_insights=[insight], tradeoffs=[trade], recommendations=[rec]),
        evidence,
    )
    kept = cleaned.recommendations[0]
    assert kept.status == "supported"
    assert kept.limitations == ["no pricing evidence"]
    assert "ev_missing" not in kept.supporting_evidence_ids  # dangling ref dropped
    assert kept.supporting_insight_ids == ["ins_1"]
    assert kept.supporting_tradeoff_ids == ["t_1"]


# ---------------------------------------------------------------------------
# 10. item-level synthesis persistence (reloadable)
# ---------------------------------------------------------------------------


def test_synthesis_items_are_persisted_with_resolvable_ids() -> None:
    evidence, sources = _evidence_pair()
    ids = [e.evidence_id for e in evidence]
    bundle, _ = _bundle(
        evidence=evidence,
        findings=[
            Finding(
                finding_id="find_1", statement="s1", evidence_ids=ids,
                support_kind="multi_source",
            )
        ],
        insights=[Insight(insight_id="ins_1", statement="i1", supporting_evidence_ids=ids)],
        contradictions=[
            Contradiction(contradiction_id="con_1", claim_a="a", claim_b="b", evidence_ids=ids)
        ],
        uncertainties=[Uncertainty(uncertainty_id="u_1", statement="u", evidence_ids=ids)],
        tradeoffs=[Tradeoff(tradeoff_id="t_1", dimension="d", evidence_ids=ids)],
        recommendations=[
            Recommendation(
                recommendation_id="rec_1",
                statement="r",
                supporting_insight_ids=["ins_1"],
                supporting_tradeoff_ids=["t_1"],
                supporting_evidence_ids=ids,
                limitations=["l"],
            )
        ],
    )
    session = SimpleNamespace(
        run_id="run_test",
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
    metrics = collect_metrics(session, scenario_id="A", mode="offline")
    syn = metrics["synthesis"]
    # counts AND items are present
    assert syn["findings"] and syn["findings"][0]["finding_id"] == "find_1"
    assert syn["insights"][0]["insight_id"] == "ins_1"
    assert syn["contradictions"][0]["claim_a"] and syn["contradictions"][0]["claim_b"]
    assert syn["uncertainties"][0]["uncertainty_id"] == "u_1"
    assert syn["tradeoffs"][0]["tradeoff_id"] == "t_1"
    assert syn["recommendations"][0]["recommendation_id"] == "rec_1"
    assert syn["recommendations"][0]["limitations"] == ["l"]
    # round-trips through JSON (reloadable audit artifact)
    reloaded = json.loads(json.dumps(syn, ensure_ascii=False))
    known = {item["evidence_id"] for item in metrics["evidence"]["items"]}
    for item in reloaded["findings"]:
        assert set(item["evidence_ids"]) <= known | known  # every id resolves
    assert metrics["evidence"]["items"][0]["review_status"] in {
        "not_checked",
        "unsupported",
        "verified",
        "partially_supported",
        "source_unavailable",
    }


# ---------------------------------------------------------------------------
# 11/12/13. report rendering guards
# ---------------------------------------------------------------------------


def _render(bundle, artifacts, order):
    final = assemble_from_bundle(
        task="t", artifacts=artifacts, bundle=bundle, agent_order=order, run_id="run_x"
    )
    return final, final.to_markdown()


def test_report_renders_exactly_one_final_report() -> None:
    evidence, _ = _evidence_pair()
    bundle, _ = _bundle(
        findings=[Finding(finding_id="f", statement="s", evidence_ids=[evidence[0].evidence_id])]
    )
    artifacts = [
        _runtime_artifact(
            "proposal_writer",
            sources=[("s1", "https://a.example/1", "x")],
            claims=[("c", "x", "s1")],
            output_type=ArtifactType.PROPOSAL,
        ),
        _runtime_artifact(
            "report_writer",
            sources=[("s2", "https://a.example/2", "y")],
            claims=[("c", "y", "s2")],
            output_type=ArtifactType.REPORT,
        ),
        _runtime_artifact(
            "report_writer_b",
            sources=[("s3", "https://a.example/3", "z")],
            claims=[("c", "z", "s3")],
            output_type=ArtifactType.REPORT,
        ),
    ]
    final, markdown = _render(
        bundle, artifacts, ["proposal_writer", "report_writer", "report_writer_b"]
    )
    report_sections = [s for s in final.sections if s.output_type == "report"]
    assert len(report_sections) == 1  # exactly one canonical final report
    assert markdown.count("Intermediate deliverable (not the final report)") == 1


def test_evidence_section_is_compact_and_keeps_full_text_outside() -> None:
    long_snippet = "证据原文。" * 800  # ~4k chars
    evidence = [
        EvidenceRecord(
            evidence_id="ev_long",
            claim="long claim",
            evidence=long_snippet,
            source_id="source_001",
            source_title="Source",
            source_url="https://one.example/a",
            source_type="web",
            review_status="not_checked",
        )
    ]
    bundle = ReportBundle(
        task="t",
        synthesis=SynthesisResult(key_findings=[], summary="s"),
        evidence=evidence,
        sources=[SourceRecord(source_id="source_001", title="Source", url="https://one.example/a")],
        status="completed",
    )
    final, markdown = _render(bundle, [], [])
    assert long_snippet not in markdown  # the raw dump never enters the body
    assert "…" in markdown
    evidence_line = next(line for line in markdown.splitlines() if "long claim" in line)
    assert len(evidence_line) < 600
    # the full snippet is still available on the artifact for the separate file
    assert final.evidence[0].evidence == long_snippet


def test_report_does_not_dump_raw_json_into_prose() -> None:
    raw_json = '{"categories": [' + ", ".join(f'{{"name": "c{i}"}}' for i in range(120)) + "]}"
    artifact = _runtime_artifact(
        "data_analyst",
        sources=[("s1", "https://a.example/1", "x")],
        claims=[("c", "x", "s1")],
    )
    artifact.structured_data = {"competitor_landscape": raw_json}
    bundle, _ = _bundle()
    _final, markdown = _render(bundle, [artifact], ["data_analyst"])
    assert raw_json not in markdown
    assert "…" in markdown


def test_report_reference_validator_passes_for_a_clean_bundle() -> None:
    evidence, _ = _evidence_pair()
    ids = [e.evidence_id for e in evidence]
    bundle, _ = _bundle(
        evidence=evidence,
        findings=[Finding(finding_id="f", statement="s", evidence_ids=ids)],
        insights=[Insight(insight_id="i", statement="x", supporting_evidence_ids=ids)],
        recommendations=[
            Recommendation(
                recommendation_id="r", statement="y", supporting_insight_ids=["i"],
                supporting_evidence_ids=ids,
            )
        ],
    )
    assert validate_report_references(bundle) == []


# ---------------------------------------------------------------------------
# 14. backward compatibility + read-only Phase 5 regression
# ---------------------------------------------------------------------------

PHASE5_EVIDENCE = Path(
    "validation/runs/20261002T074824Z_A_real/run1_run_98e1d9aa/evidence.json"
)


def test_legacy_evidence_record_json_still_parses_and_is_not_verified() -> None:
    """Old records (no review_status, verified=true) must load and stay honest."""
    legacy = {
        "evidence_id": "ev_old",
        "claim": "old claim",
        "evidence": "old snippet",
        "source_id": "source_001",
        "source_url": "https://one.example/a",
        "source_type": "web",
        "producer_agent": "agent_a",
        "artifact_id": "artifact_agent_a",
        "relevance": "x",
        "claim_type": "",
        "verified": True,  # legacy meaning: "a source id exists"
    }
    record = EvidenceRecord(**legacy)
    assert record.review_status == "not_checked"
    assert record.verified is False  # never auto-promoted to verified


@pytest.mark.skipif(not PHASE5_EVIDENCE.exists(), reason="Phase 5 run artifacts not present")
def test_phase5_artifacts_remain_readable_and_never_claim_verified() -> None:
    """Read-only regression over the real Phase 5 output (nothing is modified)."""
    payload = json.loads(PHASE5_EVIDENCE.read_text(encoding="utf-8"))
    records = [EvidenceRecord(**item) for item in payload["items"]]
    assert len(records) == payload["count"] == 31
    for record in records:
        assert record.verified is False
        assert record.review_status in {
            "not_checked",
            "unsupported",
            "verified",
            "partially_supported",
            "source_unavailable",
        }
        if not record.source_id:
            assert record.review_status == "unsupported"
    # the original file must be untouched by this test
    assert PHASE5_EVIDENCE.exists()
