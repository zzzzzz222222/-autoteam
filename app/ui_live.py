"""Streamlit "AI Team Live View" (v0.4.0).

Renders a full Task Execution Session: run info, dynamic team, live agent
statuses, execution timeline, agent collaboration (artifact flow), intermediate
artifacts and the final readable deliverable (view + save).

The page only renders. All orchestration lives in ``app.runtime.session`` so the
same pipeline is exercised by tests without a browser. Run with:
    streamlit run app/ui_live.py
"""

from __future__ import annotations

import threading
import time

import streamlit as st

from app.runtime.session import SessionStatus, execute_task

STATUS_EMOJI = {
    "pending": "⚪",
    "running": "🟡",
    "success": "🟢",
    "failed": "🔴",
    "skipped": "⚫",
    "partial_success": "🟠",
}

DEMO_TASKS = {
    "Killer Demo — AI Agent 市场分析 + 产品方案": (
        "分析 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案。"
    ),
    "Demo B — FastAPI 电商后端设计": "设计一个 FastAPI 电商后端系统",
    "Demo C — SaaS 市场进入策略": "制定 SaaS 产品进入某行业的市场策略",
}


def _run_in_thread(session_holder: dict, task: str) -> None:
    try:
        session_holder["session"] = execute_task(task)
    except Exception as exc:  # surface to the UI rather than swallow
        session_holder["error"] = str(exc)


def _render_team(session) -> None:
    plan = session.plan
    if plan is None:
        return
    st.subheader("① 团队 · Team")
    for index, layer in enumerate(plan.execution_layers, start=1):
        names = ", ".join(
            next(a.role.name for a in plan.agents if a.id == agent_id) for agent_id in layer
        )
        st.markdown(f"并行层 {index}: **{names}**")


def _render_live(session) -> None:
    st.subheader("② 实时执行 · Live Status")
    names = session.agent_names()
    columns = st.columns(max(len(names), 1))
    for index, (agent_id, name) in enumerate(names.items()):
        result = session.agent_results.get(agent_id)
        status = result.status.value if result is not None else "running"
        with columns[index % max(len(names), 1)]:
            st.metric(label=name, value=f"{STATUS_EMOJI.get(status, '⚪')} {status}")


def _render_trace(session) -> None:
    st.subheader("③ 执行时间线 · Execution Timeline")
    for event in session.trace.events:
        agent_label = session.agent_names().get(event.agent_id, event.agent_id)
        agent = f" · {agent_label}" if event.agent_id else ""
        st.markdown(f"- `{event.event_id}` **{event.type}**{agent} — {event.message}")


def _render_artifacts(session) -> None:
    st.subheader("④ 协作与成果 · Collaboration & Artifacts")
    names = session.agent_names()
    for artifact in session.artifacts:
        deps = ", ".join(artifact.dependencies) or "—"
        with st.expander(
            f"**{artifact.title}** ({artifact.output_type.value}) by "
            f"{names.get(artifact.agent_id, artifact.agent_id)}"
        ):
            st.markdown(f"- 依赖上游: `{deps}`")
            st.markdown(
                "- 关键数据: "
                + ", ".join(f"`{k}={v}`" for k, v in artifact.structured_data.items())
                or "- 关键数据: —"
            )
            st.markdown(artifact.content)


def _render_final(session) -> None:
    st.subheader("⑤ 最终成果 · Final Artifact")
    if session.final_artifact is None:
        st.warning("未生成最终成果。")
        return
    markdown = session.final_artifact.to_markdown()
    st.markdown(markdown)
    st.download_button(
        "Save Artifact",
        data=markdown,
        file_name=f"{session.run_id}.md",
        mime="text/markdown",
    )


def main() -> None:
    st.set_page_config(page_title="AutoTeam Live", layout="wide")
    st.title("AutoTeam Research — AI Team Live View")
    st.caption(
        "v0.4.0 · 任务执行 Session：动态组队 → 协作执行 → Artifact → 最终成果（默认离线）"
    )

    if "session" not in st.session_state:
        st.session_state.session = None
        st.session_state.running = False

    choice = st.selectbox("选择示例任务或自定义", list(DEMO_TASKS) + ["自定义任务"])
    task = st.text_area("任务", value=DEMO_TASKS.get(choice, ""), height=80)

    if st.button("▶ 运行任务", type="primary", disabled=st.session_state.running):
        holder: dict = {}
        st.session_state.running = True
        st.session_state.session = None
        threading.Thread(target=_run_in_thread, args=(holder, task), daemon=True).start()
        st.session_state.holder = holder

    session = st.session_state.session
    holder = st.session_state.get("holder")
    if session is None and holder is not None:
        inner = holder.get("session")
        if inner is not None:
            st.session_state.session = inner
            session = inner
        elif holder.get("error"):
            st.session_state.running = False
            st.error(f"运行出错: {holder['error']}")
            return
        else:
            st.caption("⏳ 任务执行中…（自动刷新）")
            time.sleep(0.5)
            st.rerun()
    if session is None:
        st.info("选择任务后点击「运行任务」。完整 Session 默认离线运行，无需任何 API Key。")
        return

    st.session_state.running = False
    if session.status in (SessionStatus.RUNNING, SessionStatus.PENDING):
        st.caption("⏳ 任务执行中…（自动刷新）")
        time.sleep(0.5)
        st.rerun()

    st.markdown(f"**Run**: `{session.run_id}` · **Status**: {session.status.value.upper()}")
    _render_team(session)
    _render_live(session)
    _render_trace(session)
    _render_artifacts(session)
    _render_final(session)


if __name__ == "__main__":
    main()
