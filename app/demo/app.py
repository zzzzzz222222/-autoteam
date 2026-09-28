"""Streamlit page for AutoTeam (Day 6).

This module only renders. Every orchestration call lives in ``app.demo.service``,
so the same pipeline can be exercised by tests without a browser. All visible
text goes through ``app.demo.i18n`` so the page can switch between English and
Simplified Chinese without touching any Day 1-5 logic.
"""

import asyncio

import streamlit as st
from streamlit.components.v1 import html as render_html

from app.demo.i18n import (
    DEFAULT_LOCALE,
    EN,
    ZH,
    capability_label,
    complexity_label,
    observation_label,
    role_goal,
    role_name,
    translate,
)
from app.demo.render import (
    layout_positions,
    render_timeline_html,
    render_topology_svg,
    timeline_height,
)
from app.demo.service import (
    DEFAULT_DELAY,
    FailureMode,
    RunConfig,
    TeamBlueprint,
    build_candidates,
    build_team,
    evaluate_runs,
    run_all,
    suggest_failure_agent,
    topology_summary,
)
from app.demo.tasks import (
    default_task_description,
    find_demo_task,
    localized_description,
    localized_label,
    localized_labels,
)
from app.evaluation.models import TopologyComparison
from app.models.topology import Topology

TEAM_KEY = "autoteam_team"
CANDIDATES_KEY = "autoteam_candidates"
RUNS_KEY = "autoteam_runs"
COMPARISON_KEY = "autoteam_comparison"
LANG_KEY = "autoteam_language"
LOCALE_KEY = "autoteam_locale"

LANGUAGE_OPTIONS = ("English", "中文")
LANGUAGE_TO_LOCALE = {"English": EN, "中文": ZH}

STATUS_COLORS = {
    "success": "#16A34A",
    "failed": "#DC2626",
    "skipped": "#6B7280",
    "running": "#2563EB",
    "ready": "#6366F1",
    "pending": "#9CA3AF",
}

_PAGE_CSS = """
<style>
.block-container { max-width: 1080px; padding-top: 2rem; padding-bottom: 4rem; }
h1 { font-weight: 650; letter-spacing: -0.02em; margin-bottom: 0; }
.at-sub { color: #6B7280; margin-top: 0.2rem; margin-bottom: 1.6rem; font-size: 0.92rem; }
.at-label { color: #6B7280; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; }
.at-value { color: #111827; font-size: 1.02rem; font-weight: 600; }
.at-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.at-table th { text-align: left; color: #6B7280; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.05em; border-bottom: 1px solid #E5E7EB; padding: 6px 8px; font-weight: 600; }
.at-table td { padding: 6px 8px; border-bottom: 1px solid #F1F3F7; color: #111827; }
hr { border-color: #EEF0F3; }
</style>
"""


def _locale() -> str:
    return st.session_state.get(LOCALE_KEY, DEFAULT_LOCALE)


def t(key: str, **kwargs: object) -> str:
    text = translate(key, _locale())
    return text.format(**kwargs) if kwargs else text


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#6B7280")
    return f"<span style='color:{color};font-weight:600'>{status.upper()}</span>"


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_escape(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table class='at-table'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _reset_downstream() -> None:
    for key in (CANDIDATES_KEY, RUNS_KEY, COMPARISON_KEY):
        st.session_state.pop(key, None)


def _apply_demo_choice() -> None:
    task = find_demo_task(st.session_state.get("demo_choice", ""))
    if task is not None:
        st.session_state["task_text"] = localized_description(task, _locale())


def _apply_locale() -> None:
    """Re-translate the active preset and rebuild the team in the new language."""
    st.session_state[LOCALE_KEY] = LANGUAGE_TO_LOCALE.get(
        st.session_state.get(LANG_KEY, "English"), DEFAULT_LOCALE
    )
    locale = _locale()
    task = find_demo_task(st.session_state.get("demo_choice", ""))
    if task is not None:
        st.session_state["demo_choice"] = localized_label(task, locale)
        st.session_state["task_text"] = localized_description(task, locale)
    st.session_state.pop(TEAM_KEY, None)
    _reset_downstream()


def _render_header() -> None:
    header_column, language_column = st.columns([5, 2])
    with header_column:
        st.title("AutoTeam")
        st.markdown(f"<div class='at-sub'>{t('subtitle')}</div>", unsafe_allow_html=True)
    with language_column:
        st.radio(
            "Language / 语言",
            LANGUAGE_OPTIONS,
            horizontal=True,
            key=LANG_KEY,
            label_visibility="collapsed",
            on_change=_apply_locale,
        )


def _render_task_section() -> str:
    st.subheader(t("section.task"))
    options = [t("preset.custom"), *localized_labels(_locale())]
    if st.session_state.get("demo_choice") not in options:
        st.session_state["demo_choice"] = options[1]
    if "task_text" not in st.session_state:
        st.session_state["task_text"] = default_task_description(_locale())
    st.radio(
        t("preset.label"),
        options,
        horizontal=True,
        key="demo_choice",
        on_change=_apply_demo_choice,
    )
    st.text_area(t("task.text_area"), key="task_text", height=88)
    if st.button(t("task.analyze"), type="primary"):
        st.session_state[TEAM_KEY] = build_team(st.session_state["task_text"])
        _reset_downstream()
    return st.session_state["task_text"]


def _render_team(team: TeamBlueprint) -> None:
    locale = _locale()
    st.subheader(t("section.team"))
    analysis_column, team_column = st.columns([1, 2])
    with analysis_column:
        st.caption(t("analysis.caption"))
        st.markdown(
            f"**{t('analysis.complexity')}** "
            f"`{complexity_label(team.analysis.complexity.value, locale)}` · "
            f"**{t('analysis.confidence')}** `{team.analysis.confidence:.2f}`"
        )
        st.markdown(f"**{t('analysis.capabilities')}**")
        for capability in team.capabilities:
            st.markdown(f"- `{capability_label(capability, locale)}`")
        names = [capability_label(item, locale) for item in team.capabilities]
        st.caption(t("analysis.reasoning", caps=", ".join(names)))
    with team_column:
        st.caption(t("team.caption", count=len(team.agents)))
        columns = st.columns(min(len(team.agents), 4) or 1)
        for index, agent in enumerate(team.agents):
            with columns[index % len(columns)]:
                with st.container(border=True):
                    st.markdown(f"**{index + 1}. {role_name(agent.role.name, locale)}**")
                    st.caption(role_goal(agent.role.name, agent.role.goal, locale))
                    st.markdown(
                        " ".join(
                            f"`{capability_label(item.value, locale)}`"
                            for item in agent.role.capabilities
                        )
                    )
                    if agent.tools:
                        st.caption(t("team.tools") + ", ".join(agent.tools))
    if len(team.agents) < 3:
        st.info(t("team.small_hint"))


def _render_candidates(candidates: list[Topology]) -> None:
    st.subheader(t("section.topologies"))
    columns = st.columns(len(candidates) or 1)
    for column, topology in zip(columns, candidates):
        summary = topology_summary(topology)
        with column:
            with st.container(border=True):
                st.markdown(f"**{str(summary['type']).upper()}**")
                cells = st.columns(4)
                for cell, (label, value) in zip(
                    cells,
                    (
                        (t("metric.agents"), str(summary["agents"])),
                        (t("metric.edges"), str(summary["edges"])),
                        (t("metric.steps"), str(summary["steps"])),
                        (t("metric.parallelism"), f"{summary['parallelism']:.0%}"),
                    ),
                ):
                    cell.markdown(
                        f"<div class='at-label'>{label}</div>"
                        f"<div class='at-value'>{value}</div>",
                        unsafe_allow_html=True,
                    )


def _render_graph(candidates: list[Topology], team: TeamBlueprint) -> None:
    st.subheader(t("section.graph"))
    if not candidates:
        st.warning(t("graph.no_candidate"))
        return
    locale = _locale()
    labels = {
        agent_id: role_name(name, locale) for agent_id, name in team.labels().items()
    }
    options = [topology.type.value.upper() for topology in candidates]
    if st.session_state.get("graph_choice") not in options:
        st.session_state["graph_choice"] = options[0]
    choice = st.radio(t("graph.topology"), options, horizontal=True, key="graph_choice")
    topology = next(item for item in candidates if item.type.value.upper() == choice)
    _, _, height = layout_positions(topology)
    render_html(render_topology_svg(topology, labels), height=int(height) + 8, scrolling=False)
    edges_text = ", ".join(
        f"{labels.get(edge.source, edge.source)} → {labels.get(edge.target, edge.target)}"
        for edge in topology.edges
    )
    st.caption(t("graph.edges") + (edges_text or t("graph.empty_edges")))


def _render_run_controls(team: TeamBlueprint, candidates: list[Topology]) -> tuple[bool, RunConfig]:
    st.subheader(t("section.execution"))
    unlimited = t("run.concurrency.unlimited")
    retry_label = t("run.scenario.retry")
    with st.expander(t("run.config"), expanded=False):
        delay = st.slider(t("run.delay"), 0.0, 0.30, DEFAULT_DELAY, 0.01)
        concurrency_option = st.selectbox(
            t("run.concurrency"), [unlimited, "1", "2", "4", "8"], index=0
        )
        failure_enabled = st.checkbox(t("run.failure"))
        mode = FailureMode.NONE
        target: str | None = None
        if failure_enabled:
            scenario = st.radio(
                t("run.scenario"),
                [retry_label, t("run.scenario.exhausted")],
                horizontal=True,
                key="failure_scenario",
            )
            mode = (
                FailureMode.RETRY_SUCCESS
                if scenario == retry_label
                else FailureMode.RETRY_EXHAUSTED
            )
            agent_ids = team.agent_ids()
            suggested = suggest_failure_agent(candidates[0]) if candidates else None
            index = agent_ids.index(suggested) if suggested in agent_ids else 0
            target = st.selectbox(t("run.failing_agent"), agent_ids, index=index)
    triggered = st.button(t("run.button"), type="primary")
    concurrency = None if concurrency_option == unlimited else int(concurrency_option)
    return triggered, RunConfig(
        delay=delay,
        max_concurrency=concurrency,
        failure_mode=mode,
        failure_agent_id=target,
    )


def _render_runs(runs: list, labels: dict[str, str]) -> None:
    st.subheader(t("section.results"))
    for run in runs:
        with st.container(border=True):
            st.markdown(
                f"**{run.topology.type.value.upper()}** · {run.duration:.3f}s · "
                f"{t('run.max_concurrency')} {run.max_concurrency}"
            )
            rows = []
            for agent_id in run.topology.agents:
                result = run.results.get(agent_id)
                duration = (
                    f"{result.duration:.3f}s" if result is not None and result.duration else "—"
                )
                rows.append(
                    [
                        _escape(labels.get(agent_id, agent_id)),
                        _status_badge(run.status_of(agent_id)),
                        str(result.attempt) if result is not None else "0",
                        duration,
                    ]
                )
            st.markdown(
                _html_table(
                    [t("table.agent"), t("table.status"), t("table.attempts"),
                     t("table.duration")],
                    rows,
                ),
                unsafe_allow_html=True,
            )
            for agent_id in run.retried_agents():
                attempts = run.results[agent_id].attempts
                detail = " → ".join(
                    t("attempt.detail", n=item.attempt, status=item.status.value.upper())
                    for item in attempts
                )
                st.caption(f"{labels.get(agent_id, agent_id)} — {detail}")
            for agent_id in run.topology.agents:
                if run.skip_reason(agent_id):
                    st.caption(f"{labels.get(agent_id, agent_id)} — {t('run.skipped_note')}")
            for event in run.replan_events:
                st.caption(f"[REPLAN] {event}")
            render_html(
                render_timeline_html(run, labels),
                height=timeline_height(run),
                scrolling=False,
            )


def _render_evaluation(comparison: TopologyComparison) -> None:
    locale = _locale()
    st.subheader(t("section.evaluation"))
    evaluations = comparison.evaluations
    headers = [t("eval.metric"), *[item.topology_type.value.upper() for item in evaluations]]
    rows = [
        [t("eval.duration"), *[f"{item.metrics.duration:.3f}" for item in evaluations]],
        [t("eval.success_rate"), *[f"{item.metrics.success_rate:.0%}" for item in evaluations]],
        [t("eval.failure_rate"), *[f"{item.metrics.failure_rate:.0%}" for item in evaluations]],
        [t("eval.skipped"), *[str(item.metrics.skipped_count) for item in evaluations]],
        [t("eval.recovered"), *[str(item.metrics.recovery_count) for item in evaluations]],
        [t("eval.concurrency"), *[str(item.metrics.max_concurrency) for item in evaluations]],
        [t("eval.parallelism"), *[f"{item.metrics.parallelism:.0%}" for item in evaluations]],
        [
            t("eval.size"),
            *[f"{item.metrics.agent_count} / {item.metrics.edge_count}" for item in evaluations],
        ],
    ]
    st.markdown(_html_table(headers, rows), unsafe_allow_html=True)
    with st.expander(t("eval.observations")):
        for item in evaluations:
            st.markdown(f"**{item.topology_type.value.upper()}**")
            if item.strengths:
                joined = ", ".join(observation_label(x, locale) for x in item.strengths)
                st.caption(t("eval.strengths") + joined)
            if item.weaknesses:
                joined = ", ".join(observation_label(x, locale) for x in item.weaknesses)
                st.caption(t("eval.weaknesses") + joined)
            if item.observations:
                joined = ", ".join(observation_label(x, locale) for x in item.observations)
                st.caption(t("eval.observed") + joined)

    st.subheader(t("section.comparison"))
    leaders = [
        (t("cmp.shortest"), comparison.best_by_duration),
        (t("cmp.success"), comparison.best_by_success_rate),
        (t("cmp.parallel"), comparison.highest_parallelism),
        (t("cmp.reliable"), comparison.most_reliable),
    ]
    for label, values in leaders:
        text = ", ".join(item.value for item in values) if values else t("value.na")
        st.markdown(f"- **{label}:** `{text}`")
    st.caption(t("cmp.note"))


def _candidates(team: TeamBlueprint) -> list[Topology]:
    if CANDIDATES_KEY not in st.session_state:
        st.session_state[CANDIDATES_KEY] = build_candidates(team)
    return st.session_state[CANDIDATES_KEY]


def main() -> None:
    st.set_page_config(page_title="AutoTeam", layout="centered")
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    if LANG_KEY not in st.session_state:
        st.session_state[LANG_KEY] = LANGUAGE_OPTIONS[0]
    if LOCALE_KEY not in st.session_state:
        st.session_state[LOCALE_KEY] = DEFAULT_LOCALE
    _render_header()
    description = _render_task_section()
    if TEAM_KEY not in st.session_state:
        st.session_state[TEAM_KEY] = build_team(description)
    team = st.session_state[TEAM_KEY]
    _render_team(team)
    candidates = _candidates(team)
    _render_candidates(candidates)
    _render_graph(candidates, team)
    triggered, config = _render_run_controls(team, candidates)
    if triggered:
        with st.spinner(t("run.spinner")):
            runs = asyncio.run(run_all(team, candidates, config))
        st.session_state[RUNS_KEY] = runs
        st.session_state[COMPARISON_KEY] = evaluate_runs(runs)
    if RUNS_KEY in st.session_state:
        labels = {
            agent_id: role_name(name, _locale())
            for agent_id, name in team.labels().items()
        }
        _render_runs(st.session_state[RUNS_KEY], labels)
    if COMPARISON_KEY in st.session_state:
        _render_evaluation(st.session_state[COMPARISON_KEY])
