"""Offline tests for Phase 6.3: output-scale control + staged synthesis.

Covers provider output ceilings / finish_reason / usage capture, deterministic
prompt budgeting, staged generation with independent validation, partial-result
degradation, and truncation-targeted recovery. Fully offline: every provider is
a local fake, no network, no paid API.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.provider import OpenAILLMProvider, ProviderError
from app.runtime.artifacts import AgentArtifact, ArtifactType
from app.synthesis.models import (
    EvidenceRecord,
    Finding,
    Insight,
    Recommendation,
    SourceRecord,
    SynthesisResult,
)
from app.synthesis.pipeline import run_synthesis_pipeline
from app.synthesis.synthesizer import (
    MAX_EVIDENCE_PER_AGENT,
    MAX_EVIDENCE_TOTAL,
    SynthesisError,
    build_synthesis_prompt,
    run_synthesis,
    select_prompt_evidence,
)
from validation.counting_provider import CountingProvider

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None, finish_reason: str | None) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content: str | None, finish_reason: str | None, usage=None) -> None:
        self.choices = [_FakeChoice(content, finish_reason)]
        self.usage = usage


class _FakeCompletions:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.last_kwargs: dict = {}
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._response


def _provider_with(response=None, *, error=None, max_tokens=None) -> tuple:
    provider = OpenAILLMProvider.__new__(OpenAILLMProvider)
    provider.model = "fake-model"
    provider.max_tokens = max_tokens
    provider.last_response_meta = {}
    completions = _FakeCompletions(response=response, error=error)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return provider, completions


# ---------------------------------------------------------------------------
# P0: provider output control
# ---------------------------------------------------------------------------


def test_max_tokens_is_only_sent_when_configured() -> None:
    provider, completions = _provider_with(
        _FakeResponse('{"value": "ok"}', "stop"), max_tokens=None
    )
    provider.structured_completion("p", _Model)
    assert "max_tokens" not in completions.last_kwargs  # endpoint default preserved

    provider, completions = _provider_with(
        _FakeResponse('{"value": "ok"}', "stop"), max_tokens=4096
    )
    provider.structured_completion("p", _Model)
    assert completions.last_kwargs["max_tokens"] == 4096


def test_normal_response_is_parsed_and_meta_recorded() -> None:
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    provider, _ = _provider_with(_FakeResponse('{"value": "ok"}', "stop", usage))
    result = provider.structured_completion("p", _Model)
    assert result.value == "ok"
    assert provider.last_response_meta["finish_reason"] == "stop"
    assert provider.last_response_meta["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
    }
    assert provider.last_response_meta["usage_available"] is True


def test_usage_marked_unavailable_when_endpoint_omits_it() -> None:
    provider, _ = _provider_with(_FakeResponse('{"value": "ok"}', "stop", None))
    provider.structured_completion("p", _Model)
    assert provider.last_response_meta["usage"] is None
    assert provider.last_response_meta["usage_available"] is False


def test_finish_reason_length_is_reported_as_length_limit() -> None:
    truncated = '{"value": "cut off here'
    provider, _ = _provider_with(_FakeResponse(truncated, "length"))
    with pytest.raises(ProviderError) as excinfo:
        provider.structured_completion("p", _Model)
    error = excinfo.value
    assert error.retryable is True
    assert getattr(error, "parse_category", "") == "length_limit"
    assert "finish_reason=length" in error.diagnostics


def test_missing_finish_reason_falls_back_to_parser_classification() -> None:
    provider, _ = _provider_with(_FakeResponse('{"value": "cut off here', None))
    with pytest.raises(ProviderError) as excinfo:
        provider.structured_completion("p", _Model)
    assert getattr(excinfo.value, "parse_category", "") == "truncated"


def test_transport_error_becomes_non_retryable_provider_error() -> None:
    provider, _ = _provider_with(error=RuntimeError("connection reset"))
    with pytest.raises(ProviderError) as excinfo:
        provider.structured_completion("p", _Model)
    assert excinfo.value.retryable is False
    assert "LLM provider call failed" in str(excinfo.value)


def test_provider_diagnostics_never_leak_response_content() -> None:
    secret = "sk-live-SUPERSECRETKEYVALUE123456"
    provider, _ = _provider_with(_FakeResponse(f'{{"value": "{secret}"', "length"))
    with pytest.raises(ProviderError) as excinfo:
        provider.structured_completion("p", _Model)
    blob = f"{excinfo.value}{excinfo.value.diagnostics}"
    assert secret not in blob
    assert "len=" in excinfo.value.diagnostics and "sha=" in excinfo.value.diagnostics


# ---------------------------------------------------------------------------
# P1: deterministic prompt budgeting
# ---------------------------------------------------------------------------


def _evidence(count: int, *, agents: int = 5) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            evidence_id=f"ev_{i:04d}",
            claim=f"claim {i}",
            evidence=f"snippet {i}",
            source_id="source_001",
            source_type="web",
            producer_agent=f"agent_{i % agents}",
        )
        for i in range(count)
    ]


def test_prompt_evidence_is_capped_deterministically() -> None:
    evidence = _evidence(100, agents=5)
    first = select_prompt_evidence(evidence)
    second = select_prompt_evidence(list(reversed(evidence)))
    assert len(first) == MAX_EVIDENCE_TOTAL
    assert [e.evidence_id for e in first] == [e.evidence_id for e in second]  # order-independent
    per_agent: dict[str, int] = {}
    for item in first:
        per_agent[item.producer_agent] = per_agent.get(item.producer_agent, 0) + 1
    assert max(per_agent.values()) <= MAX_EVIDENCE_PER_AGENT
    assert len(per_agent) == 5  # every agent keeps a voice


def test_small_input_is_not_truncated() -> None:
    evidence = _evidence(4, agents=2)
    assert len(select_prompt_evidence(evidence)) == 4


def test_prompt_carries_budgets_and_not_every_evidence_id() -> None:
    evidence = _evidence(100, agents=5)
    selected = select_prompt_evidence(evidence)
    prompt = build_synthesis_prompt("T", [], selected, [])
    assert len(selected) < len(evidence)
    assert "ev_0099" not in prompt  # unselected evidence never reaches the model


def test_stage_prompt_limits_categories_and_length() -> None:
    from app.synthesis.synthesizer import _STAGE_FIELDS, STAGE_STATEMENT_MAX_CHARS

    prompt = build_synthesis_prompt(
        "T", [], _evidence(3, agents=1), [],
        stage="facts", stage_fields=_STAGE_FIELDS["facts"],
    )
    assert "STAGED SYNTHESIS - stage 'facts'" in prompt
    assert "at most 6 key_findings" in prompt
    assert str(STAGE_STATEMENT_MAX_CHARS) in prompt
    assert "Only cite evidence_ids listed above" in prompt  # shared rules kept


# ---------------------------------------------------------------------------
# P2: staged synthesis
# ---------------------------------------------------------------------------


def _artifacts() -> list[AgentArtifact]:
    return [
        AgentArtifact(
            artifact_id="artifact_agent_a",
            agent_id="agent_a",
            output_type=ArtifactType.ANALYSIS,
            title="A",
            content="body a",
            metadata={"role_name": "Agent A"},
        ),
        AgentArtifact(
            artifact_id="artifact_agent_b",
            agent_id="agent_b",
            output_type=ArtifactType.ANALYSIS,
            title="B",
            content="body b",
            metadata={"role_name": "Agent B"},
        ),
    ]


def _evidence_pair() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            evidence_id="ev_1", claim="c1", evidence="s1", source_id="source_001",
            source_type="web", producer_agent="agent_a",
        ),
        EvidenceRecord(
            evidence_id="ev_2", claim="c2", evidence="s2", source_id="source_002",
            source_type="web", producer_agent="agent_b",
        ),
    ]


class _StageProvider:
    """Returns stage-appropriate SynthesisResults and records the prompts."""

    model = "stage-stub"

    def __init__(self, *, facts=None, implications=None, fail: dict | None = None) -> None:
        self.facts = facts
        self.implications = implications
        self.fail = fail or {}
        self.calls = 0
        self.prompts: list[str] = []

    def _ids_from_prompt(self, prompt: str) -> list[str]:
        import re

        return re.findall(r"ev_[0-9a-fA-F]+", prompt)[:2]

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        self.calls += 1
        self.prompts.append(prompt)
        ids = self._ids_from_prompt(prompt)
        if "stage 'facts'" in prompt:
            if "facts" in self.fail:
                raise self.fail["facts"]
            return self.facts if self.facts is not None else SynthesisResult(
                key_findings=[
                    Finding(finding_id="f1", statement="fact one", evidence_ids=ids[:1])
                ]
            )
        if "stage 'implications'" in prompt:
            if "implications" in self.fail:
                raise self.fail["implications"]
            return self.implications if self.implications is not None else SynthesisResult(
                cross_agent_insights=[
                    Insight(
                        insight_id="i1", statement="insight", supporting_evidence_ids=ids
                    )
                ],
                recommendations=[
                    Recommendation(
                        recommendation_id="r1", statement="rec",
                        supporting_insight_ids=["i1"], supporting_evidence_ids=ids[:1],
                    )
                ],
            )
        return SynthesisResult()


def test_staged_run_completes_and_records_stage_audit() -> None:
    provider = _StageProvider()
    result = run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    assert provider.calls == 2  # one call per stage
    assert len(result.stage_audit) == 2
    assert all(stage["ok"] for stage in result.stage_audit)
    assert [s["stage"] for s in result.stage_audit] == ["facts", "implications"]
    assert result.key_findings and result.cross_agent_insights and result.recommendations
    assert result.retry_count == 0


def test_stage_two_receives_prior_findings() -> None:
    provider = _StageProvider()
    run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    implications_prompt = provider.prompts[1]
    assert "PRIOR FINDINGS" in implications_prompt
    assert "fact one" in implications_prompt


def test_categories_do_not_mix_between_stages() -> None:
    """A stage response carrying extra categories must not leak them in."""
    leaky = SynthesisResult(
        key_findings=[
            Finding(finding_id="leak", statement="should not appear", evidence_ids=["ev_1"])
        ],
        cross_agent_insights=[
            Insight(insight_id="i1", statement="insight", supporting_evidence_ids=["ev_1"])
        ],
    )
    provider = _StageProvider(
        facts=SynthesisResult(
            key_findings=[Finding(finding_id="f1", statement="real fact", evidence_ids=["ev_1"])]
        ),
        implications=leaky,
    )
    result = run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    assert [f.finding_id for f in result.key_findings] == ["f1"]  # no leak
    assert result.cross_agent_insights


def test_dangling_stage_citation_is_dropped_not_faked() -> None:
    provider = _StageProvider(
        facts=SynthesisResult(
            key_findings=[
                Finding(finding_id="good", statement="ok", evidence_ids=["ev_1"]),
                Finding(finding_id="bad", statement="dangling", evidence_ids=["ev_missing"]),
            ]
        )
    )
    result = run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    assert [f.finding_id for f in result.key_findings] == ["good"]
    assert any("ev_missing" in issue for issue in result.validation_errors)


def test_cross_stage_references_survive_the_merge() -> None:
    provider = _StageProvider(
        implications=SynthesisResult(
            cross_agent_insights=[
                Insight(insight_id="ins_9", statement="i", supporting_evidence_ids=["ev_1"])
            ],
            recommendations=[
                Recommendation(
                    recommendation_id="rec_9", statement="r",
                    supporting_insight_ids=["ins_9"], supporting_evidence_ids=["ev_1"],
                )
            ],
        )
    )
    result = run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    assert result.recommendations[0].supporting_insight_ids == ["ins_9"]
    assert {i.insight_id for i in result.cross_agent_insights} == {"ins_9"}


def test_final_assembly_has_no_dangling_references() -> None:
    from app.synthesis.evidence_filter import validate_report_references
    from app.synthesis.models import ReportBundle

    provider = _StageProvider()
    result = run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    bundle = ReportBundle(
        task="T", synthesis=result, evidence=_evidence_pair(),
        sources=[SourceRecord(source_id="source_001"), SourceRecord(source_id="source_002")],
        status="completed",
    )
    assert validate_report_references(bundle) == []


def test_partial_stage_failure_keeps_validated_partial_output() -> None:
    provider = _StageProvider(fail={"implications": ProviderError("boom")})
    with pytest.raises(SynthesisError) as excinfo:
        run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    error = excinfo.value
    assert error.partial_result is not None
    assert error.partial_result.key_findings            # stage-1 output preserved
    assert not error.partial_result.cross_agent_insights  # stage 2 never ran
    assert [s["ok"] for s in error.stage_audit] == [True, False]
    assert error.stage_audit[1]["error"]


def test_pipeline_marks_partial_stage_failure_as_degraded_not_success() -> None:
    provider = _StageProvider(fail={"implications": ProviderError("boom")})
    bundle = run_synthesis_pipeline("T", _artifacts(), provider=provider)
    assert bundle.status == "degraded"
    assert bundle.fallback_used is True
    assert bundle.stage_audit and bundle.stage_audit[1]["ok"] is False
    assert bundle.synthesis.key_findings  # partial kept, not replaced by fallback
    assert "dedup: " in bundle.synthesis.notes  # audit still produced


def test_stage_one_failure_falls_back_but_stays_audited() -> None:
    provider = _StageProvider(fail={"facts": ProviderError("boom")})
    bundle = run_synthesis_pipeline("T", _artifacts(), provider=provider)
    assert bundle.status == "degraded"
    assert bundle.fallback_used is True
    assert bundle.stage_audit[0]["ok"] is False
    assert bundle.synthesis.key_findings  # generic fallback still traceable


# ---------------------------------------------------------------------------
# P3: truncation-targeted recovery + budget
# ---------------------------------------------------------------------------


def test_truncation_retry_asks_for_a_smaller_answer() -> None:
    class _TruncatingProvider:
        model = "trunc"

        def __init__(self) -> None:
            self.prompts: list[str] = []

        def structured_completion(self, prompt, response_model):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                error = ProviderError(
                    "structured output invalid [length_limit]: cut off",
                    category="structured_parse",
                    retryable=True,
                    diagnostics="finish_reason=length",
                )
                error.parse_category = "length_limit"
                raise error
            return SynthesisResult(
                key_findings=[Finding(finding_id="f", statement="s", evidence_ids=["ev_1"])]
            )

    provider = _TruncatingProvider()
    run_synthesis(
        "T", _artifacts(), _evidence_pair(), [], provider=provider, staged=False, max_attempts=2
    )
    assert len(provider.prompts) == 2
    assert "CUT OFF" in provider.prompts[1] and "SMALLER" in provider.prompts[1]
    assert "CUT OFF" not in provider.prompts[0]


def test_model_provider_errors_are_not_retried() -> None:
    class _AuthError:
        model = "auth"

        def __init__(self) -> None:
            self.calls = 0

        def structured_completion(self, prompt, response_model):
            self.calls += 1
            raise ProviderError("LLM provider call failed: AuthenticationError")

    provider = _AuthError()
    with pytest.raises(SynthesisError):
        run_synthesis(
            "T", _artifacts(), _evidence_pair(), [], provider=provider, staged=False
        )
    assert provider.calls == 1


def test_staged_retries_respect_the_llm_budget() -> None:
    class _AlwaysTruncates:
        model = "trunc"

        def structured_completion(self, prompt, response_model):
            error = ProviderError(
                "structured output invalid [length_limit]: cut off",
                category="structured_parse", retryable=True, diagnostics="finish_reason=length",
            )
            error.parse_category = "length_limit"
            raise error

    counter = CountingProvider(_AlwaysTruncates(), max_calls=1)
    with pytest.raises(SynthesisError):
        run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=counter)
    summary = counter.summary()
    assert summary["count"] == 1   # only the first real attempt
    assert summary["blocked"] == 1  # the retry was refused by the budget
    assert summary["finish_reasons"]  # safe per-call metadata is recorded


def test_counting_provider_reports_usage_when_available() -> None:
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=7, total_tokens=12)
    provider, _ = _provider_with(_FakeResponse('{"value": "ok"}', "stop", usage))
    counter = CountingProvider(provider)
    counter.structured_completion("p", _Model)
    summary = counter.summary()
    assert summary["token_usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
    }
    assert summary["finish_reasons"] == {"stop": 1}


def test_counting_provider_marks_usage_unavailable_without_endpoint_support() -> None:
    provider, _ = _provider_with(_FakeResponse('{"value": "ok"}', "stop", None))
    counter = CountingProvider(provider)
    counter.structured_completion("p", _Model)
    summary = counter.summary()
    assert summary["token_usage"] is None
    assert summary["token_usage_reason"]


# ---------------------------------------------------------------------------
# compatibility
# ---------------------------------------------------------------------------


def test_legacy_synthesis_payload_without_stage_audit_still_parses() -> None:
    legacy = {"key_findings": [], "summary": "s", "retry_count": 1}
    result = SynthesisResult.model_validate(legacy)
    assert result.stage_audit == []


def test_single_shot_mode_is_still_available() -> None:
    class _SingleShot:
        model = "one"

        def __init__(self) -> None:
            self.calls = 0

        def structured_completion(self, prompt, response_model):
            self.calls += 1
            return SynthesisResult(
                key_findings=[Finding(finding_id="f", statement="s", evidence_ids=["ev_1"])]
            )

    provider = _SingleShot()
    result = run_synthesis(
        "T", _artifacts(), _evidence_pair(), [], provider=provider, staged=False
    )
    assert provider.calls == 1
    assert result.key_findings and result.stage_audit == []


def test_stage_audit_is_persisted_in_metrics() -> None:
    from validation.collect import collect_metrics

    provider = _StageProvider()
    result = run_synthesis("T", _artifacts(), _evidence_pair(), [], provider=provider)
    from app.synthesis.models import ReportBundle

    bundle = ReportBundle(task="T", synthesis=result, evidence=_evidence_pair(), status="completed")
    session = SimpleNamespace(
        run_id="run_x", task="T", status="success", started_at=1.0, finished_at=2.0, error=None,
        plan=None, agent_results={}, artifacts=[], final_artifact=None,
        synthesis_bundle=bundle, trace=None,
    )
    syn = collect_metrics(session, scenario_id="A", mode="offline")["synthesis"]
    assert len(syn["stage_audit"]) == 2
    assert json.loads(json.dumps(syn["stage_audit"]))  # JSON-serialisable


class _Model(BaseModel):
    value: str = ""
