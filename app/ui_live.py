"""Streamlit "AI Team Live View" for the v0.2.0 research demo.

This page renders only. All orchestration lives in ``app.runtime.orchestrator`` and
``app.runtime.result_store`` so the same pipeline can be exercised by tests without
a browser. The pipeline runs in a background thread; this page polls the
``ResultStore`` and reruns to give a live updating view of the agent team.

Run it with:
    streamlit run app/ui_live.py
"""

from __future__ import annotations

import asyncio
import threading
import time

import streamlit as st

from app.llm.provider import get_llm_provider
from app.runtime.orchestrator import ResearchOrchestrator
from app.runtime.result_store import ResultStore

STATUS_EMOJI = {
    "pending": "⚪",
    "ready": "🟦",
    "running": "🟡",
    "success": "🟢",
    "failed": "🔴",
    "skipped": "⚫",
}


def _run_in_thread(
    orchestrator: ResearchOrchestrator, store: ResultStore, description: str
) -> None:
    try:
        asyncio.run(orchestrator.run(description))
    except Exception as exc:  # surface to the UI rather than swallow
        store.mark_done(error=str(exc))
    else:
        store.mark_done()


def _render_structure(snapshot: dict) -> None:
    structure = snapshot.get("structure")
    if not structure:
        return
    st.subheader("① 研究计划 · Task Decomposition")
    for index, subtask in enumerate(structure["subtasks"]):
        depends = subtask.get("depends_on") or "—"
        st.markdown(
            f"{index + 1}. **{subtask.get('target_role', 'Agent')}** — "
            f"{subtask.get('description', '')}  · 依赖: `{depends}`"
        )

    st.subheader("② 团队与编排 · Team & Topology")
    layers = structure.get("parallel_layers") or []
    for index, layer in enumerate(layers):
        names = " · ".join(structure["agent_names"].get(aid, aid) for aid in layer)
        st.markdown(f"并行层 {index + 1}: **{names}**")


def _render_live(snapshot: dict) -> None:
    structure = snapshot.get("structure")
    agent_ids = (structure or {}).get("agents", [])
    if not agent_ids:
        return
    st.subheader("③ 实时状态 · Live Agents")
    store: ResultStore = st.session_state.get("store")
    columns = st.columns(len(agent_ids))
    for index, agent_id in enumerate(agent_ids):
        status = store.status_of(agent_id) if store is not None else "pending"
        label = (structure["agent_names"].get(agent_id, agent_id) or agent_id).replace("_", " ")
        with columns[index]:
            st.metric(label=label, value=f"{STATUS_EMOJI.get(status, '⚪')} {status}")


def _render_report(snapshot: dict) -> None:
    report = snapshot.get("report")
    if not report:
        st.warning("未生成报告（可能存在上游失败）。")
        return
    st.subheader("④ 研究报告 · Research Report")
    st.markdown(f"**任务**: {report.get('task', '')}")
    st.markdown(f"**摘要**: {report.get('summary', '')}")

    market = report.get("market_overview")
    if market:
        st.markdown("**市场概览**")
        st.write(market.get("summary", ""))
        trends = market.get("key_trends") or []
        if trends:
            st.write("关键趋势: " + ", ".join(str(t) for t in trends))

    competitors = report.get("competitors")
    if competitors:
        st.markdown("**竞争格局**")
        st.write(competitors.get("summary", ""))
        for comp in competitors.get("competitors") or []:
            if isinstance(comp, dict) and comp.get("name"):
                st.write(f"- {comp.get('name')}: {comp.get('focus', '')}")

    technology = report.get("technology")
    if technology:
        st.markdown("**技术趋势**")
        st.write(technology.get("summary", ""))
        tech_trends = technology.get("trends") or []
        if tech_trends:
            st.write("趋势: " + ", ".join(str(t) for t in tech_trends))

    sources = report.get("sources") or []
    if sources:
        with st.expander(f"来源 ({len(sources)})"):
            for source in sources:
                st.markdown(f"- {source}")
    st.caption(f"生成时间: {report.get('generated_at', '')}")


def main() -> None:
    st.set_page_config(page_title="AutoTeam Research", layout="wide")
    st.title("AutoTeam Research — AI Team Live View")
    st.caption(
        "v0.2.0 · 多智能体研究团队实时编排 · 默认离线 Mock（配置 AUTOTEAM_API_KEY 可切换真实 LLM）"
    )

    if "store" not in st.session_state:
        st.session_state.store = None
        st.session_state.running = False

    task = st.text_area(
        "研究任务",
        value="分析中国跨境电商 SaaS 市场的竞争格局与技术趋势",
        height=80,
    )
    tool_mode = st.radio("工具模式", ["auto", "mock", "web"], index=0, horizontal=True)

    if st.button("▶ 运行研究团队", type="primary", disabled=st.session_state.running):
        new_store: ResultStore = ResultStore()
        orchestrator = ResearchOrchestrator(
            provider=get_llm_provider(), tool_mode=tool_mode, store=new_store
        )
        st.session_state.store = new_store
        st.session_state.running = True
        threading.Thread(
            target=_run_in_thread, args=(orchestrator, new_store, task), daemon=True
        ).start()

    store: ResultStore | None = st.session_state.store
    if store is None:
        st.info("输入任务后点击「运行研究团队」开始。所有 Demo 默认离线运行，无需 API Key。")
        return

    snapshot = store.snapshot()
    _render_structure(snapshot)
    _render_live(snapshot)

    if not snapshot["done"]:
        if snapshot.get("error"):
            st.session_state.running = False
            st.error(f"运行出错: {snapshot['error']}")
        else:
            st.caption("⏳ 研究中…（自动刷新）")
            time.sleep(0.4)
            st.rerun()
    else:
        st.session_state.running = False
        if snapshot.get("error"):
            st.error(f"运行出错: {snapshot['error']}")
        _render_report(snapshot)


if __name__ == "__main__":
    main()
