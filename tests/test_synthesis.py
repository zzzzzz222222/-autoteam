"""v0.6.0 Agent Team Synthesis tests.

Focus is on structure and provenance — not on whether mock prose "reads well":
evidence must be traceable, ids must be stable, invalid references must be
dropped, and synthesis failure must degrade instead of failing the run.
"""

from __future__ import annotations

from app.llm.provider import MockLLMProvider
from app.runtime.artifacts import (
    AgentArtifact,
    ArtifactType,
    Evidence,
    Source,
)
from app.runtime.session import execute_task
from app.synthesis.assembler import assemble_from_bundle
from app.synthesis.evidence_filter import (
    collect_evidence_records,
    validate_evidence_references,
)
from app.synthesis.models import (
    Finding,
    Insight,
    Recommendation,
    SynthesisResult,
    Tradeoff,
    Uncertainty,
)
from app.synthesis.pipeline import run_synthesis_pipeline
from app.synthesis.synthesizer import (
    SynthesisError,
    run_synthesis,
    validate_synthesis,
)


def _artifact(
    agent_id: str,
    *,
    artifact_id: str | None = None,
    claims: list[tuple[str, str, str]] | None = None,
) -> AgentArtifact:
    """claims = [(claim, evidence_text, source_id)]"""
    artifact_id = artifact_id or f"artifact_{agent_id}"
    source_records = [
        Source(
            id=f"src_{agent_id}_1",
            title=f"Source for {agent_id}",
            url=f"https://example.test/{agent_id}",
            source_type="web",
        )
    ]
    evidence = [
        Evidence(claim=claim, evidence=text, source_id=source_id)
        for claim, text, source_id in (claims or [])
    ]
    return AgentArtifact(
        artifact_id=artifact_id,
        agent_id=agent_id,
        output_type=ArtifactType.ANALYSIS,
        title=f"{agent_id} findings",
        content=f"**{agent_id} summary**\n\n- point one\n- point two",
        structured_data={"note": "value"},
        sources=[f"src_{agent_id}_1"],
        source_records=source_records,
        evidence=evidence,
        metadata={"role_name": agent_id.replace("_", " ").title()},
    )


# ---------------------------------------------------------------------------
# Evidence filtering
# ---------------------------------------------------------------------------


def test_evidence_collection_and_provenance():
    artifacts = [
        _artifact(
            "market_researcher",
            claims=[("Market grows fast", "snippet A", "src_market_researcher_1")],
        ),
        _artifact(
            "tech_analyst",
            claims=[("Frameworks rising", "snippet B", "src_tech_analyst_1")],
        ),
    ]
    evidence, sources = collect_evidence_records(artifacts)

    assert evidence and sources
    for item in evidence:
        assert item.evidence_id
        assert item.producer_agent
        assert item.artifact_id
        assert item.source_id
    producers = {item.producer_agent for item in evidence}
    assert "market_researcher" in producers or "Market Researcher" in producers
    # URL preserved, never fabricated
    for source in sources:
        assert source.url.startswith("https://")
        assert source.source_type == "web"


def test_evidence_deduplication_merges_claims():
    artifacts = [
        _artifact(
            "agent_a",
            claims=[
                ("Same claim about cost", "s1", "src_agent_a_1"),
                ("Same claim about cost", "s1 dup", "src_agent_a_1"),
            ],
        )
    ]
    evidence, _ = collect_evidence_records(artifacts)
    cost_items = [item for item in evidence if "Same claim about cost" in item.claim]
    assert len(cost_items) == 1


def test_source_deduplication_by_url():
    artifact_a = _artifact("agent_a", claims=[("claim a", "e", "src_agent_a_1")])
    artifact_b = _artifact("agent_b", claims=[("claim b", "e", "src_agent_b_1")])
    # force the same URL on both sources
    artifact_a.source_records[0].url = "https://example.test/shared"
    artifact_b.source_records[0].url = "https://example.test/shared"
    evidence, sources = collect_evidence_records([artifact_a, artifact_b])

    urls = [item.url for item in sources if item.url]
    assert urls.count("https://example.test/shared") == 1
    assert all(item.source_id for item in evidence)


def test_structured_data_parse_does_not_drop_content():
    artifact = _artifact("agent_a", claims=[("keep me", "e", "src_agent_a_1")])
    artifact.structured_data = {
        "broken": "{not json",
        "ok": '{"k": 1}',
    }
    evidence, sources = collect_evidence_records([artifact])
    assert evidence
    assert sources
    assert artifact.structured_data["broken"] == "{not json"


def test_invalid_evidence_reference_is_reported():
    valid, invalid = validate_evidence_references(
        ["ev_1", "ev_missing", "ev_1", ""], {"ev_1"}
    )
    assert valid == ["ev_1"]
    assert invalid == ["ev_missing"]


# ---------------------------------------------------------------------------
# Synthesis validation
# ---------------------------------------------------------------------------


def test_synthesis_drops_invalid_evidence_references():
    # build a tiny evidence list
    artifacts = [_artifact("agent_a", claims=[("real claim", "e", "src_agent_a_1")])]
    evidence, _ = collect_evidence_records(artifacts)
    assert evidence
    real_id = evidence[0].evidence_id

    proposed = SynthesisResult(
        key_findings=[
            Finding(
                finding_id="f1",
                statement="ok",
                evidence_ids=[real_id],
                supporting_agents=["agent_a"],
            ),
            Finding(
                finding_id="f2",
                statement="bad",
                evidence_ids=["ev_does_not_exist"],
                supporting_agents=["agent_a"],
            ),
        ],
        cross_agent_insights=[
            Insight(
                insight_id="i1",
                statement="good insight",
                supporting_evidence_ids=[real_id],
            ),
            Insight(
                insight_id="i2",
                statement="bad insight",
                supporting_evidence_ids=["ev_nope"],
            ),
        ],
        recommendations=[
            Recommendation(
                recommendation_id="r1",
                statement="unsupported idea",
                supporting_evidence_ids=["ev_nope"],
            )
        ],
    )
    cleaned = validate_synthesis(proposed, evidence)

    assert {item.finding_id for item in cleaned.key_findings} == {"f1"}
    assert {item.insight_id for item in cleaned.cross_agent_insights} == {"i1"}
    assert cleaned.recommendations
    # no usable evidence -> status is downgraded, never fake-supported
    assert cleaned.recommendations[0].status in {"potential", "unsupported"}
    assert cleaned.recommendations[0].supporting_evidence_ids == []


def test_recommendation_status_reflects_support():
    artifacts = [_artifact("agent_a", claims=[("claim", "e", "src_agent_a_1")])]
    evidence, _ = collect_evidence_records(artifacts)
    real_id = evidence[0].evidence_id

    proposed = SynthesisResult(
        recommendations=[
            Recommendation(
                recommendation_id="r_ok",
                statement="has evidence",
                supporting_evidence_ids=[real_id],
            ),
            Recommendation(
                recommendation_id="r_potential",
                statement="insight only",
                supporting_insight_ids=["ins_x"],
            ),
            Recommendation(
                recommendation_id="r_none",
                statement="nothing",
            ),
        ],
        cross_agent_insights=[
            Insight(
                insight_id="ins_x",
                statement="insight",
                supporting_evidence_ids=[real_id],
            )
        ],
    )
    cleaned = validate_synthesis(proposed, evidence)
    by_id = {item.recommendation_id: item for item in cleaned.recommendations}
    assert by_id["r_ok"].status == "supported"
    assert by_id["r_ok"].supporting_evidence_ids == [real_id]
    assert by_id["r_potential"].status == "potential"
    assert by_id["r_none"].status == "unsupported"


# ---------------------------------------------------------------------------
# Pipeline / offline end-to-end
# ---------------------------------------------------------------------------


def test_offline_pipeline_produces_structured_bundle():
    artifacts = [
        _artifact(
            "market_researcher",
            claims=[
                ("SME agents need low cost", "cost snippet", "src_market_researcher_1"),
            ],
        ),
        _artifact(
            "tech_analyst",
            claims=[
                ("Knowledge base integration matters", "kb snippet", "src_tech_analyst_1"),
            ],
        ),
    ]
    bundle = run_synthesis_pipeline(
        "design an SME agent product", artifacts, provider=MockLLMProvider()
    )

    assert bundle.status == "completed"
    assert bundle.evidence
    assert bundle.sources
    assert bundle.synthesis.cross_agent_insights
    assert bundle.synthesis.tradeoffs
    assert bundle.synthesis.recommendations
    # every insight cites existing evidence ids
    known = {item.evidence_id for item in bundle.evidence}
    for insight in bundle.synthesis.cross_agent_insights:
        assert insight.supporting_evidence_ids
        assert set(insight.supporting_evidence_ids) <= known
    for rec in bundle.synthesis.recommendations:
        assert rec.status in {"supported", "potential", "unsupported"}
        if rec.status == "supported":
            assert rec.supporting_evidence_ids


def test_pipeline_records_trace_events():
    from app.runtime.events import ExecutionTrace

    artifacts = [
        _artifact("agent_a", claims=[("claim a", "e", "src_agent_a_1")]),
        _artifact("agent_b", claims=[("claim b", "e", "src_agent_b_1")]),
    ]
    trace = ExecutionTrace("run_test")
    bundle = run_synthesis_pipeline(
        "task", artifacts, provider=MockLLMProvider(), trace=trace
    )
    types = [event.type for event in trace.events]
    assert "SYNTHESIS_STARTED" in types
    assert "EVIDENCE_FILTERED" in types
    assert "SYNTHESIS_COMPLETED" in types
    assert bundle.status == "completed"


def test_pipeline_without_artifacts_fails_soft():
    bundle = run_synthesis_pipeline("task", [], provider=MockLLMProvider())
    assert bundle.status == "failed"
    assert bundle.degradation_reason


def test_assembler_builds_v06_sections():
    artifacts = [
        _artifact("agent_a", claims=[("claim a", "e", "src_agent_a_1")]),
    ]
    bundle = run_synthesis_pipeline("task", artifacts, provider=MockLLMProvider())
    final = assemble_from_bundle(
        "task", artifacts, bundle, agent_order=["agent_a"], run_id="run_x"
    )
    titles = [section.title for section in final.sections]
    # Executive Summary is rendered from FinalArtifact.summary (not a section)
    assert "Key Findings" in titles
    # mock synthesis always emits these
    assert "Cross-Agent Insights" in titles
    assert "Trade-offs" in titles
    assert "Recommendations" in titles
    # provenance survives into the final artifact
    assert final.evidence
    assert all(item.source_id for item in final.evidence)
    assert final.source_records
    markdown = final.to_markdown()
    assert "## Executive Summary" in markdown
    assert "## Recommendations" in markdown


def test_synthesis_error_when_provider_breaks():
    class BrokenProvider:
        def structured_completion(self, prompt, response_model):
            raise ValueError("LLM provider call failed: JSONDecodeError")

    artifacts = [_artifact("agent_a", claims=[("c", "e", "src_agent_a_1")])]
    try:
        evidence, sources = collect_evidence_records(artifacts)
        run_synthesis("task", artifacts, evidence, sources, provider=BrokenProvider())
    except SynthesisError as exc:
        assert "Structured output" in str(exc) or "Invalid structured" in str(exc)
    else:
        raise AssertionError("expected SynthesisError")


def test_pipeline_degrades_when_synthesis_fails():
    class BrokenProvider:
        def structured_completion(self, prompt, response_model):
            raise ValueError("boom")

    artifacts = [_artifact("agent_a", claims=[("c", "e", "src_agent_a_1")])]
    bundle = run_synthesis_pipeline("task", artifacts, provider=BrokenProvider())
    # pipeline itself never raises — session can still assemble a report
    assert bundle.status == "degraded"
    assert bundle.degradation_reason
    assert bundle.synthesis.uncertainties
    final = assemble_from_bundle("task", artifacts, bundle, ["agent_a"])
    assert final.to_markdown()
    assert final.metadata.get("synthesis_status") == "degraded"


# ---------------------------------------------------------------------------
# Session integration (offline, full run)
# ---------------------------------------------------------------------------


def test_execute_task_offline_includes_synthesis_sections():
    session = execute_task("analyze the market and design a product plan")
    assert session.final_artifact is not None
    titles = [section.title for section in session.final_artifact.sections]
    assert "Key Findings" in titles
    assert "Cross-Agent Insights" in titles
    assert "Trade-offs" in titles
    assert "Recommendations" in titles
    markdown = session.final_artifact.to_markdown()
    assert "## Executive Summary" in markdown
    assert "## Recommendations" in markdown
    # synthesis provenance fields are populated offline too
    assert session.final_artifact.evidence
    for item in session.final_artifact.evidence:
        assert item.source_id
    event_types = [event.type for event in session.trace.events]
    assert "SYNTHESIS_STARTED" in event_types
    assert "SYNTHESIS_COMPLETED" in event_types or "SYNTHESIS_FAILED" in event_types


def test_execute_task_offline_recommendations_traceable():
    session = execute_task("design an SME AI agent product")
    assert session.final_artifact is not None
    bundle = getattr(session, "synthesis_bundle", None)
    assert bundle is not None
    known = {item.evidence_id for item in bundle.evidence}
    for rec in bundle.synthesis.recommendations:
        if rec.status == "supported":
            assert set(rec.supporting_evidence_ids) <= known
            assert rec.supporting_evidence_ids
    for insight in bundle.synthesis.cross_agent_insights:
        assert set(insight.supporting_evidence_ids) <= known


def test_tradoff_model_shape():
    item = Tradeoff(
        tradeoff_id="t1",
        dimension="cost vs capability",
        option_a="cheap",
        option_b="capable",
        gains_a=["low cost"],
        costs_a=["fewer features"],
        gains_b=["more features"],
        costs_b=["higher cost"],
        evidence_ids=["ev_1"],
        implications=["SME prefers A"],
    )
    assert item.dimension
    assert item.gains_a and item.costs_b
    unc = Uncertainty(uncertainty_id="u1", statement="thin", kind="insufficient_evidence")
    assert unc.kind == "insufficient_evidence"
