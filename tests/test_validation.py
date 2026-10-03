"""Offline unit tests for the AutoTeam v0.6.0 validation toolkit.

Everything here runs fully offline: no provider, no Tavily, no network. The
tests cover the counting provider, sanitisation, metric collection, truth
determination, CLI guards, default-offline safety and the single-agent baseline.
"""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.provider import MockLLMProvider
from app.models.capability import CapabilityName
from app.runtime.events import ExecutionTrace
from app.scheduler.models import AgentResult, ExecutionStatus
from validation import run_scenario, single_agent_baseline
from validation.collect import (
    collect_metrics,
    determine_truth,
    max_concurrency_from_results,
)
from validation.counting_provider import CountingMockProvider, CountingProvider
from validation.sanitize import domain_of, redact_text, sanitize_url
from validation.scenarios import SCENARIOS, get_scenario, scenario_ids


class _StubProvider:
    """Minimal provider double: no network, configurable failure."""

    def __init__(self, *, model: str = "stub-model", fail: bool = False) -> None:
        self.model = model
        self.fail = fail
        self.calls = 0

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom sk-abcdefgh12345678")
        return response_model()


class _RealStub:
    """Looks like a real provider (not a MockLLMProvider) without any network."""

    model = "real-stub"

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        return response_model()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def test_scenarios_have_ids_tasks_and_checklists() -> None:
    assert scenario_ids() == ["A", "B", "C"]
    for key in scenario_ids():
        scenario = get_scenario(key)
        assert scenario.scenario_id == key
        assert len(scenario.task) > 40
        assert len(scenario.checklist) >= 10
    assert get_scenario("a") is SCENARIOS["A"]


def test_scenarios_do_not_prescribe_agents_or_topology() -> None:
    """Task text must stay natural language, never a prescribed workflow."""
    forbidden = ["agent_id", "layer", "dag", "topology", "依赖边", "第1层"]
    for key in scenario_ids():
        task = get_scenario(key).task.lower()
        assert not any(word.lower() in task for word in forbidden)


def test_unknown_scenario_raises() -> None:
    with pytest.raises(KeyError):
        get_scenario("Z")


# ---------------------------------------------------------------------------
# Counting provider
# ---------------------------------------------------------------------------


def test_counting_provider_delegates_and_counts() -> None:
    inner = _StubProvider()
    counter = CountingProvider(inner)
    out = counter.structured_completion("prompt", _EmptyModel)
    assert isinstance(out, _EmptyModel)
    assert inner.calls == 1
    summary = counter.summary()
    assert summary["count"] == 1
    assert summary["succeeded"] == 1
    assert summary["failed"] == 0
    assert summary["model"] == "stub-model"
    assert summary["is_mock"] is False
    # Per-call records hold timing/outcome only — never prompt or response text.
    assert summary["records_prompts_or_responses"] is False
    for call in summary["calls"]:
        assert set(call) == {
            "index",
            "started_at",
            "finished_at",
            "started_offset",
            "duration",
            "ok",
            "error_type",
            "error",
            # v0.6.1: safe per-call metadata (no prompt/response text).
            "finish_reason",
            "usage",
        }
    assert summary["token_usage"] is None
    assert "response.usage" in summary["token_usage_reason"]


def test_counting_provider_reraises_and_redacts() -> None:
    counter = CountingProvider(_StubProvider(fail=True))
    with pytest.raises(RuntimeError):
        counter.structured_completion("prompt", _EmptyModel)
    summary = counter.summary()
    assert summary["failed"] == 1
    assert summary["count"] == 1
    call = summary["calls"][0]
    assert call["ok"] is False
    assert call["error_type"] == "RuntimeError"
    assert "sk-abcdefgh12345678" not in call["error"]
    assert "[redacted]" in call["error"]


def test_counting_provider_is_concurrency_safe() -> None:
    counter = CountingProvider(_StubProvider())

    def _call(_: int) -> None:
        counter.structured_completion("p", _EmptyModel)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_call, range(40)))
    summary = counter.summary()
    assert summary["count"] == 40
    assert sorted(c["index"] for c in summary["calls"]) == list(range(1, 41))


def test_counting_mock_provider_stays_a_mock() -> None:
    counter = CountingMockProvider()
    assert isinstance(counter, MockLLMProvider)
    out = counter.structured_completion("prompt", _EmptyModel)
    assert isinstance(out, _EmptyModel)
    assert counter.call_count() == 1
    summary = counter.summary()
    assert summary["is_mock"] is True
    assert summary["count"] == 1


def test_counting_provider_rejects_non_providers() -> None:
    with pytest.raises(TypeError):
        CountingProvider(object())


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


def test_sanitize_url_strips_query_fragment_and_credentials() -> None:
    assert sanitize_url("https://api.tavily.com/search?api_key=SECRET#frag") == (
        "https://api.tavily.com/search"
    )
    assert sanitize_url("https://user:pass@example.com/a/b?x=1") == "https://example.com/a/b"
    assert sanitize_url("") == ""
    assert sanitize_url("javascript:alert(1)") == "[relative-url]"
    assert domain_of("https://docs.example.com/x?y=1") == "docs.example.com"


def test_redact_text_masks_secrets_and_truncates() -> None:
    assert "sk-abcdefgh12345678" not in redact_text("key sk-abcdefgh12345678 leaked")
    assert "Bearer" not in redact_text("Authorization: Bearer abcdefghijklmnop")
    assert "[redacted]" in redact_text("api_key=supersecretvalue")
    assert len(redact_text("x" * 500, limit=50)) == 50


# ---------------------------------------------------------------------------
# Metrics collection + derived concurrency
# ---------------------------------------------------------------------------


def _synthetic_session() -> SimpleNamespace:
    trace = ExecutionTrace("run_synthetic")
    trace.record("TASK_STARTED", message="start")
    trace.record(
        "TOOL_CALLED",
        agent_id="a1",
        message="web_search (web)",
        tool="web_search",
        tool_kind="web",
        offline=False,
        error="",
    )
    trace.record(
        "TOOL_CALLED",
        agent_id="a2",
        message="web_search (offline fallback)",
        tool="web_search",
        tool_kind="offline_fallback",
        offline=True,
        error="web search failed: TimeoutError",
    )
    trace.record("ARTIFACT_REJECTED", agent_id="a2", message="missing evidence")
    trace.record("SYNTHESIS_FAILED", message="Synthesis could not produce a valid result")

    session = SimpleNamespace(
        run_id="run_synthetic",
        task="synthetic task",
        status="success",
        started_at=100.0,
        finished_at=112.5,
        error=None,
        plan=SimpleNamespace(
            agents=[
                SimpleNamespace(
                    id="a1",
                    role=SimpleNamespace(
                        name="Agent One",
                        goal="do the thing",
                        capabilities=[CapabilityName.MARKET_RESEARCH],
                    ),
                    tools=["web_search"],
                )
            ],
            execution_layers=[["a1"]],
            topology=SimpleNamespace(
                edges=[SimpleNamespace(source="a1", target="a2")], type="hierarchical"
            ),
        ),
        agent_results={
            "a1": AgentResult(
                agent_id="a1",
                status=ExecutionStatus.SUCCESS,
                started_at=100.0,
                finished_at=104.0,
                attempt=2,
            )
        },
        artifacts=[],
        final_artifact=None,
        synthesis_bundle=None,
        trace=trace,
    )
    session.agent_names = lambda: {"a1": "Agent One"}  # type: ignore[assignment]
    return session


def test_collect_metrics_maps_real_fields() -> None:
    metrics = collect_metrics(
        _synthetic_session(),
        scenario_id="A",
        mode="offline",
        provider=None,
        counting=None,
        measured_elapsed=12.5,
    )
    assert metrics["run_id"] == "run_synthetic"
    assert metrics["team"]["agent_count"] == 1
    assert metrics["team"]["agents"][0]["name"] == "Agent One"
    assert metrics["team"]["agents"][0]["capabilities"] == ["market_research"]
    assert metrics["team"]["dag"]["layer_count"] == 1
    assert metrics["team"]["dag"]["edge_count"] == 1
    assert metrics["execution"]["counts"]["success"] == 1
    assert metrics["execution"]["retry_total"] == 1  # attempt 2 => 1 retry
    assert metrics["execution"]["total_elapsed_seconds"] == 12.5
    assert metrics["tools"]["total"] == 2
    assert metrics["tools"]["by_kind"]["web"] == 1
    assert metrics["tools"]["by_kind"]["offline_fallback"] == 1
    assert metrics["tools"]["failures"] == 1
    assert metrics["artifacts"]["rejected_count"] == 1
    # Synthesis failed => degraded, never reported as fine.
    assert metrics["synthesis"]["available"] is False
    assert metrics["synthesis"]["degraded"] is True
    assert metrics["truth"]["is_real_llm"] is False
    assert metrics["truth"]["has_offline_fallback"] is True
    assert metrics["truth"]["is_valid_real_e2e"] is False
    # Unavailable metrics are declared, not guessed.
    assert metrics["unavailable_metrics"]["token_usage"]
    assert metrics["unavailable_metrics"]["llm_call_count"]


def test_max_concurrency_is_derived_and_labelled() -> None:
    rows = [
        {"started_at": 0.0, "finished_at": 2.0, "attempts": []},
        {"started_at": 1.0, "finished_at": 3.0, "attempts": []},
        {"started_at": 5.0, "finished_at": 6.0, "attempts": []},
    ]
    result = max_concurrency_from_results(rows)
    assert result["value"] == 2
    assert result["is_derived"] is True
    assert "derived" in result["note"]


def test_max_concurrency_handles_attempts_and_empty() -> None:
    rows = [
        {
            "started_at": None,
            "finished_at": None,
            "attempts": [
                {"started_at": 1.0, "finished_at": 4.0},
                {"started_at": 2.0, "finished_at": 5.0},
            ],
        }
    ]
    assert max_concurrency_from_results(rows)["value"] == 2
    empty = max_concurrency_from_results([])
    assert empty["value"] is None and empty["is_derived"] is True


# ---------------------------------------------------------------------------
# Truth determination
# ---------------------------------------------------------------------------


def test_truth_mock_provider_is_never_a_real_e2e() -> None:
    truth = determine_truth(
        provider=MockLLMProvider(),
        tool_metrics={"by_kind": {"offline_mock": 4}},
        llm_call_count=None,
        provider_fallback=False,
        synthesis_degraded=False,
        core_data_present=True,
    )
    assert truth["is_real_llm"] is False
    assert truth["is_valid_real_e2e"] is False
    assert truth["verdict"] == "not_real_llm"


def test_truth_none_provider_is_mock() -> None:
    truth = determine_truth(
        provider=None,
        tool_metrics={"by_kind": {}},
        llm_call_count=None,
        provider_fallback=False,
        synthesis_degraded=False,
        core_data_present=True,
    )
    assert truth["is_mock"] is True
    assert truth["provider_instance_provided"] is False
    assert "MockLLMProvider" in truth["provider_type"]


def test_truth_valid_real_run() -> None:
    truth = determine_truth(
        provider=_RealStub(),
        tool_metrics={"by_kind": {"web": 3, "local": 1}},
        llm_call_count=6,
        provider_fallback=False,
        synthesis_degraded=False,
        core_data_present=True,
    )
    assert truth["is_real_llm"] is True
    assert truth["is_real_web_search"] is True
    assert truth["is_valid_real_e2e"] is True
    assert truth["verdict"] == "valid_real_e2e"
    assert truth["reasons"] == []


@pytest.mark.parametrize(
    ("kwargs", "verdict"),
    [
        ({"provider_fallback": True}, "invalid_provider_fallback"),
        ({"tool_metrics": {"by_kind": {"offline_mock": 5}}}, "invalid_missing_real_web_search"),
        ({"tool_metrics": {"by_kind": {"web": 1, "offline_fallback": 2}}}, "degraded_partial"),
        ({"synthesis_degraded": True}, "degraded_partial"),
        ({"core_data_present": False}, "invalid_missing_core_data"),
        ({"llm_call_count": 0}, "not_real_llm"),
    ],
)
def test_truth_degraded_and_invalid_variants(kwargs: dict, verdict: str) -> None:
    base = {
        "provider": _RealStub(),
        "tool_metrics": {"by_kind": {"web": 2}},
        "llm_call_count": 4,
        "provider_fallback": False,
        "synthesis_degraded": False,
        "core_data_present": True,
    }
    base.update(kwargs)
    truth = determine_truth(**base)  # type: ignore[arg-type]
    assert truth["verdict"] == verdict
    assert truth["is_valid_real_e2e"] is False
    assert truth["reasons"]


def test_truth_all_searches_offline_flag() -> None:
    truth = determine_truth(
        provider=_RealStub(),
        tool_metrics={"by_kind": {"offline_mock": 3, "offline_fallback": 1}},
        llm_call_count=3,
        provider_fallback=False,
        synthesis_degraded=False,
        core_data_present=True,
    )
    assert truth["all_searches_offline"] is True
    assert truth["has_offline_fallback"] is True


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_write_json_never_loses_the_record(tmp_path: Path) -> None:
    target = tmp_path / "metrics.json"
    errors = run_scenario.write_json(target, {"ok": 1, "odd": object(), "set": {1, 2}})
    assert errors == []
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ok"] == 1
    assert "non-serializable" in payload["odd"]
    assert isinstance(payload["set"], list)


def test_write_json_survives_broken_objects(tmp_path: Path) -> None:
    class Broken:
        def model_dump(self) -> dict:
            raise ValueError("nope")

        def __repr__(self) -> str:
            return "<broken>"

    target = tmp_path / "broken.json"
    errors = run_scenario.write_json(target, {"b": Broken()})
    assert target.exists()
    assert errors == []


# ---------------------------------------------------------------------------
# CLI guards — default offline, real mode disabled
# ---------------------------------------------------------------------------


def test_cli_rejects_illegal_budgets() -> None:
    for argv in (
        ["--runs", "0"],
        ["--max-tool-calls", "0"],
        ["--max-iterations", "0"],
        ["--timeout", "0"],
        ["--max-total-minutes", "0"],
        ["--max-llm-calls", "0"],
    ):
        with pytest.raises(SystemExit):
            run_scenario.main(["--prepare-only", *argv])


def test_cli_default_mode_is_offline() -> None:
    args = run_scenario.build_parser().parse_args(["--scenario", "A"])
    assert args.mode == "offline"
    assert args.confirm_real is False
    assert args.runs == 1
    assert args.max_tool_calls == 6
    assert args.max_iterations == 4
    assert args.timeout == 300.0
    assert args.max_total_minutes == 10.0
    assert args.max_llm_calls == 20


def test_cli_prepare_only_does_not_execute(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    code = run_scenario.main(
        ["--scenario", "A", "--prepare-only", "--out", str(tmp_path / "never")]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "prepare-only" in out
    assert not (tmp_path / "never").exists()


def test_cli_real_mode_requires_confirm() -> None:
    with pytest.raises(SystemExit):
        run_scenario.main(["--scenario", "A", "--mode", "real", "--runs", "1"])


def test_cli_real_mode_is_disabled_in_phase_2() -> None:
    assert run_scenario.REAL_EXECUTION_ENABLED is False
    with pytest.raises(SystemExit):
        run_scenario.main(["--scenario", "A", "--mode", "real", "--confirm-real", "--runs", "1"])


def test_baseline_real_mode_is_disabled_in_phase_2() -> None:
    with pytest.raises(SystemExit):
        single_agent_baseline.main(["--scenario", "A", "--mode", "real", "--confirm-real"])


# ---------------------------------------------------------------------------
# Offline end-to-end self-tests (no network, no credentials)
# ---------------------------------------------------------------------------


def test_offline_run_produces_full_record(tmp_path: Path) -> None:
    code = run_scenario.main(
        ["--scenario", "A", "--runs", "1", "--mode", "offline", "--out", str(tmp_path)]
    )
    assert code == 0
    batch = json.loads(next(tmp_path.glob("*/batch.json")).read_text(encoding="utf-8"))
    run = batch["runs"][0]
    assert run["truth"]["is_real_llm"] is False
    assert run["truth"]["is_valid_real_e2e"] is False
    assert run["metrics"]["agent_count"] >= 1
    run_dir = Path(run["dir"])
    for name in ("task.txt", "metrics.json", "team.json", "dag.json", "trace.json", "report.md"):
        assert (run_dir / name).exists(), name
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["truth"]["verdict"] == "not_real_llm"
    assert metrics["synthesis"]["available"] is True  # offline synthesis still runs


def test_offline_run_never_touches_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with stray real-looking credentials in the env, offline stays offline."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("network call attempted during an offline run")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    for key, value in (
        ("AUTOTEAM_LLM_PROVIDER", "openai"),
        ("AUTOTEAM_API_KEY", "fake-key"),
        ("AUTOTEAM_WEB_SEARCH_URL", "https://api.tavily.com/search"),
        ("AUTOTEAM_WEB_SEARCH_API_KEY", "fake-key"),
    ):
        monkeypatch.setenv(key, value)

    code = run_scenario.main(
        ["--scenario", "A", "--runs", "1", "--mode", "offline", "--out", str(tmp_path)]
    )
    assert code == 0
    batch = json.loads(next(tmp_path.glob("*/batch.json")).read_text(encoding="utf-8"))
    run = batch["runs"][0]
    assert run["truth"]["is_real_llm"] is False
    assert run["metrics"]["tools_by_kind"].get("web", 0) == 0
    assert run["metrics"]["tools_by_kind"].get("offline_fallback", 0) == 0


def test_offline_sources_are_not_faked(tmp_path: Path) -> None:
    code = run_scenario.main(
        ["--scenario", "A", "--runs", "1", "--mode", "offline", "--out", str(tmp_path)]
    )
    assert code == 0
    run = json.loads(next(tmp_path.glob("*/batch.json")).read_text(encoding="utf-8"))["runs"][0]
    sources = json.loads(
        (Path(run["dir"]) / "sources.json").read_text(encoding="utf-8")
    )
    for item in sources["items"]:
        assert item["source_type"] != "web", "offline run must not claim a live web source"
        assert item["url"] == "" or item["url"].startswith(("http://", "https://"))


def test_baseline_offline_runs_with_same_tools(tmp_path: Path) -> None:
    code = single_agent_baseline.main(
        ["--scenario", "A", "--mode", "offline", "--out", str(tmp_path)]
    )
    assert code == 0
    run_dir = next(tmp_path.glob("*/"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["baseline"] is True
    assert metrics["agent_count"] == 1
    assert metrics["provider"]["is_real_llm"] is False
    # Regression: the resolved provider drives the tool mode, so an offline
    # baseline must never report live tool kinds.
    assert set(metrics["tools"]["by_kind"]) <= {"offline_mock"}
    assert (run_dir / "report.md").exists()


class _EmptyModel(BaseModel):
    value: str = ""
