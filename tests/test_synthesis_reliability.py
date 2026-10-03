"""Offline regression tests for the Phase 6.1 synthesis-reliability fixes.

Covers: tolerant/classified structured parsing, bounded corrective retry under
the LLM budget, auditable fallback, and the upstream claim-quality gate.
Fully offline — no provider, no network, no paid API.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.llm.provider import ProviderError
from app.llm.structured import (
    CATEGORY_EMPTY,
    CATEGORY_INVALID_JSON,
    CATEGORY_NOT_JSON,
    CATEGORY_SCHEMA_MISMATCH,
    CATEGORY_TRUNCATED,
    CATEGORY_WRONG_TYPE,
    StructuredParseError,
    parse_structured,
)
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
from app.synthesis.evidence_filter import collect_evidence_records
from app.synthesis.models import SUPPORT_KINDS, ReportBundle, SynthesisResult
from app.synthesis.pipeline import run_synthesis_pipeline
from app.synthesis.synthesizer import SynthesisError, run_synthesis
from validation.counting_provider import CountingProvider

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Payload(BaseModel):
    name: str = ""
    count: int = 0


def _artifacts() -> list[AgentArtifact]:
    return [
        AgentArtifact(
            artifact_id="artifact_agent_a",
            agent_id="agent_a",
            output_type=ArtifactType.ANALYSIS,
            title="Agent A output",
            content="body a",
            metadata={"role_name": "Agent A"},
            source_records=[
                RuntimeSource(
                    id="src_a", title="Src A", url="https://a.example/x",
                    source_type="web",
                )
            ],
            evidence=[RuntimeEvidence(claim="claim a", evidence="snippet a", source_id="src_a")],
        ),
        AgentArtifact(
            artifact_id="artifact_agent_b",
            agent_id="agent_b",
            output_type=ArtifactType.ANALYSIS,
            title="Agent B output",
            content="body b",
            metadata={"role_name": "Agent B"},
            source_records=[
                RuntimeSource(
                    id="src_b", title="Src B", url="https://b.example/y",
                    source_type="web",
                )
            ],
            evidence=[RuntimeEvidence(claim="claim b", evidence="snippet b", source_id="src_b")],
        ),
    ]


def _valid_synthesis() -> SynthesisResult:
    from app.synthesis.models import Finding

    return SynthesisResult(key_findings=[Finding(finding_id="f1", statement="combined finding")])


class _ScriptedProvider:
    """Returns scripted values/errors and records the prompts it received."""

    model = "scripted"

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0
        self.prompts: list[str] = []

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        self.prompts.append(prompt)
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(prompt, response_model)
        return item


def _parse_error(category: str, message: str = "bad output") -> ProviderError:
    return ProviderError(
        f"structured output invalid [{category}]: {message}",
        category="structured_parse",
        retryable=True,
        diagnostics="len=10 sha=deadbeef brace_delta=1",
    )


# ---------------------------------------------------------------------------
# P0: structured parsing (classic + tolerant + classified failures)
# ---------------------------------------------------------------------------


def test_parse_plain_json() -> None:
    result = parse_structured('{"name": "a", "count": 2}', _Payload)
    assert result.name == "a" and result.count == 2


def test_parse_markdown_fenced_json() -> None:
    content = '```json\n{"name": "a", "count": 2}\n```'
    result = parse_structured(content, _Payload)
    assert result.name == "a"


def test_parse_fenced_json_with_surrounding_prose() -> None:
    content = (
        'Here is the synthesis you asked for:\n'
        '```json\n{"name": "a", "count": 2}\n```\n'
        'Thanks!'
    )
    result = parse_structured(content, _Payload)
    assert result.name == "a"


def test_parse_ignores_unknown_fields() -> None:
    result = parse_structured('{"name": "a", "unexpected": 1}', _Payload)
    assert result.name == "a"


@pytest.mark.parametrize(
    ("content", "category"),
    [
        ("", CATEGORY_EMPTY),
        ("   \n ", CATEGORY_EMPTY),
        ("I could not produce JSON for this task.", CATEGORY_NOT_JSON),
        ('{"name": "a",}', CATEGORY_INVALID_JSON),
        ('{"name": "a", "count": 1', CATEGORY_TRUNCATED),
        ('{"name": "a" "count": 1}', CATEGORY_INVALID_JSON),
        ('["a", "b"]', CATEGORY_WRONG_TYPE),
        ("42", CATEGORY_NOT_JSON),
        ('{"count": "not-an-int"}', CATEGORY_SCHEMA_MISMATCH),
        ("{}", "ok"),
    ],
)
def test_parse_failure_classification(content: str, category: str) -> None:
    if category == "ok":
        assert parse_structured(content, _Payload).name == ""
        return
    with pytest.raises(StructuredParseError) as excinfo:
        parse_structured(content, _Payload)
    assert excinfo.value.category == category
    assert excinfo.value.retryable is True


def test_parse_never_scrapes_json_out_of_prose() -> None:
    """No greedy '{...}' extraction: prose containing a JSON-looking blob fails."""
    content = 'The answer is probably {"name": "a"} but I am not sure.'
    with pytest.raises(StructuredParseError) as excinfo:
        parse_structured(content, _Payload)
    assert excinfo.value.category == CATEGORY_NOT_JSON


def test_parse_diagnostics_never_contain_the_payload() -> None:
    secret = "user-private-token-abcdef"
    with pytest.raises(StructuredParseError) as excinfo:
        parse_structured(f"nope {secret} nope", _Payload)
    diagnostics = excinfo.value.diagnostics
    assert secret not in diagnostics
    assert "sha=" in diagnostics and "len=" in diagnostics


def test_truncated_payload_is_not_repaired() -> None:
    with pytest.raises(StructuredParseError) as excinfo:
        parse_structured('{"name": "a", "count": 1', _Payload)
    assert excinfo.value.category == CATEGORY_TRUNCATED


# ---------------------------------------------------------------------------
# P0: bounded, corrective retry (budget-respecting)
# ---------------------------------------------------------------------------


def test_retry_recovers_after_a_malformed_payload() -> None:
    provider = _ScriptedProvider([_parse_error(CATEGORY_INVALID_JSON), _valid_synthesis()])
    result = run_synthesis(
        "t",
        _artifacts(),
        *collect_evidence_records(_artifacts()),
        provider=provider,
        staged=False,  # single-shot: this test counts the retry on one call path
    )
    assert provider.calls == 2  # one corrective retry
    assert result.retry_count == 1
    assert "IMPORTANT" in provider.prompts[1]  # the re-ask explains the requirement
    assert "IMPORTANT" not in provider.prompts[0]


def test_retry_exhaustion_raises_synthesis_error() -> None:
    provider = _ScriptedProvider([_parse_error(CATEGORY_NOT_JSON)])
    with pytest.raises(SynthesisError):
        run_synthesis("t", _artifacts(), *collect_evidence_records(_artifacts()), provider=provider)
    assert provider.calls == 2  # bounded: exactly the configured attempts


def test_non_retryable_provider_error_is_not_retried() -> None:
    provider = _ScriptedProvider([ProviderError("LLM provider call failed: AuthenticationError")])
    with pytest.raises(SynthesisError):
        run_synthesis("t", _artifacts(), *collect_evidence_records(_artifacts()), provider=provider)
    assert provider.calls == 1


def test_retry_respects_the_llm_budget() -> None:
    inner = _ScriptedProvider([_parse_error(CATEGORY_INVALID_JSON)])
    counter = CountingProvider(inner, max_calls=1)
    with pytest.raises(SynthesisError):
        run_synthesis("t", _artifacts(), *collect_evidence_records(_artifacts()), provider=counter)
    summary = counter.summary()
    assert summary["count"] == 1   # only the first (real) attempt consumed budget
    assert summary["blocked"] == 1  # the retry was refused, not silently allowed
    assert inner.calls == 1


def test_attempts_are_configurable() -> None:
    provider = _ScriptedProvider([_parse_error(CATEGORY_EMPTY)])
    with pytest.raises(SynthesisError):
        run_synthesis(
            "t", _artifacts(), *collect_evidence_records(_artifacts()),
            provider=provider, max_attempts=1,
        )
    assert provider.calls == 1


# ---------------------------------------------------------------------------
# P1: auditable fallback
# ---------------------------------------------------------------------------


class _BrokenProvider:
    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        raise _parse_error(CATEGORY_INVALID_JSON)


def _degraded_bundle() -> tuple[ReportBundle, list[AgentArtifact]]:
    artifacts = _artifacts()
    bundle = run_synthesis_pipeline("t", artifacts, provider=_BrokenProvider())
    return bundle, artifacts


def test_fallback_is_explicitly_degraded_and_audited() -> None:
    bundle, _ = _degraded_bundle()
    assert bundle.status == "degraded"
    assert bundle.fallback_used is True
    assert bundle.fallback_reason
    assert bundle.retry_count == 1  # the corrective retry was attempted
    assert isinstance(bundle.validation_errors, list)


def test_fallback_findings_cite_real_evidence() -> None:
    bundle, _ = _degraded_bundle()
    known = {item.evidence_id for item in bundle.evidence}
    assert bundle.synthesis.key_findings
    for finding in bundle.synthesis.key_findings:
        assert set(finding.evidence_ids) <= known  # no dangling citations


def test_fallback_produces_a_dedup_audit() -> None:
    bundle, _ = _degraded_bundle()
    assert "dedup: " in bundle.synthesis.notes
    audit = json.loads(bundle.synthesis.notes.split("dedup: ", 1)[1])
    assert "before" in audit and "after" in audit


def test_fallback_content_is_never_verified() -> None:
    bundle, _ = _degraded_bundle()
    for finding in bundle.synthesis.key_findings:
        assert finding.claim_type == "unverified_claim"
        assert finding.support_kind in SUPPORT_KINDS
        assert finding.review_status != "verified"
    for record in bundle.evidence:
        assert record.verified is False
        assert record.review_status != "verified"


def test_all_six_categories_are_persisted_on_the_degraded_path() -> None:
    from types import SimpleNamespace

    from validation.collect import collect_metrics

    bundle, _ = _degraded_bundle()
    session = SimpleNamespace(
        run_id="run_x", task="t", status="success", started_at=1.0, finished_at=2.0, error=None,
        plan=None, agent_results={}, artifacts=[], final_artifact=None,
        synthesis_bundle=bundle, trace=None,
    )
    syn = collect_metrics(session, scenario_id="A", mode="offline")["synthesis"]
    for key in (
        "findings", "insights", "contradictions", "uncertainties", "tradeoffs", "recommendations",
    ):
        assert key in syn and isinstance(syn[key], list)
    assert syn["synthesis_status"] == "degraded"
    assert syn["fallback_used"] is True
    assert syn["fallback_reason"]
    assert syn["dedup_audit"]


def test_report_shows_the_degraded_banner_and_separates_content() -> None:
    bundle, artifacts = _degraded_bundle()
    final = assemble_from_bundle("t", artifacts, bundle, ["agent_a", "agent_b"])
    markdown = final.to_markdown()
    assert "Degraded synthesis" in markdown
    assert final.metadata.get("fallback_used") is True
    assert final.metadata.get("synthesis_status") == "degraded"


def test_legacy_bundle_json_without_new_fields_still_parses() -> None:
    legacy = {
        "task": "t",
        "synthesis": {"key_findings": [], "summary": "s"},
        "status": "completed",
    }
    bundle = ReportBundle.model_validate(legacy)
    assert bundle.fallback_used is False
    assert bundle.retry_count == 0
    assert bundle.validation_errors == []


# ---------------------------------------------------------------------------
# P2: claim quality gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "|  |  |  --- | | Date | July 22, 2026 | | Organization | ServiceNow |",
        "| --- | --- |",
        "-----",
        "",
        "   ",
        '{"categories": ["a", "b"]}',
        "市场规模与增速：2025年投资55.9亿元、",
    ],
)
def test_low_quality_claims_are_flagged(text: str) -> None:
    from app.runtime.claim_quality import assess_claim

    usable, reason = assess_claim(text)
    assert usable is False
    assert reason


@pytest.mark.parametrize(
    "text",
    [
        "中小企业对私有化部署的偏好正在上升",
        "2025 年中国企业级 AI Agent 投资为 55.9 亿元",
        "ROI 不及预期导致部分项目停滞",
    ],
)
def test_meaningful_claims_are_usable(text: str) -> None:
    from app.runtime.claim_quality import assess_claim

    assert assess_claim(text) == (True, "")


def test_low_quality_claim_is_kept_but_never_bound_or_verified() -> None:
    """A table fragment containing numbers must not be matched to a source."""
    from app.llm.provider import MockLLMProvider
    from app.runtime.agent_runtime import AgentRuntime
    from app.runtime.artifacts import AgentDeliverable
    from app.tools.registry import SearchResult, ToolRegistry, ToolResult

    table_row = "| Date | July 22, 2026 | | Revenue | 3.99 billion |"
    snippet = "| Date | July 22, 2026 | | Revenue | 3.99 billion |"  # identical text!
    runtime = AgentRuntime(provider=MockLLMProvider(), tool_registry=ToolRegistry(mode="mock"))
    collected = [
        ToolResult(
            query="q", tool="web_search", offline=False, kind="web", results=[],
            search_results=[
                SearchResult(title="t", url="https://x.example/a", snippet=snippet)
            ],
        )
    ]
    deliverable = AgentDeliverable(title="t", summary="s", key_points=[table_row], sources=[])
    _sources, evidence = runtime._collect_evidence(
        collected, deliverable, agent_id="a", artifact_id="art_a"
    )
    assert len(evidence) == 1          # kept, not dropped
    assert evidence[0].source_id == ""  # never bound, even though text is identical
    assert evidence[0].match_method.startswith("low_quality:")
    assert evidence[0].review_status == "unsupported"
    assert evidence[0].claim_type == "unverified_claim"


def test_usable_claim_still_binds_by_content() -> None:
    """The Phase 5 binding rule is unchanged for real claims."""
    from app.llm.provider import MockLLMProvider
    from app.runtime.agent_runtime import AgentRuntime
    from app.runtime.artifacts import AgentDeliverable
    from app.tools.registry import SearchResult, ToolRegistry, ToolResult

    claim = "2025年中国企业级AI Agent投资55.9亿元，CAGR 70.9%"
    snippet = "中国企业级AI Agent投资2025年为55.9亿元，CAGR 70.9%，持续增长。"
    runtime = AgentRuntime(provider=MockLLMProvider(), tool_registry=ToolRegistry(mode="mock"))
    collected = [
        ToolResult(
            query="q", tool="web_search", offline=False, kind="web", results=[],
            search_results=[
                SearchResult(title="t", url="https://x.example/a", snippet=snippet)
            ],
        )
    ]
    deliverable = AgentDeliverable(title="t", summary="s", key_points=[claim], sources=[])
    sources, evidence = runtime._collect_evidence(
        collected, deliverable, agent_id="a", artifact_id="art_a"
    )
    assert evidence[0].source_id == sources[0].id
    assert evidence[0].review_status == "not_checked"  # bound, still not "verified"
    assert evidence[0].claim_type == "source_fact"


def test_phase6_table_fragment_is_flagged_read_only() -> None:
    """Regression on the real Phase 6 artifact (read-only, no mutation)."""
    from pathlib import Path

    from app.runtime.claim_quality import assess_claim

    evidence_path = Path(
        "validation/runs/20261002T081913Z_A_real/run1_run_bba43b64/evidence.json"
    )
    if not evidence_path.exists():
        pytest.skip("Phase 6 run artifacts not present")
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    table_rows = [item for item in payload["items"] if item["claim"].lstrip().startswith("|")]
    assert table_rows, "expected the known table-fragment claim in the Phase 6 run"
    for item in table_rows:
        usable, reason = assess_claim(item["claim"])
        assert usable is False
        assert reason in {"markdown_table_row", "table_like", "markdown_table_separator"}
    assert evidence_path.exists()  # original artifact untouched
