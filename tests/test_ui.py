"""Day 6 tests for the presentation layer.

These tests cover the pure-Python service functions and the offline guarantee.
They deliberately do not assert Streamlit HTML details.
"""

import asyncio
import importlib
import os
from pathlib import Path

import pytest

from app.demo.render import layout_positions, render_timeline_html, render_topology_svg
from app.demo.service import (
    FailureMode,
    RunConfig,
    build_candidates,
    build_team,
    evaluate_runs,
    run_all,
    run_topology,
    suggest_failure_agent,
    topology_summary,
)
from app.demo.tasks import DEFAULT_TASK_DESCRIPTION, DEMO_TASKS, find_demo_task
from app.models.topology import TopologyType
from app.scheduler.models import ExecutionStatus
from app.topology.validator import TopologyValidator

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(coroutine):
    return asyncio.run(coroutine)


def team_for(description: str = DEFAULT_TASK_DESCRIPTION):
    return build_team(description)


def test_ui_module_imports() -> None:
    pytest.importorskip("streamlit")
    module = importlib.import_module("app.demo.app")
    assert callable(module.main)


def test_ui_entrypoint_exists() -> None:
    entrypoint = REPO_ROOT / "app" / "ui.py"
    assert entrypoint.exists()
    assert "streamlit run app/ui.py" in entrypoint.read_text(encoding="utf-8")


def test_demo_tasks_are_unique_and_loadable() -> None:
    labels = [task.label for task in DEMO_TASKS]
    assert len(labels) == len(set(labels))
    assert DEMO_TASKS[0].description == DEFAULT_TASK_DESCRIPTION
    assert find_demo_task("Deep Market Study") is not None
    assert find_demo_task("Custom") is None


def test_default_task_loads_into_team_formation() -> None:
    team = team_for()
    assert team.task.description == DEFAULT_TASK_DESCRIPTION
    assert team.capabilities
    assert len(team.agents) == len(team.agent_ids())
    assert set(team.labels()) == set(team.agent_ids())


def test_team_formation_is_offline_and_rule_based(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    team = team_for()
    assert os.environ.get("LLM_API_KEY") is None
    assert team.analysis.confidence == 0.5


def test_topology_generation_reuses_validated_candidates() -> None:
    team = team_for("Research the AI agent market, analyze competitors and pricing, "
                    "and write a market report.")
    candidates = build_candidates(team)
    assert [item.type for item in candidates] == [
        TopologyType.CHAIN,
        TopologyType.STAR,
        TopologyType.HIERARCHICAL,
    ]
    validator = TopologyValidator()
    for topology in candidates:
        validator.validate(topology)
        summary = topology_summary(topology)
        assert summary["agents"] == len(team.agents)
        assert summary["steps"] >= 1
        assert 0.0 < summary["parallelism"] <= 1.0


def test_topology_summary_reports_structural_parallelism() -> None:
    team = team_for("Research the AI agent market, analyze competitors and pricing, "
                    "and write a market report.")
    summaries = {item.type: topology_summary(item) for item in build_candidates(team)}
    assert summaries[TopologyType.CHAIN]["parallelism"] < summaries[
        TopologyType.STAR
    ]["parallelism"]
    assert summaries[TopologyType.CHAIN]["steps"] > summaries[TopologyType.STAR]["steps"]


def test_suggest_failure_agent_prefers_a_node_with_dependencies() -> None:
    team = team_for("Research the AI agent market, analyze competitors and pricing, "
                    "and write a market report.")
    candidates = build_candidates(team)
    target = suggest_failure_agent(candidates[0])
    assert target in candidates[0].agents
    assert any(edge.source == target for edge in candidates[0].edges)


def test_run_all_succeeds_without_failures() -> None:
    team = team_for()
    runs = run(run_all(team, build_candidates(team), RunConfig(delay=0.001)))
    assert len(runs) == 3
    for topology_run in runs:
        assert set(topology_run.results) == set(topology_run.topology.agents)
        assert all(
            item.status is ExecutionStatus.SUCCESS for item in topology_run.results.values()
        )
        assert topology_run.replan_events == []


def test_failure_simulation_retries_then_succeeds() -> None:
    team = team_for()
    candidates = build_candidates(team)
    target = suggest_failure_agent(candidates[0])
    config = RunConfig(
        delay=0.001, failure_mode=FailureMode.RETRY_SUCCESS, failure_agent_id=target
    )
    topology_run = run(run_topology(team, candidates[0], config))
    result = topology_run.results[target]
    assert result.status is ExecutionStatus.SUCCESS
    assert result.attempt == 2
    assert len(result.attempts) == 2
    assert result.attempts[0].status is ExecutionStatus.FAILED
    assert topology_run.retried_agents() == [target]


def test_failure_simulation_exhausts_retries_and_skips_downstream() -> None:
    team = team_for()
    candidates = build_candidates(team)
    target = suggest_failure_agent(candidates[0])
    config = RunConfig(
        delay=0.001, failure_mode=FailureMode.RETRY_EXHAUSTED, failure_agent_id=target
    )
    topology_run = run(run_topology(team, candidates[0], config))
    assert topology_run.results[target].status is ExecutionStatus.FAILED
    assert any(
        item.status is ExecutionStatus.SKIPPED for item in topology_run.results.values()
    )
    skipped = next(
        agent_id
        for agent_id, item in topology_run.results.items()
        if item.status is ExecutionStatus.SKIPPED
    )
    assert topology_run.skip_reason(skipped).startswith("Skipped because")
    assert topology_run.replan_events


def test_evaluation_pipeline_produces_metric_specific_comparison() -> None:
    team = team_for("Research the AI agent market, analyze competitors and pricing, "
                    "and write a market report.")
    candidates = build_candidates(team)
    runs = run(run_all(team, candidates, RunConfig(delay=0.001)))
    comparison = evaluate_runs(runs)
    assert len(comparison.evaluations) == 3
    assert comparison.best_by_duration
    assert comparison.highest_parallelism
    assert comparison.best_by_success_rate
    assert comparison.most_reliable
    assert [item.metrics.topology_type for item in comparison.evaluations] == [
        item.type for item in candidates
    ]
    star = next(item for item in comparison.evaluations if item.topology_type is TopologyType.STAR)
    chain = next(
        item for item in comparison.evaluations if item.topology_type is TopologyType.CHAIN
    )
    assert star.metrics.parallelism > chain.metrics.parallelism


def test_evaluation_records_recovery_when_retry_succeeds() -> None:
    team = team_for()
    candidates = build_candidates(team)
    target = suggest_failure_agent(candidates[0])
    config = RunConfig(
        delay=0.001, failure_mode=FailureMode.RETRY_SUCCESS, failure_agent_id=target
    )
    runs = run(run_all(team, candidates, config))
    comparison = evaluate_runs(runs)
    assert sum(item.metrics.recovery_count for item in comparison.evaluations) >= 1
    assert all(item.metrics.success_rate == 1.0 for item in comparison.evaluations)


def test_evaluation_reuses_the_displayed_run_instead_of_replaying_it() -> None:
    team = team_for()
    runs = run(run_all(team, build_candidates(team), RunConfig(delay=0.001)))
    for topology_run, evaluation in zip(runs, evaluate_runs(runs).evaluations):
        assert evaluation.metrics.duration == topology_run.duration
        assert evaluation.metrics.max_concurrency == topology_run.max_concurrency


def test_topology_svg_contains_every_agent_and_arrowheads() -> None:
    team = team_for()
    labels = team.labels()
    topology = build_candidates(team)[1]
    svg = render_topology_svg(topology, labels)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    for agent_id in topology.agents:
        assert labels[agent_id] in svg
    assert "marker-end" in svg
    positions, width, height = layout_positions(topology)
    assert set(positions) == set(topology.agents)
    assert width > 0 and height > 0


def test_timeline_html_renders_every_agent() -> None:
    team = team_for()
    labels = team.labels()
    topology = build_candidates(team)[0]
    topology_run = run(run_topology(team, topology, RunConfig(delay=0.001)))
    html = render_timeline_html(topology_run, labels)
    for agent_id in topology.agents:
        assert labels[agent_id] in html
    assert "SUCCESS" in html
