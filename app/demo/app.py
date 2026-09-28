"""Streamlit page for AutoTeam (Day 6).

This module only renders. Every orchestration call lives in ``app.demo.service``,
so the same pipeline can be exercised by tests without a browser.
"""

import asyncio

import streamlit as st
from streamlit.components.v1 import html as render_html

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
from app.demo.tasks import DEFAULT_TASK_DESCRIPTION, demo_task_labels, find_demo_task
from app.evaluation.models import TopologyComparison
from app.models.topology import Topology

TEAM_KEY = "autoteam_team"
CANDIDATES_KEY = "autoteam_candidates"
RUNS_KEY = "autoteam_runs"
COMPARISON_KEY = "autoteam_comparison"

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


def _apply_demo_choice() -> None:
    task = find_demo_task(st.session_state.get("demo_choice", ""))
    if task is not None:
        st.session_state["task_text"] = task.description


def _reset_downstream() -> None:
    for key in (CANDIDATES_KEY, RUNS_KEY, COMPARISON_KEY):
        st.session_state.pop(key, None)


def _render_header() -> None:
    st.title("AutoTeam")
    st.markdown(
        "<div class='at-sub'>Adaptive Multi-Agent Orchestration — "
        "Task → Team → Topology → Execution → Recovery → Evaluation</div>",
        unsafe_allow_html=True,
    )


def _render_task_section() -> str:
    st.subheader("1 · Task")
    labels = ["Custom", *demo_task_labels()]
    if "demo_choice" not in st.session_state:
        st.session_state["demo_choice"] = labels[1]
    if "task_text" not in st.session_state:
        st.session_state["task_text"] = DEFAULT_TASK_DESCRIPTION
    st.radio(
        "Preset",
        labels,
        horizontal=True,
        key="demo_choice",
        on_change=_apply_demo_choice,
    )
    st.text_area("Task description", key="task_text", height=88)
    if st.button("Analyze & Build Team", type="primary"):
        st.session_state[TEAM_KEY] = build_team(st.session_state["task_text"])
        _reset_downstream()
    return st.session_state["task_text"]


def _render_team(team: TeamBlueprint) -> None:
    st.subheader("2 · Team Formation")
    analysis_column, team_column = st.columns([1, 2])
    with analysis_column:
        st.caption("TASK ANALYSIS")
        st.markdown(
            f"**Complexity** `{team.analysis.complexity.value}` · "
            f"**Confidence** `{team.analysis.confidence:.2f}`"
        )
        st.markdown("**Capabilities**")
        for capability in team.capabilities:
            st.markdown(f"- `{capability}`")
        st.caption(team.analysis.reasoning)
    with team_column:
        st.caption(f"AGENT TEAM — {len(team.agents)} agents")
        columns = st.columns(min(len(team.agents), 4) or 1)
        for index, agent in enumerate(team.agents):
            with columns[index % len(columns)]:
                with st.container(border=True):
                    st.markdown(f"**{index + 1}. {agent.role.name}**")
                    st.caption(agent.role.goal)
                    st.markdown(
                        " ".join(f"`{item.value}`" for item in agent.role.capabilities)
                    )
                    if agent.tools:
                        st.caption("Tools: " + ", ".join(agent.tools))
    if len(team.agents) < 3:
        st.info(
            "This task produced a small team, so the three topologies look similar. "
            "Richer descriptions allocate more capabilities — try the "
            "**Deep Market Study** preset."
        )


def _render_candidates(candidates: list[Topology]) -> None:
    st.subheader("3 · Candidate Topologies")
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
                        ("Agents", str(summary["agents"])),
                        ("Edges", str(summary["edges"])),
                        ("Steps", str(summary["steps"])),
                        ("Parall.", f"{summary['parallelism']:.0%}"),
                    ),
                ):
                    cell.markdown(
                        f"<div class='at-label'>{label}</div>"
                        f"<div class='at-value'>{value}</div>",
                        unsafe_allow_html=True,
                    )


def _render_graph(candidates: list[Topology], team: TeamBlueprint) -> None:
    st.subheader("4 · Topology Graph")
    if not candidates:
        st.warning("No valid topology was generated for this team.")
        return
    labels = team.labels()
    options = [topology.type.value.upper() for topology in candidates]
    if st.session_state.get("graph_choice") not in options:
        st.session_state["graph_choice"] = options[0]
    choice = st.radio("Topology", options, horizontal=True, key="graph_choice")
    topology = next(item for item in candidates if item.type.value.upper() == choice)
    _, _, height = layout_positions(topology)
    render_html(render_topology_svg(topology, labels), height=int(height) + 8, scrolling=False)
    summary = topology_summary(topology)
    st.caption("Edges: " + (str(summary["edges_text"]) or "none"))


def _render_run_controls(team: TeamBlueprint, candidates: list[Topology]) -> tuple[bool, RunConfig]:
    st.subheader("5 · Execution")
    with st.expander("Run configuration", expanded=False):
        delay = st.slider("Mock agent delay (s)", 0.0, 0.30, DEFAULT_DELAY, 0.01)
        concurrency_option = st.selectbox(
            "Max concurrency", ["unlimited", "1", "2", "4", "8"], index=0
        )
        failure_enabled = st.checkbox("Enable failure simulation")
        mode = FailureMode.NONE
        target: str | None = None
        if failure_enabled:
            scenario = st.radio(
                "Failure scenario",
                ["Retry then succeed", "Retry exhausted"],
                horizontal=True,
                key="failure_scenario",
            )
            mode = (
                FailureMode.RETRY_SUCCESS
                if scenario == "Retry then succeed"
                else FailureMode.RETRY_EXHAUSTED
            )
            agent_ids = team.agent_ids()
            suggested = suggest_failure_agent(candidates[0]) if candidates else None
            index = agent_ids.index(suggested) if suggested in agent_ids else 0
            target = st.selectbox("Failing agent", agent_ids, index=index)
    triggered = st.button("Run All Topologies", type="primary")
    concurrency = None if concurrency_option == "unlimited" else int(concurrency_option)
    return triggered, RunConfig(
        delay=delay,
        max_concurrency=concurrency,
        failure_mode=mode,
        failure_agent_id=target,
    )


def _render_runs(runs: list, labels: dict[str, str]) -> None:
    st.subheader("6 · Execution Results")
    for run in runs:
        with st.container(border=True):
            st.markdown(
                f"**{run.topology.type.value.upper()}** · {run.duration:.3f}s · "
                f"max concurrency {run.max_concurrency}"
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
                _html_table(["Agent", "Status", "Attempts", "Duration"], rows),
                unsafe_allow_html=True,
            )
            for agent_id in run.retried_agents():
                attempts = run.results[agent_id].attempts
                detail = " → ".join(
                    f"attempt {item.attempt}: {item.status.value.upper()}" for item in attempts
                )
                st.caption(f"{labels.get(agent_id, agent_id)} — {detail}")
            for agent_id in run.topology.agents:
                reason = run.skip_reason(agent_id)
                if reason:
                    st.caption(f"{labels.get(agent_id, agent_id)} — {reason}")
            for event in run.replan_events:
                st.caption(f"[REPLAN] {event}")
            render_html(
                render_timeline_html(run, labels),
                height=timeline_height(run),
                scrolling=False,
            )


def _render_evaluation(comparison: TopologyComparison) -> None:
    st.subheader("7 · Evaluation")
    evaluations = comparison.evaluations
    headers = ["Metric", *[item.topology_type.value.upper() for item in evaluations]]
    rows = [
        ["Duration (s)", *[f"{item.metrics.duration:.3f}" for item in evaluations]],
        ["Success Rate", *[f"{item.metrics.success_rate:.0%}" for item in evaluations]],
        ["Failure Rate", *[f"{item.metrics.failure_rate:.0%}" for item in evaluations]],
        ["Skipped Agents", *[str(item.metrics.skipped_count) for item in evaluations]],
        ["Recovered Agents", *[str(item.metrics.recovery_count) for item in evaluations]],
        ["Max Concurrency", *[str(item.metrics.max_concurrency) for item in evaluations]],
        ["Parallelism", *[f"{item.metrics.parallelism:.0%}" for item in evaluations]],
        [
            "Agents / Edges",
            *[f"{item.metrics.agent_count} / {item.metrics.edge_count}" for item in evaluations],
        ],
    ]
    st.markdown(_html_table(headers, rows), unsafe_allow_html=True)
    with st.expander("Per-topology observations"):
        for item in evaluations:
            st.markdown(f"**{item.topology_type.value.upper()}**")
            if item.strengths:
                st.caption("Strengths: " + ", ".join(item.strengths))
            if item.weaknesses:
                st.caption("Weaknesses: " + ", ".join(item.weaknesses))
            if item.observations:
                st.caption("Observed: " + ", ".join(item.observations))

    st.subheader("8 · Comparison")
    leaders = [
        ("Shortest Duration", comparison.best_by_duration),
        ("Highest Success Rate", comparison.best_by_success_rate),
        ("Highest Parallelism", comparison.highest_parallelism),
        ("Most Reliable (lowest failure rate)", comparison.most_reliable),
    ]
    for label, values in leaders:
        text = ", ".join(item.value for item in values) if values else "n/a"
        st.markdown(f"- **{label}:** `{text}`")
    st.caption(
        "Metric-specific results only. AutoTeam does not compute a weighted score "
        "and does not declare a single overall winner."
    )


def _candidates(team: TeamBlueprint) -> list[Topology]:
    if CANDIDATES_KEY not in st.session_state:
        st.session_state[CANDIDATES_KEY] = build_candidates(team)
    return st.session_state[CANDIDATES_KEY]


def main() -> None:
    st.set_page_config(page_title="AutoTeam", layout="centered")
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
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
        with st.spinner("Executing topologies..."):
            runs = asyncio.run(run_all(team, candidates, config))
        st.session_state[RUNS_KEY] = runs
        st.session_state[COMPARISON_KEY] = evaluate_runs(runs)
    if RUNS_KEY in st.session_state:
        _render_runs(st.session_state[RUNS_KEY], team.labels())
    if COMPARISON_KEY in st.session_state:
        _render_evaluation(st.session_state[COMPARISON_KEY])
