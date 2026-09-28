"""Killer demo: AutoTeam v0.5.0 — Real-World Agent Execution.

One pipeline, two modes:

- Offline (default, no API key): dynamic team → tool use (offline_mock search,
  safe calculator, local knowledge) → artifacts with offline evidence →
  validation → collaboration → final Markdown with Sources/Evidence sections.
- Real (optional): set AUTOTEAM_API_KEY (+ optionally AUTOTEAM_WEB_SEARCH_URL /
  AUTOTEAM_WEB_SEARCH_API_KEY) to run the same flow with a real LLM and real
  web search. The real demo is NOT exercised by CI or tests.

Run with:
    python examples/real_world_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.provider import MockLLMProvider, get_llm_provider  # noqa: E402
from app.runtime.session import execute_task  # noqa: E402

TASK = "分析 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案。"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "autoteam_output"


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def print_sources(session) -> None:
    final = session.final_artifact
    if final is None:
        return
    if final.source_records:
        print("Sources:")
        for source in final.source_records:
            url = source.url or "(no url — offline_mock)"
            print(f"  - [{source.id}] {source.title or '(untitled)'} ({source.source_type}) {url}")
        print(f"Evidence items: {len(final.evidence)}")
    else:
        print("Sources: none (agent knowledge only, nothing fabricated)")


def main() -> None:
    configure_utf8_output()
    provider = get_llm_provider()
    real_mode = not isinstance(provider, MockLLMProvider)
    search_real = bool(
        os.getenv("AUTOTEAM_WEB_SEARCH_URL") and os.getenv("AUTOTEAM_WEB_SEARCH_API_KEY")
    )
    mode_label = "REAL LLM" if real_mode else "OFFLINE MOCK (no API key)"
    print(f"Execution mode : {mode_label}")
    print("Web search     : REAL" if search_real else "Web search     : OFFLINE MOCK")
    print(f"Provider       : {type(provider).__name__}")
    print()

    session = execute_task(TASK, provider=provider, provider_fallback=True)
    plan = session.plan
    print(f"Run ID     : {session.run_id}")
    print(f"Task       : {session.task}")
    print(f"Team       : {', '.join(agent.role.name for agent in plan.agents)}")
    for index, layer in enumerate(plan.execution_layers, start=1):
        names = ", ".join(
            next(a.role.name for a in plan.agents if a.id == agent_id) for agent_id in layer
        )
        print(f"Layer {index}    : {names}")
    names = session.agent_names()
    print("Agent Results:")
    for agent_id, result in session.agent_results.items():
        output = result.output
        title = getattr(output, "title", "") if output is not None else ""
        sources = len(getattr(output, "source_records", []) or [])
        print(
            f"  - {names.get(agent_id, agent_id)}: {result.status.value} — {title}"
            f" (sources: {sources})"
        )
    print(f"Final Status: {session.status.value.upper()}")
    if session.final_artifact is not None:
        path = session.save_markdown(OUTPUT_DIR)
        print(f"Final Artifact Path: {path}")
        print_sources(session)
        print("-" * 68)
        print(session.final_artifact.to_markdown())
        print("-" * 68)


if __name__ == "__main__":
    main()
