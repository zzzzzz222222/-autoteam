"""Streamlit "Dynamic Team" view (v0.3.0).

Renders the full dynamic chain — Task → Understanding → Capabilities →
Team → Tools → Dependencies → Execution Layers — plus a "Why this team?"
section, and can execute the plan through the existing scheduler and runtime.
All orchestration lives in ``app.runtime.dynamic_team``; this page only renders.

Run it with:
    streamlit run app/ui_dynamic.py
"""

from __future__ import annotations

import asyncio
import threading
import time

import streamlit as st

from app.llm.provider import get_llm_provider
from app.runtime.dynamic_team import build_dynamic_team, run_dynamic_team
from app.runtime.result_store import ResultStore

STATUS_EMOJI = {
    "pending": "⚪",
    "ready": "🟦",
    "running": "🟡",
    "success": "🟢",
    "failed": "🔴",
    "skipped": "⚫",
}

DEMO_TASKS = {
    "Demo A — AI Agent 市场分析": "分析 AI Agent 市场竞争格局",
    "Demo B — FastAPI 电商后端": "设计一个 FastAPI 电商后端系统",
    "Demo C — SaaS 市场进入策略": "制定 SaaS 产品进入某行业的市场策略",
}


def _run_in_thread(plan, store: ResultStore) -> None:
    try:
        asyncio.run(run_dynamic_team(plan, provider=get_llm_provider(), store=store))
    except Exception as exc:
        store.mark_done(error=str(exc))
    else:
        store.mark_done()


def _render_understanding(plan) -> None:
    st.subheader("① 任务理解 · Task Understanding")
    u = plan.understanding
    st.markdown(
        f"**领域**: {u.domain} · **目标**: {u.objective} · "
        f"**预期产出**: {u.expected_output} · **复杂度**: {u.complexity.value}"
    )
    st.markdown(
        "**所需能力**: " + ", ".join(f"`{c.value}`" for c in u.required_capabilities)
    )
    st.markdown("**子任务**:")
    for subtask in plan.subtasks:
        deps = ", ".join(subtask.dependencies) or "—"
        st.markdown(
            f"- **{subtask.title}** (`{subtask.id}`) → 能力 "
            f"{', '.join(c.value for c in subtask.required_capabilities)} · "
            f"依赖: `{deps}` · 产出: `{subtask.expected_output}`"
        )


def _render_team(plan) -> None:
    st.subheader("② 动态团队 · Dynamic Team")
    for reason in plan.explanation.agents:
        with st.expander(f"**{reason.agent_name}** — {', '.join(reason.capabilities)}"):
            st.markdown(f"**Why this team?** {reason.reason}")
            st.markdown(f"**Tools**: {', '.join(reason.tools) or '—'}")
            st.markdown(f"**Dependencies**: {', '.join(reason.depends_on) or '—'}")

    st.subheader("③ 执行分层 · Execution Layers")
    for index, layer in enumerate(plan.execution_layers, start=1):
        names = ", ".join(
            next(a.role.name for a in plan.agents if a.id == agent_id) for agent_id in layer
        )
        st.markdown(f"并行层 {index}: **{names}**")

    if plan.dependencies:
        with st.expander("依赖图（Agent → Agent）"):
            for edge in plan.dependencies:
                source = next(a.role.name for a in plan.agents if a.id == edge.source)
                target = next(a.role.name for a in plan.agents if a.id == edge.target)
                st.markdown(f"- {source} → {target}（{edge.reason}）")


def _render_results(snapshot: dict) -> None:
    st.subheader("④ 执行结果 · Results")
    structure = snapshot.get("structure") or {}
    names = structure.get("agent_names", {})
    for agent_id, result in snapshot["results"].items():
        status = result["status"]
        output = result.get("output") or {}
        title = output.get("title", "") if isinstance(output, dict) else ""
        summary = output.get("summary", "") if isinstance(output, dict) else ""
        st.markdown(
            f"- {STATUS_EMOJI.get(status, '⚪')} **{names.get(agent_id, agent_id)}** "
            f"— `{status}` · {title} {summary}"
        )


def main() -> None:
    st.set_page_config(page_title="AutoTeam Dynamic Team", layout="wide")
    st.title("AutoTeam — Dynamic Team Intelligence")
    st.caption("v0.3.0 · 不同任务 → 不同能力 → 不同团队（默认离线，无需 API Key）")

    if "plan" not in st.session_state:
        st.session_state.plan = None
        st.session_state.store = None
        st.session_state.running = False

    choice = st.selectbox("选择示例任务或自定义", list(DEMO_TASKS) + ["自定义任务"])
    task = st.text_area(
        "研究/工程/策略任务",
        value=DEMO_TASKS.get(choice, "制定一个个人知识管理工具的产品方案"),
        height=80,
    )

    col1, col2 = st.columns(2)
    build_clicked = col1.button("① 构建动态团队", type="primary")
    run_clicked = col2.button(
        "② 执行团队",
        disabled=st.session_state.plan is None or st.session_state.running,
    )

    if build_clicked:
        try:
            st.session_state.plan = build_dynamic_team(task)
            st.session_state.store = None
        except Exception as exc:
            st.error(f"团队构建失败: {exc}")
            st.session_state.plan = None

    plan = st.session_state.plan
    if plan is None:
        st.info("选择任务后点击「构建动态团队」。离线模式使用确定性规则，无需任何 API Key。")
        return

    _render_understanding(plan)
    _render_team(plan)

    if run_clicked and not st.session_state.running:
        store: ResultStore = ResultStore()
        st.session_state.store = store
        st.session_state.running = True
        threading.Thread(target=_run_in_thread, args=(plan, store), daemon=True).start()

    store: ResultStore | None = st.session_state.store
    if store is None:
        return
    snapshot = store.snapshot()
    if not snapshot["done"]:
        st.caption("⏳ 执行中…（自动刷新）")
        time.sleep(0.4)
        st.rerun()
    st.session_state.running = False
    if snapshot.get("error"):
        st.error(f"执行出错: {snapshot['error']}")
    _render_results(snapshot)


if __name__ == "__main__":
    main()
