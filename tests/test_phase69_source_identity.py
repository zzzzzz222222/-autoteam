"""Phase 6.9 (F13) — stable source identity tests.

Every fixture here is built offline from hand-written URL/title/type triples.
No provider, tool, or network call is made: this module must never contain
``web_search`` or any HTTP client call (the ``.env`` file in this repository
configures a real search endpoint, so an accidental call would leave the
machine).

The invariants under test (from the Phase 6.8 F13 finding):

* two different sources must never share one source id;
* the same source referenced by several agents must collapse to one identity;
* ``web`` and ``offline_mock`` attributes must never contaminate each other;
* identity, counts and types must not depend on agent arrival order;
* conflicting claims for one identity must be split *and* audited.
"""

from __future__ import annotations

import itertools

from app.runtime.artifacts import AgentArtifact, ArtifactType, Evidence, Source
from app.synthesis.evidence_filter import collect_evidence_records
from app.synthesis.source_identity import (
    derive_source_identity,
    normalize_url,
    source_id_for,
)


def _artifact(
    artifact_id: str,
    agent_id: str,
    sources: list[tuple[str, str, str]],
    claims: list[tuple[str, str, int]] | None = None,
    *,
    with_identity: bool = True,
) -> AgentArtifact:
    """Build an artifact whose evidence points at the given sources.

    ``sources`` items are ``(title, url, source_type)``; ``claims`` items are
    ``(claim, snippet, source_index)``.
    """
    records = []
    for ordinal, (title, url, source_type) in enumerate(sources, start=1):
        if with_identity:
            source_id, basis = derive_source_identity(
                url=url, artifact_id=artifact_id, title=title, ordinal=ordinal
            )
            records.append(
                Source(id=source_id, identity=basis, title=title, url=url, source_type=source_type)
            )
        else:  # legacy fixture: positional ids, no identity field
            records.append(
                Source(id=f"source_{ordinal:03d}", title=title, url=url, source_type=source_type)
            )
    evidence = []
    for claim, snippet, index in claims or []:
        evidence.append(
            Evidence(
                claim=claim,
                evidence=snippet,
                source_id=records[index].id,
                claim_type="source_fact",
            )
        )
    return AgentArtifact(
        artifact_id=artifact_id,
        agent_id=agent_id,
        output_type=ArtifactType.ANALYSIS,
        title=f"{agent_id} deliverable",
        metadata={"role_name": agent_id},
        source_records=records,
        evidence=evidence,
    )


def _snapshot(artifacts: list[AgentArtifact]) -> dict:
    """Order-independent summary of the source layer (for permutation checks)."""
    evidence, sources = collect_evidence_records(artifacts)
    return {
        "ids": sorted(s.source_id for s in sources),
        "types": sorted((s.source_id, s.source_type) for s in sources),
        "urls": sorted((s.source_id, s.url) for s in sources),
        "agents": sorted((s.source_id, tuple(s.producer_agents)) for s in sources),
        "count": len(sources),
        "independent": len({e.source_id for e in evidence if e.source_id}),
    }


# ---------------------------------------------------------------------------
# 1. the historical F13 failure: same local id, different real sources
# ---------------------------------------------------------------------------


def test_same_local_source_001_with_different_urls_is_not_merged() -> None:
    a = _artifact("art_a", "agent_a", [("A page", "https://a.example/1", "web")],
                  [("a claim", "a snippet", 0)], with_identity=False)
    b = _artifact("art_b", "agent_b", [("B page", "https://b.example/2", "web")],
                  [("b claim", "b snippet", 0)], with_identity=False)
    evidence, sources = collect_evidence_records([a, b])
    assert len(sources) == 2  # was 1 before the fix (id collision)
    assert {s.url for s in sources} == {"https://a.example/1", "https://b.example/2"}
    assert all(s.source_type == "web" for s in sources)
    # each claim keeps its own source, with its own URL
    by_claim = {e.claim: e for e in evidence}
    assert by_claim["a claim"].source_url == "https://a.example/1"
    assert by_claim["b claim"].source_url == "https://b.example/2"


def test_real_web_source_never_loses_url_to_a_mock_record() -> None:
    """The exact Phase 6.8 symptom: web evidence mislabelled offline_mock."""
    mock = _artifact("artifact_competitor_analyst", "competitor_analyst",
                     [("[offline_mock] stub", "", "offline_mock")],
                     [("stub claim", "offline deterministic stub about x", 0)])
    web = _artifact("artifact_requirement_analyst", "requirement_analyst",
                    [("Real page", "https://real.example/market", "web")],
                    [("market claim", "The market was valued at USD 3.7 billion", 0)])
    for order in ([mock, web], [web, mock]):
        evidence, sources = collect_evidence_records(order)
        web_sources = [s for s in sources if s.source_type == "web"]
        mock_sources = [s for s in sources if s.source_type == "offline_mock"]
        assert len(web_sources) == 1 and len(mock_sources) == 1
        assert web_sources[0].url == "https://real.example/market"
        assert mock_sources[0].url == ""
        web_evidence = [e for e in evidence if e.claim == "market claim"][0]
        assert web_evidence.source_type == "web"
        assert web_evidence.source_url == "https://real.example/market"
        mock_evidence = [e for e in evidence if e.claim == "stub claim"][0]
        assert mock_evidence.source_type == "offline_mock"
        assert mock_evidence.source_url == ""


def test_offline_stub_never_gains_a_url_from_a_web_record() -> None:
    web = _artifact("art_web", "agent_web", [("Page", "https://x.example/1", "web")],
                    [("w", "web snippet", 0)])
    mock = _artifact("art_mock", "agent_mock", [("Stub", "", "offline_mock")],
                     [("m", "stub snippet", 0)])
    evidence, sources = collect_evidence_records([web, mock])
    mock_source = next(s for s in sources if s.source_type == "offline_mock")
    assert mock_source.url == ""  # never adopted the web URL
    assert mock_source.artifact_ids == ["art_mock"]


# ---------------------------------------------------------------------------
# 2. the same real source used by several agents
# ---------------------------------------------------------------------------


def test_same_url_from_two_agents_is_one_source() -> None:
    a = _artifact("art_a", "agent_a", [("Page A title", "https://shared.example/x", "web")],
                  [("a claim", "snippet a", 0)])
    b = _artifact("art_b", "agent_b", [("Page B title", "https://shared.example/x", "web")],
                  [("b claim", "snippet b", 0)])
    evidence, sources = collect_evidence_records([a, b])
    assert len(sources) == 1
    source = sources[0]
    assert source.producer_agents == ["agent_a", "agent_b"]
    assert source.artifact_ids == ["art_a", "art_b"]
    assert len({e.source_id for e in evidence}) == 1  # one independent source, not two


def test_same_url_with_different_titles_keeps_both_titles() -> None:
    a = _artifact("art_a", "agent_a", [("Alpha title", "https://s.example/p", "web")], [])
    b = _artifact("art_b", "agent_b", [("Beta title", "https://s.example/p", "web")], [])
    _, sources = collect_evidence_records([a, b])
    assert len(sources) == 1
    assert sources[0].title in {"Alpha title", "Beta title"}
    assert sources[0].alt_titles  # the other title is preserved, not dropped


def test_www_and_case_differences_are_normalised_but_path_is_not() -> None:
    assert normalize_url("HTTPS://Example.COM/a") == "https://example.com/a"
    assert normalize_url("https://example.com:443/a") == "https://example.com/a"
    assert normalize_url("https://example.com/a?x=1#frag") == "https://example.com/a?x=1#frag"
    # different query strings are different resources
    assert normalize_url("https://e.com/a?x=1") != normalize_url("https://e.com/a?x=2")


def test_url_normalisation_unifies_scheme_and_host_case() -> None:
    a = _artifact("art_a", "agent_a", [("t", "HTTPS://Shared.Example/X", "web")], [])
    b = _artifact("art_b", "agent_b", [("t", "https://shared.example/X", "web")], [])
    _, sources = collect_evidence_records([a, b])
    assert len(sources) == 1


def test_missing_url_sources_stay_separate_per_artifact() -> None:
    a = _artifact("art_a", "agent_a", [("Stub A", "", "offline_mock")], [])
    b = _artifact("art_b", "agent_b", [("Stub B", "", "offline_mock")], [])
    _, sources = collect_evidence_records([a, b])
    assert len(sources) == 2  # never merged: no evidence they are the same source


def test_malformed_and_non_http_urls_are_handled_conservatively() -> None:
    src = [("javascript", "javascript:alert(1)", "web"), ("empty", "", "offline_mock"),
           ("nocase", "HTTPS://E.example/P", "web")]
    art = _artifact("art_x", "agent_x", src, [])
    _, sources = collect_evidence_records([art])
    assert len(sources) == 3
    bad = next(s for s in sources if s.title == "javascript")
    assert bad.url == ""  # rejected defensively, and the caller's record is untouched
    assert bad.source_type == "web"  # type is preserved, never guessed


def test_caller_artifact_records_are_not_mutated() -> None:
    art = _artifact("art_x", "agent_x", [("bad", "javascript:alert(1)", "web")], [])
    before = art.source_records[0].url
    collect_evidence_records([art])
    assert art.source_records[0].url == before  # no side effects on the input


# ---------------------------------------------------------------------------
# 3. order / permutation independence
# ---------------------------------------------------------------------------


def test_source_layer_is_permutation_invariant() -> None:
    artifacts = [
        _artifact("art_a", "agent_a", [("A", "https://a.example/1", "web")],
                  [("a claim", "2026年市场达449亿元", 0)]),
        _artifact("art_b", "agent_b", [("B", "https://b.example/2", "web")],
                  [("b claim", "另一条陈述", 0)]),
        _artifact("art_c", "agent_c", [("Stub C", "", "offline_mock")],
                  [("c claim", "stub text", 0)]),
    ]
    snapshots = [_snapshot(list(order)) for order in itertools.permutations(artifacts)]
    assert all(snap == snapshots[0] for snap in snapshots)
    assert snapshots[0]["count"] == 3
    assert snapshots[0]["independent"] == 3


def test_identity_is_stable_across_repeated_runs_and_retries() -> None:
    art = _artifact("art_a", "agent_a", [("A", "https://a.example/1", "web")],
                    [("a claim", "snippet", 0)])
    first = {s.source_id for s in collect_evidence_records([art])[1]}
    again = {s.source_id for s in collect_evidence_records([art])[1]}
    assert first == again  # deterministic, not random


def test_retry_duplicate_results_deduplicate_to_one_source() -> None:
    """A retried agent returns the same source again - it must not be counted twice."""
    art = _artifact(
        "art_a",
        "agent_a",
        [("A", "https://a.example/1", "web"), ("A again", "https://a.example/1", "web")],
        [],
    )
    _, sources = collect_evidence_records([art])
    assert len(sources) == 1


def test_derive_source_identity_is_pure_function_of_content() -> None:
    one = derive_source_identity(
        url="https://a.example/1", artifact_id="art_a", title="t", ordinal=1
    )
    two = derive_source_identity(
        url="https://a.example/1", artifact_id="art_z", title="other", ordinal=9
    )
    assert one[0] == two[0]  # same URL -> same identity regardless of artifact/ordinal
    assert one[1] == two[1]
    assert source_id_for(one[1]) == one[0]


# ---------------------------------------------------------------------------
# 4. conflicts are split and audited (never overwritten)
# ---------------------------------------------------------------------------


def test_conflicting_source_types_for_one_url_are_split_and_audited() -> None:
    web = _artifact("art_web", "agent_web", [("E", "https://same.example/p", "web")],
                    [("e claim", "e snippet", 0)])
    mock = _artifact(
        "art_mock",
        "agent_mock",
        [("F", "https://same.example/p", "offline_mock")],
        [("f claim", "f snippet", 0)],
    )
    conflicts: list[dict] = []
    evidence, sources = collect_evidence_records([web, mock], conflicts=conflicts)
    assert len(sources) == 2
    assert len(conflicts) == 1
    assert "conflicting source types" in conflicts[0]["reason"]
    assert {s.source_type for s in sources} == {"web", "offline_mock"}
    # each piece of evidence stays attached to its own type (no contamination)
    by_claim = {e.claim: e for e in evidence}
    assert by_claim["e claim"].source_type == "web"
    assert by_claim["f claim"].source_type == "offline_mock"


def test_conflict_resolution_is_order_independent() -> None:
    web = _artifact("art_web", "agent_web", [("E", "https://same.example/p", "web")], [])
    mock = _artifact(
        "art_mock", "agent_mock", [("F", "https://same.example/p", "offline_mock")], []
    )
    left = _snapshot([web, mock])
    right = _snapshot([mock, web])
    assert left["count"] == right["count"] == 2
    assert left["types"] == right["types"]  # which source keeps the base id is stable


def test_no_conflict_when_identity_and_type_agree() -> None:
    a = _artifact("art_a", "agent_a", [("A", "https://a.example/1", "web")], [])
    b = _artifact("art_b", "agent_b", [("A2", "https://a.example/1", "web")], [])
    conflicts: list[dict] = []
    _, sources = collect_evidence_records([a, b], conflicts=conflicts)
    assert len(sources) == 1 and conflicts == []


def test_conflicts_out_param_is_optional_and_backward_compatible() -> None:
    a = _artifact("art_a", "agent_a", [("A", "https://a.example/1", "web")], [])
    evidence, sources = collect_evidence_records([a])  # no out-param
    assert isinstance(evidence, list) and isinstance(sources, list)


# ---------------------------------------------------------------------------
# 5. downstream counts and audit semantics
# ---------------------------------------------------------------------------


def test_source_count_and_independent_count_use_identity_not_agents() -> None:
    a = _artifact("art_a", "agent_a", [("S", "https://shared.example/1", "web")],
                  [("c1", "text one", 0)])
    b = _artifact("art_b", "agent_b", [("S", "https://shared.example/1", "web")],
                  [("c2", "text two", 0)])
    evidence, sources = collect_evidence_records([a, b])
    assert len(sources) == 1  # not 2 agents -> 2 sources
    assert len({e.source_id for e in evidence}) == 1


def test_two_real_sources_stay_two_sources() -> None:
    a = _artifact("art_a", "agent_a", [("A", "https://a.example/1", "web")], [("c1", "t1", 0)])
    b = _artifact("art_b", "agent_b", [("B", "https://b.example/2", "web")], [("c2", "t2", 0)])
    evidence, sources = collect_evidence_records([a, b])
    assert len(sources) == 2
    assert len({e.source_id for e in evidence}) == 2


def test_access_failure_is_preserved_when_records_merge() -> None:
    good = _artifact("art_a", "agent_a", [("S", "https://s.example/p", "web")], [("c1", "t1", 0)])
    bad = _artifact("art_b", "agent_b", [("S", "https://s.example/p", "web")], [("c2", "t2", 0)])
    bad.source_records[0].access_status = "http_403"
    bad.source_records[0].access_note = "forbidden"
    evidence, sources = collect_evidence_records([good, bad])
    assert len(sources) == 1
    assert sources[0].access_status == "http_403"  # a failure is never hidden
    assert sources[0].access_note == "forbidden"
    # knowledge of the failure flows into the evidence review status
    assert all(e.review_status == "source_unavailable" for e in evidence)


def test_producer_agents_and_artifacts_are_unioned_and_sorted() -> None:
    a = _artifact("art_a", "agent_z", [("S", "https://s.example/p", "web")], [])
    b = _artifact("art_b", "agent_a", [("S", "https://s.example/p", "web")], [])
    _, sources = collect_evidence_records([a, b])
    assert sources[0].producer_agents == ["agent_a", "agent_z"]
    assert sources[0].artifact_ids == ["art_a", "art_b"]


def test_first_seen_agent_is_informational_only() -> None:
    a = _artifact("art_a", "agent_a", [("S", "https://s.example/p", "web")], [])
    b = _artifact("art_b", "agent_b", [("S", "https://s.example/p", "web")], [])
    forward = collect_evidence_records([a, b])[1][0]
    backward = collect_evidence_records([b, a])[1][0]
    # order-dependent field, explicitly excluded from identity/counts
    assert forward.first_seen_agent in {"agent_a", "agent_b"}
    assert forward.source_id == backward.source_id
    assert forward.producer_agents == backward.producer_agents


def test_serialisation_roundtrip_keeps_identity() -> None:
    from app.synthesis.models import SourceRecord

    art = _artifact("art_a", "agent_a", [("S", "https://s.example/p", "web")], [])
    _, sources = collect_evidence_records([art])
    dumped = sources[0].model_dump()
    restored = SourceRecord.model_validate(dumped)
    assert restored.source_id == sources[0].source_id
    assert restored.identity == sources[0].identity
    assert restored.url == "https://s.example/p"


def test_legacy_records_without_identity_still_load_and_identify() -> None:
    """Old data (positional ids, no identity field) must keep working."""
    legacy = _artifact("art_legacy", "agent_legacy",
                       [("Old", "https://old.example/a", "web")], [("old claim", "old snippet", 0)],
                       with_identity=False)
    evidence, sources = collect_evidence_records([legacy])
    assert len(sources) == 1
    assert sources[0].url == "https://old.example/a"
    assert sources[0].identity == "web:https://old.example/a"
    assert evidence[0].source_id == sources[0].source_id


def test_report_bundle_exposes_source_conflicts_field() -> None:
    from app.synthesis.models import ReportBundle

    bundle = ReportBundle(task="t", source_conflicts=[{"reason": "x"}])
    assert bundle.model_dump()["source_conflicts"] == [{"reason": "x"}]


# ---------------------------------------------------------------------------
# 6. invalid references must never be rendered as valid (acceptance 12.8)
# ---------------------------------------------------------------------------


def test_dangling_evidence_source_id_is_flagged_not_rendered_as_valid() -> None:
    from app.synthesis.evidence_filter import validate_report_references
    from app.synthesis.models import EvidenceRecord, Finding, ReportBundle, SynthesisResult

    # an evidence record bound to a source that does not exist in the bundle
    dangling = EvidenceRecord(
        evidence_id="ev_x", claim="c", evidence="snippet", source_id="src_ghost"
    )
    bundle = ReportBundle(
        task="t",
        evidence=[dangling],
        sources=[],  # src_ghost is not registered
        synthesis=SynthesisResult(
            key_findings=[
                Finding(finding_id="f", statement="s", evidence_ids=["ev_x"])
            ]
        ),
    )
    issues = validate_report_references(bundle)
    assert any("src_ghost" in issue for issue in issues)  # flagged, not silently kept


def test_unresolvable_evidence_id_is_dropped_from_the_finding() -> None:
    from app.synthesis.models import EvidenceRecord, Finding, SynthesisResult
    from app.synthesis.synthesizer import validate_synthesis

    evidence = [EvidenceRecord(evidence_id="ev_1", claim="c", evidence="s", source_id="") ]
    cleaned = validate_synthesis(
        SynthesisResult(
            key_findings=[Finding(finding_id="f", statement="s", evidence_ids=["ev_ghost"])]
        ),
        evidence,
    )
    assert cleaned.key_findings == []  # a fabricated citation can never be rendered


def test_contradiction_with_invalid_source_ids_is_dropped_and_noted() -> None:
    from app.synthesis.models import Contradiction, EvidenceRecord, SynthesisResult
    from app.synthesis.synthesizer import validate_synthesis

    evidence = [
        EvidenceRecord(evidence_id="ev_1", claim="c", evidence="s", source_id="src_real")
    ]
    cleaned = validate_synthesis(
        SynthesisResult(
            contradictions=[
                Contradiction(
                    contradiction_id="con_1",
                    claim_a="A",
                    claim_b="B",
                    evidence_ids=["ev_1"],
                    source_ids=["src_real", "src_FABRICATED"],
                )
            ]
        ),
        evidence,
    )
    kept = cleaned.contradictions[0]
    assert kept.source_ids == ["src_real"]  # valid one kept
    assert "src_FABRICATED" in kept.resolution  # invalid one audited, not rendered


def test_contradiction_source_ids_all_resolve_for_valid_input() -> None:
    from app.synthesis.models import Contradiction, EvidenceRecord, SynthesisResult
    from app.synthesis.synthesizer import validate_synthesis

    evidence = [
        EvidenceRecord(evidence_id="ev_1", claim="c", evidence="s", source_id="src_a"),
        EvidenceRecord(evidence_id="ev_2", claim="c2", evidence="s2", source_id="src_b"),
    ]
    cleaned = validate_synthesis(
        SynthesisResult(
            contradictions=[
                Contradiction(
                    contradiction_id="con_1",
                    claim_a="A",
                    claim_b="B",
                    evidence_ids=["ev_1", "ev_2"],
                    source_ids=["src_a", "src_b"],
                )
            ]
        ),
        evidence,
    )
    assert cleaned.contradictions[0].source_ids == ["src_a", "src_b"]
    assert "dropped unresolved" not in cleaned.contradictions[0].resolution
