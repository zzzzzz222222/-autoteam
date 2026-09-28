"""Day 6 tests for the presentation layer.

These tests cover the pure-Python service functions and the offline guarantee.
They deliberately do not assert Streamlit HTML details.
"""

import asyncio
import importlib
import os
from pathlib import Path

import pytest

from app.demo.i18n import (
    EN,
    ROLE_GOALS,
    STRINGS,
    ZH,
    capability_label,
    complexity_label,
    is_supported,
    observation_label,
    role_goal,
    role_name,
    translate,
)
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
from app.demo.tasks import (
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_TASK_DESCRIPTION_ZH,
    DEMO_TASKS,
    default_task_description,
    find_demo_task,
    localized_description,
    localized_labels,
)
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


def test_timeline_adapts_to_light_and_dark_themes() -> None:
    team = team_for()
    labels = team.labels()
    topology = build_candidates(team)[0]
    topology_run = run(run_topology(team, topology, RunConfig(delay=0.001)))
    light = render_timeline_html(topology_run, labels, dark=False)
    dark = render_timeline_html(topology_run, labels, dark=True)
    assert light != dark
    assert "#374151" in light and "#374151" not in dark
    assert "#E5E7EB" in dark and "#E5E7EB" not in light


def test_page_css_stays_theme_agnostic() -> None:
    """Guard against the regression where hardcoded light-theme colors made the
    tables invisible on a dark Streamlit theme."""
    pytest.importorskip("streamlit")
    module = importlib.import_module("app.demo.app")
    css = module._PAGE_CSS
    for hardcoded in ("#111827", "#6B7280", "#E5E7EB", "#F1F3F7", "#EEF0F3"):
        assert hardcoded not in css, f"hardcoded theme color {hardcoded!r} is back"
    assert "inherit" in css


# ---------------------------------------------------------------------------
# i18n (Task #15): every presentation string must localize without changing the
# underlying demo outcome. Core identifiers (capabilities, roles, statuses,
# topology types) stay English because Day 1-5 code treats them as identifiers.
# ---------------------------------------------------------------------------


def test_i18n_every_string_has_both_locales() -> None:
    for key, entry in STRINGS.items():
        assert EN in entry and ZH in entry, f"locale gap in STRINGS[{key!r}]"
        assert isinstance(entry[EN], str) and isinstance(entry[ZH], str)


def test_translate_falls_back_and_localizes() -> None:
    assert translate("section.task", EN) == "1 · Task"
    assert translate("section.task", ZH) == "1 · 任务"
    assert translate("section.task") == "1 · Task"  # default locale is EN
    assert translate("__unknown_key__") == "__unknown_key__"  # unknown -> key itself


def test_complexity_capability_role_observation_labels() -> None:
    assert complexity_label("high", ZH) == "高"
    assert complexity_label("high", EN) == "high"
    assert capability_label("market_research", ZH) == "市场调研"
    assert capability_label("market_research", EN) == "market_research"
    assert role_name("Market Researcher", ZH) == "市场研究员"
    assert role_name("Market Researcher", EN) == "Market Researcher"
    assert (
        observation_label("all agents completed successfully", ZH)
        == "全部智能体执行成功"
    )
    assert (
        observation_label("all agents completed successfully", EN)
        == "all agents completed successfully"
    )
    assert is_supported(EN) and is_supported(ZH)
    assert not is_supported("fr")


def test_role_goal_uses_english_dict_for_en_and_chinese_goal_for_zh() -> None:
    team = team_for()
    agent = team.agents[0]
    zh_goal = role_goal(agent.role.name, agent.role.goal, ZH)
    en_goal = role_goal(agent.role.name, agent.role.goal, EN)
    assert zh_goal == agent.role.goal  # stored goal is Chinese
    assert en_goal == ROLE_GOALS.get(agent.role.name, agent.role.goal)
    assert en_goal != zh_goal  # the two locales differ


def test_find_demo_task_accepts_chinese_label() -> None:
    assert find_demo_task("市场研究") is not None
    assert find_demo_task("市场研究").label == "Market Research"
    assert find_demo_task("SaaS 上线计划") is not None
    assert find_demo_task("SaaS 上线计划").label == "SaaS Launch Plan"
    assert find_demo_task("市場研究") is None  # traditional / wrong form


def test_localized_labels_and_descriptions_zh() -> None:
    zh_labels = localized_labels(ZH)
    assert "市场研究" in zh_labels and "Market Research" not in zh_labels
    en_labels = localized_labels(EN)
    assert "Market Research" in en_labels
    task = find_demo_task("Market Research")
    assert localized_description(task, ZH) == DEFAULT_TASK_DESCRIPTION_ZH
    assert localized_description(task, EN) == DEFAULT_TASK_DESCRIPTION
    assert default_task_description(ZH) == DEFAULT_TASK_DESCRIPTION_ZH
    assert default_task_description(EN) == DEFAULT_TASK_DESCRIPTION


def test_chinese_and_english_demo_tasks_build_identical_teams() -> None:
    """The core i18n invariant: switching the UI language never changes what
    team / topology the demo allocates, so results stay comparable."""
    for task in DEMO_TASKS:
        en_team = build_team(task.description)
        zh_team = build_team(task.description_zh)
        assert sorted(en_team.capabilities) == sorted(
            zh_team.capabilities
        ), f"capability mismatch for {task.label}"
        assert [agent.role.name for agent in en_team.agents] == [
            agent.role.name for agent in zh_team.agents
        ], f"agent mismatch for {task.label}"


def test_ui_renders_in_english_by_default() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(REPO_ROOT / "app" / "ui.py")).run()
    assert not at.exception
    assert any("1 · Task" in (item.value or "") for item in at.subheader)


def test_ui_switches_to_chinese_on_language_radio() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(REPO_ROOT / "app" / "ui.py")).run()
    language_radio = next(
        item for item in at.radio if item.key == "autoteam_language"
    )
    language_radio.set_value("中文").run()
    assert not at.exception
    assert any("1 · 任务" in (item.value or "") for item in at.subheader)
    # The same demo content re-localizes: a known Chinese capability appears.
    assert any(
        "市场调研" in (item.value or "") or "市场研究" in (item.value or "")
        for item in at.markdown
    )


def test_live_view_renders_initial_state() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(REPO_ROOT / "app" / "ui_live.py")).run(timeout=30)
    assert not at.exception
    assert any("AI Team Live View" in (item.value or "") for item in at.title)
    # Before running, the page shows the offline-mode hint, not a report.
    assert any("离线" in (item.value or "") for item in at.info)
