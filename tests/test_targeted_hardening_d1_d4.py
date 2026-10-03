"""Targeted hardening tests: D1 adaptive length_limit retry, D2 finding counts,
D3 executive summary, D4 search trigger vs authorisation.

Every provider here is a *scripted fake*, never ``MockLLMProvider``, so the real
adaptive path is exercised. Nothing in this module touches the network.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm.provider import MockLLMProvider, ProviderError
from app.runtime.agent_runtime import (
    LENGTH_LIMIT_ADAPTIONS,
    LENGTH_LIMIT_CONCISE_HINT,
    LENGTH_LIMIT_TOKEN_CAP,
    AgentRuntime,
)
from app.synthesis.assembler import assemble_from_bundle
from app.synthesis.models import Finding, SynthesisResult
from app.synthesis.synthesizer import (
    SUMMARY_STATUS_DERIVED,
    SUMMARY_STATUS_MODEL,
    SUMMARY_STATUS_UNAVAILABLE,
    compute_finding_counts,
    derive_executive_summary,
)


class _Echo(BaseModel):
    value: str = "ok"


def _length_limit_error() -> ProviderError:
    error = ProviderError(
        "structured output invalid [length_limit]: cut off",
        category="structured_parse",
        retryable=True,
        diagnostics="finish_reason=length",
    )
    error.parse_category = "length_limit"
    return error


def _invalid_json_error() -> ProviderError:
    error = ProviderError(
        "structured output invalid [invalid_json]: bad token",
        category="structured_parse",
        retryable=True,
        diagnostics="pos=3",
    )
    error.parse_category = "invalid_json"
    return error


def _fatal_error() -> ProviderError:
    error = ProviderError(
        "LLM provider call failed: AuthenticationError",
        category="transport",
        retryable=False,
        diagnostics="",
    )
    error.parse_category = "auth"
    return error


class ScriptedProvider:
    """Duck-typed *real* provider: plays a script, records every request."""

    def __init__(self, script, *, max_tokens=None, max_calls=None):
        self.script = list(script)
        self.max_tokens = max_tokens
        self.max_calls = max_calls
        self.requests: list[dict] = []
        self.is_mock = False
        self.model = "scripted"

    def structured_completion(self, prompt, response_model):
        self.requests.append({"max_tokens": self.max_tokens, "prompt": prompt})
        item = self.script.pop(0) if self.script else None
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, BaseModel):
            return item
        return response_model.model_validate(item or {})

    def summary(self) -> dict:
        return {
            "count": len(self.requests),
            "blocked": 0,
            "max_calls": self.max_calls,
            "model": self.model,
        }


def _finding(fid: str, evidence_ids: list[str], **kwargs) -> Finding:
    return Finding(
        finding_id=fid, statement=f"statement {fid}", evidence_ids=evidence_ids, **kwargs
    )


# ---------------------------------------------------------------------------
# D1 — bounded adaptive retry for confirmed length_limit stops
# ---------------------------------------------------------------------------


def test_length_limit_adapts_and_succeeds() -> None:
    provider = ScriptedProvider([_length_limit_error(), _Echo(value="recovered")], max_tokens=1000)
    runtime = AgentRuntime(provider=provider)
    result = runtime._complete_with_length_recovery(
        "prompt", _Echo, agent_id="database_engineer", stage="agent_decision"
    )
    assert result.value == "recovered"
    assert len(provider.requests) == 2
    # The retry really used different parameters (D1 core requirement).
    assert provider.requests[0]["max_tokens"] == 1000
    assert provider.requests[1]["max_tokens"] == 1500
    assert LENGTH_LIMIT_CONCISE_HINT in provider.requests[1]["prompt"]
    # The original ceiling is restored, so later calls are unaffected.
    assert provider.max_tokens == 1000
    assert runtime.length_adaptions[0]["outcome"] == "ceiling_raised"
    assert runtime.length_adaptions[0]["max_tokens"] == 1500


def test_length_limit_stops_after_bounded_adaptions() -> None:
    errors = [_length_limit_error() for _ in range(LENGTH_LIMIT_ADAPTIONS + 1)]
    provider = ScriptedProvider(errors, max_tokens=1000)
    runtime = AgentRuntime(provider=provider)
    with pytest.raises(ProviderError):
        runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    # 1 original + LENGTH_LIMIT_ADAPTIONS adaptions - never more.
    assert len(provider.requests) == LENGTH_LIMIT_ADAPTIONS + 1
    assert provider.max_tokens == 1000  # restored even on the failure path


def test_token_ceiling_never_exceeds_hard_cap() -> None:
    provider = ScriptedProvider([_length_limit_error()], max_tokens=LENGTH_LIMIT_TOKEN_CAP)
    runtime = AgentRuntime(provider=provider)
    with pytest.raises(ProviderError):
        runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert len(provider.requests) == 1  # growth is impossible -> no wasted call
    assert runtime.length_adaptions[0]["outcome"] == "cap_reached"


def test_budget_exhausted_blocks_adaption() -> None:
    provider = ScriptedProvider([_length_limit_error()], max_tokens=1000, max_calls=1)
    runtime = AgentRuntime(provider=provider)
    with pytest.raises(ProviderError):
        runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert len(provider.requests) == 1
    assert runtime.length_adaptions[0]["outcome"] == "budget_blocked"


def test_invalid_json_does_not_trigger_length_adaption() -> None:
    provider = ScriptedProvider([_invalid_json_error()], max_tokens=1000)
    runtime = AgentRuntime(provider=provider)
    with pytest.raises(ProviderError):
        runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert len(provider.requests) == 1
    assert runtime.length_adaptions == []


def test_non_retryable_error_is_never_retried() -> None:
    provider = ScriptedProvider([_fatal_error()], max_tokens=1000)
    runtime = AgentRuntime(provider=provider)
    with pytest.raises(ProviderError):
        runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert len(provider.requests) == 1
    assert runtime.length_adaptions == []


def test_adaptions_disabled_keeps_previous_behaviour() -> None:
    provider = ScriptedProvider([_length_limit_error()], max_tokens=1000)
    runtime = AgentRuntime(provider=provider, length_limit_adaptions=0)
    with pytest.raises(ProviderError):
        runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert len(provider.requests) == 1


def test_no_ceiling_configured_falls_back_to_hint_only() -> None:
    provider = ScriptedProvider([_length_limit_error(), _Echo(value="ok")], max_tokens=None)
    runtime = AgentRuntime(provider=provider)
    result = runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert result.value == "ok"
    assert provider.max_tokens is None  # no ceiling invented
    assert runtime.length_adaptions[0]["outcome"] == "concise_hint_only"


def test_offline_mock_provider_is_untouched() -> None:
    provider = MockLLMProvider()
    runtime = AgentRuntime(provider=provider)
    # The mock never raises length_limit, so this simply must not error.
    runtime._complete_with_length_recovery("p", _Echo, agent_id="a", stage="s")
    assert runtime.length_adaptions == []


def test_database_engineer_length_limit_never_repeats_identical_call() -> None:
    """Scenario B regression: 3 identical length_limit failures, no repeat."""
    from app.runtime.context import AgentExecutionContext
    from app.tools.registry import ToolRegistry

    errors = [_length_limit_error() for _ in range(LENGTH_LIMIT_ADAPTIONS + 1)]
    provider = ScriptedProvider(errors, max_tokens=4096)
    runtime = AgentRuntime(
        provider=provider, tool_registry=ToolRegistry(mode="auto"), max_iterations=1
    )

    def _agent():
        from app.models.agent import AgentRole
        from app.models.capability import CapabilityName
        from app.runtime.agent_factory import DynamicAgentSpec

        return DynamicAgentSpec(
            id="database_engineer",
            role=AgentRole(
                name="Database Engineer",
                capabilities=[CapabilityName.DATA_ANALYSIS],
                goal="design the schema",
            ),
            tools=["schema_validator"],
            system_prompt="test",
        )

    def _task():
        from app.models.task import Task

        return Task(description="design the ticket schema")

    context = AgentExecutionContext(
        agent_id="database_engineer",
        role_name="Database Engineer",
        task="design the ticket schema",
        expected_output="architecture_design",
    )
    with pytest.raises(ProviderError):
        runtime._real_execution(_agent(), context, _task())
    # Crucially: the retries are NOT byte-identical re-sends.
    ceilings = [request["max_tokens"] for request in provider.requests]
    assert len(set(ceilings)) > 1, "retries repeated the identical parameters"
    assert any(LENGTH_LIMIT_CONCISE_HINT in request["prompt"] for request in provider.requests[1:])


# ---------------------------------------------------------------------------
# D2 — deterministic finding classification
# ---------------------------------------------------------------------------


def test_counts_all_findings_without_evidence() -> None:
    findings = [_finding("f1", []), _finding("f2", ["missing"])]
    counts = compute_finding_counts(findings, {})
    assert counts["total"] == 2
    assert counts["with_valid_evidence"] == 0
    assert counts["unsupported"] == 2
    assert counts["supported"] == 0


def test_counts_all_findings_with_valid_evidence() -> None:
    index = {"e1": object(), "e2": object()}
    findings = [
        _finding("f1", ["e1"], support_level="source_text", independent_source_count=2),
        _finding("f2", ["e2"], support_level="source_text", independent_source_count=2),
    ]
    counts = compute_finding_counts(findings, index)
    assert counts["with_valid_evidence"] == 2
    assert counts["supported"] == 2
    assert counts["multi_source"] == 2
    assert counts["unsupported"] == 0


def test_counts_single_source() -> None:
    index = {"e1": object()}
    findings = [_finding("f1", ["e1"], support_level="source_text", independent_source_count=1)]
    counts = compute_finding_counts(findings, index)
    assert counts["single_source"] == 1
    assert counts["multi_source"] == 0


def test_counts_agent_consensus_is_supported_derivation() -> None:
    index = {"e1": object()}
    for level in ("agent_consensus", "derived"):
        findings = [_finding("f1", ["e1"], support_level=level)]
        counts = compute_finding_counts(findings, index)
        assert counts["supported"] == 1, level
        assert counts["unverified"] == 0


def test_counts_planning_assumption_is_unverified() -> None:
    index = {"e1": object()}
    findings = [_finding("f1", ["e1"], support_level="planning_assumption")]
    counts = compute_finding_counts(findings, index)
    assert counts["supported"] == 0
    assert counts["unverified"] == 1


def test_counts_reviewed_unsupported_is_unverified() -> None:
    index = {"e1": object()}
    findings = [_finding("f1", ["e1"], support_level="source_text", review_status="unsupported")]
    counts = compute_finding_counts(findings, index)
    assert counts["unverified"] == 1
    assert counts["supported"] == 0


def test_counts_empty_findings() -> None:
    counts = compute_finding_counts([], {})
    assert counts["total"] == 0
    assert set(counts.values()) == {0}


def test_counts_dangling_evidence_id_is_unsupported() -> None:
    index = {"known": object()}
    counts = compute_finding_counts([_finding("f1", ["ghost"])], index)
    assert counts["unsupported"] == 1
    assert counts["with_valid_evidence"] == 0


def test_counts_are_not_taken_from_the_legacy_llm_lists() -> None:
    """The breakdown is derived from real state, not the model-filled lists."""
    finding = _finding(
        "f1", ["e1"], support_level="source_text", independent_source_count=1
    )
    result = SynthesisResult(
        key_findings=[finding],
        supported_findings=[],
        single_source_findings=[],
    )
    counts = compute_finding_counts(result.key_findings, {"e1": object()})
    assert counts["total"] == 1
    assert counts["single_source"] == 1
    # Legacy lists stay empty and are never used as the source of truth.
    assert result.supported_findings == []


# ---------------------------------------------------------------------------
# D3 — executive summary must be real, or honestly marked unavailable
# ---------------------------------------------------------------------------


def test_model_summary_is_kept_verbatim() -> None:
    result = SynthesisResult(summary="Real model-written summary.")
    summary, status, reason = derive_executive_summary(result)
    assert summary == "Real model-written summary."
    assert status == SUMMARY_STATUS_MODEL
    assert reason == ""


def test_empty_summary_with_findings_is_derived() -> None:
    result = SynthesisResult(
        summary="",
        key_findings=[_finding("f1", ["e1"], support_level="source_text")],
        cross_agent_insights=[],
        recommendations=[],
    )
    result.key_findings[0].statement = "SMB adoption is growing fast."
    summary, status, reason = derive_executive_summary(result)
    assert status == SUMMARY_STATUS_DERIVED
    assert "SMB adoption is growing fast." in summary
    assert summary  # never empty when material exists


def test_empty_summary_without_material_is_unavailable_not_fabricated() -> None:
    result = SynthesisResult(summary="")
    summary, status, reason = derive_executive_summary(result)
    assert summary == ""
    assert status == SUMMARY_STATUS_UNAVAILABLE
    assert "unavailable" in reason


def test_statistical_sentence_is_never_used_as_summary() -> None:
    """The old placeholder must not reappear anywhere in the fallback path."""
    result = SynthesisResult(summary="", key_findings=[_finding("f1", ["e1"])])
    result.key_findings[0].statement = "x"
    summary, _status, _reason = derive_executive_summary(result)
    assert "Cross-agent synthesis over" not in summary
    source = open("app/synthesis/assembler.py", encoding="utf-8").read()
    assert "Cross-agent synthesis over" not in source


def test_derived_summary_reaches_the_final_markdown() -> None:
    from app.synthesis.models import ReportBundle

    result = SynthesisResult(
        key_findings=[_finding("f1", ["e1"], support_level="source_text")],
    )
    result.key_findings[0].statement = "Demand is concentrated in SMB."
    summary_text, status, reason = derive_executive_summary(result)
    result.summary = summary_text
    result.summary_status = status
    result.summary_reason = reason
    bundle = ReportBundle(task="design a system", synthesis=result, evidence=[], sources=[])
    artifact = assemble_from_bundle("design a system", [], bundle, [])
    assert "Demand is concentrated in SMB." in artifact.summary
    assert "Cross-agent synthesis over" not in artifact.summary


def test_unavailable_summary_is_disclosed_in_markdown() -> None:
    from app.synthesis.models import ReportBundle

    result = SynthesisResult()
    summary_text, status, reason = derive_executive_summary(result)
    result.summary = summary_text
    result.summary_status = status
    result.summary_reason = reason
    bundle = ReportBundle(task="design a system", synthesis=result, evidence=[], sources=[])
    artifact = assemble_from_bundle("design a system", [], bundle, [])
    assert "unavailable" in artifact.summary.lower()


def test_old_schema_without_summary_fields_still_parses() -> None:
    """Backwards compatibility: a payload without the new fields must parse."""
    payload = {"key_findings": [{"finding_id": "f1", "statement": "s"}]}
    result = SynthesisResult.model_validate(payload)
    assert result.summary_status == ""
    assert result.finding_counts == {}


# ---------------------------------------------------------------------------
# D4 — authorisation is not an obligation; requirements are stated, not forced
# ---------------------------------------------------------------------------


def test_sourcing_note_only_for_source_required_intents() -> None:
    runtime = AgentRuntime()
    assert runtime._sourcing_requirement_note(
        _Stub(expected_output="architecture_design"), _Stub(expected_output="architecture_design")
    ) == ""
    note = runtime._sourcing_requirement_note(
        _Stub(expected_output="market_overview"), _Stub(expected_output="market_overview")
    )
    assert "SOURCING REQUIREMENT" in note
    assert "market_overview" in note


def test_unauthorised_tool_call_is_still_refused() -> None:
    from app.tools.registry import ToolNotAllowed, ToolRegistry

    registry = ToolRegistry(mode="auto")
    with pytest.raises(ToolNotAllowed):
        registry.validate_allowed("web_search", ["calculator"])


def test_no_web_event_is_fabricated_when_agent_does_not_search() -> None:
    """An agent that never calls a tool must not produce a web tool event."""
    runtime = AgentRuntime()
    assert runtime.length_adaptions == []
    registry_events = []
    runtime.store.record_events = lambda *a, **k: registry_events.append(a)
    assert registry_events == []


class _Stub:
    """Minimal stand-in exposing a single attribute."""

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.metadata = kwargs
