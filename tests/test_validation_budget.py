"""Offline tests for the Phase-3 budget hardening (no network, no credentials).

Covers the global LLM call ceiling, cooperative deadline cancellation, the
wall-clock net around a blocking call, and the truth-flag consequences of a
budget stop. Everything runs offline: provider doubles are local objects.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.provider import MockLLMProvider
from tests.test_validation import _EmptyModel, _RealStub, _StubProvider, _synthetic_session
from validation import run_scenario
from validation.collect import collect_metrics, determine_truth
from validation.counting_provider import CountingProvider, LLMBudgetExceeded


def test_llm_budget_blocks_after_ceiling() -> None:
    inner = _StubProvider()
    counter = CountingProvider(inner, max_calls=2)
    counter.structured_completion("p", _EmptyModel)
    counter.structured_completion("p", _EmptyModel)
    with pytest.raises(LLMBudgetExceeded):
        counter.structured_completion("p", _EmptyModel)
    summary = counter.summary()
    assert summary["count"] == 2  # actual calls only
    assert summary["succeeded"] == 2
    assert summary["failed"] == 0
    assert summary["blocked"] == 1  # blocked tracked separately
    assert summary["blocked_by_reason"] == {"max_llm_calls": 1}
    assert inner.calls == 2  # the blocked request never reached the provider


def test_llm_budget_is_concurrency_safe() -> None:
    inner = _StubProvider()
    counter = CountingProvider(inner, max_calls=5)

    def _call(_: int) -> None:
        try:
            counter.structured_completion("p", _EmptyModel)
        except LLMBudgetExceeded:
            pass

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(_call, range(60)))
    summary = counter.summary()
    assert summary["count"] == 5
    assert summary["blocked"] == 55
    assert inner.calls == 5  # ceiling never exceeded under concurrency
    assert summary["count"] + summary["blocked"] == 60


def test_llm_budget_deadline_blocks_new_calls() -> None:
    counter = CountingProvider(_StubProvider(), deadline=time.monotonic() - 1.0)
    with pytest.raises(LLMBudgetExceeded):
        counter.structured_completion("p", _EmptyModel)
    summary = counter.summary()
    assert summary["count"] == 0
    assert summary["blocked_by_reason"] == {"run_deadline": 1}


def test_provider_exception_is_counted_not_blocked() -> None:
    counter = CountingProvider(_StubProvider(fail=True), max_calls=3)
    with pytest.raises(RuntimeError):
        counter.structured_completion("p", _EmptyModel)
    summary = counter.summary()
    assert summary["count"] == 1
    assert summary["failed"] == 1
    assert summary["blocked"] == 0


def test_truth_reflects_budget_abort() -> None:
    truth = determine_truth(
        provider=_RealStub(),
        tool_metrics={"by_kind": {"web": 1}},
        llm_call_count=2,
        provider_fallback=False,
        synthesis_degraded=False,
        core_data_present=True,
        blocked_llm_calls=3,
        aborted=True,
        abort_reason="run_timeout",
    )
    assert truth["verdict"] == "aborted_budget"
    assert truth["is_valid_real_e2e"] is False
    assert truth["aborted"] is True
    assert truth["blocked_llm_calls"] == 3
    assert truth["reasons"]


def test_truth_blocked_calls_make_run_degraded_not_valid() -> None:
    truth = determine_truth(
        provider=_RealStub(),
        tool_metrics={"by_kind": {"web": 1}},
        llm_call_count=3,
        provider_fallback=False,
        synthesis_degraded=False,
        core_data_present=True,
        blocked_llm_calls=2,
    )
    assert truth["verdict"] == "degraded_partial"
    assert truth["is_valid_real_e2e"] is False


def test_budget_exhaustion_is_not_reported_as_mock() -> None:
    """A budget stop must never be disguised as a mock/offline success."""
    counter = CountingProvider(_RealStub(), max_calls=1)
    counter.structured_completion("p", _EmptyModel)
    with pytest.raises(LLMBudgetExceeded):
        counter.structured_completion("p", _EmptyModel)

    metrics = collect_metrics(
        _synthetic_session(),
        scenario_id="A",
        mode="real",
        provider=counter,
        counting=counter,
        measured_elapsed=5.0,
        termination_reason="llm_budget_exhausted",
        aborted=True,
    )
    assert metrics["provider"]["is_real_llm"] is True
    assert metrics["provider"]["is_mock"] is False
    assert metrics["provider"]["llm_calls"]["blocked"] == 1
    assert metrics["truth"]["blocked_llm_calls"] == 1
    assert metrics["truth"]["verdict"] == "aborted_budget"
    assert metrics["truth"]["is_valid_real_e2e"] is False
    assert metrics["termination"]["budget_exhausted"] is True
    assert metrics["termination"]["aborted"] is True


class _ShapeStub:
    """Not a MockLLMProvider, but returns schema-valid stubs offline.

    Lets us drive the real code path (``_real_execution`` / real team building)
    with zero network access.
    """

    model = "shape-stub"

    def __init__(self) -> None:
        self._inner = MockLLMProvider()

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        return self._inner.structured_completion(prompt, response_model)


def test_llm_budget_exhaustion_surfaces_without_mock_fallback() -> None:
    stub = _ShapeStub()
    outcome = run_scenario._run_once_guarded(
        task="synthetic budget test",
        mode="real",
        args=SimpleNamespace(max_llm_calls=1, timeout=30.0, max_tool_calls=2, max_iterations=2),
        run_deadline=time.monotonic() + 60.0,
        provider_resolver=lambda: stub,
    )
    assert outcome.counting is not None
    assert outcome.counting.inner is stub  # never replaced by a mock provider
    summary = outcome.counting.summary()
    assert summary["blocked"] >= 1
    assert summary["blocked_by_reason"]
    assert outcome.termination_reason == "llm_budget_exhausted"
    assert outcome.aborted is True
    if outcome.session is not None:
        assert outcome.session.provider_name != "MockLLMProvider"


class _SleepingProvider:
    """Real-looking provider whose call blocks (cannot be interrupted)."""

    model = "sleepy-stub"

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        time.sleep(2.0)
        return response_model()


def test_wall_clock_timeout_aborts_and_saves_partial_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_scenario, "REAL_EXECUTION_ENABLED", True)
    monkeypatch.setattr(run_scenario, "_resolve_real_provider", _SleepingProvider)
    code = run_scenario.main(
        [
            "--scenario",
            "A",
            "--runs",
            "1",
            "--mode",
            "real",
            "--confirm-real",
            "--max-total-minutes",
            "0.02",  # ~1.2s < the 2s blocking call
            "--max-llm-calls",
            "5",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    batch = json.loads(next(tmp_path.glob("*/batch.json")).read_text(encoding="utf-8"))
    run = batch["runs"][0]
    assert run["termination_reason"] == "run_timeout"
    assert run["truth"]["verdict"] == "aborted_budget"
    assert run["truth"]["is_valid_real_e2e"] is False
    run_dir = Path(run["dir"])
    for name in ("metrics.json", "report.md", "partial_provider_log.json", "task.txt"):
        assert (run_dir / name).exists(), name
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["termination"]["run_timeout"] is True
    assert metrics["truth"]["aborted"] is True
    assert metrics["provider"]["is_mock"] is False  # never swapped to the mock
    assert metrics["session_status"] == "aborted"


def test_aborted_run_stops_further_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_scenario, "REAL_EXECUTION_ENABLED", True)
    monkeypatch.setattr(run_scenario, "_resolve_real_provider", _SleepingProvider)
    code = run_scenario.main(
        [
            "--scenario",
            "A",
            "--runs",
            "3",
            "--mode",
            "real",
            "--confirm-real",
            "--max-total-minutes",
            "0.02",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    batch = json.loads(next(tmp_path.glob("*/batch.json")).read_text(encoding="utf-8"))
    assert len(batch["runs"]) == 1  # stopped after the budget abort
    assert batch["runs"][0]["termination_reason"] == "run_timeout"


def test_offline_mode_is_unaffected_by_llm_budget(tmp_path: Path) -> None:
    """Offline runs never use the LLM budget, and never report blocked calls."""
    code = run_scenario.main(
        [
            "--scenario",
            "A",
            "--runs",
            "1",
            "--mode",
            "offline",
            "--max-llm-calls",
            "1",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    run = json.loads(next(tmp_path.glob("*/batch.json")).read_text(encoding="utf-8"))["runs"][0]
    assert run["termination_reason"] == "completed"
    assert run["truth"]["is_real_llm"] is False
    assert run["metrics"]["llm_blocked"] in (0, None)
