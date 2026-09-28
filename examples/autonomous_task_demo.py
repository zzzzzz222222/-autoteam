"""Killer demo: AutoTeam v0.4.0 — Autonomous Task Completion.

One complex task goes through the whole pipeline offline:
Task → Understanding → Capabilities → Dynamic Team → Task Graph → Execution
→ Agent Collaboration (upstream artifacts) → Failure/Retry demo → Final Report.

Run with:
    python examples/autonomous_task_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.session import execute_task  # noqa: E402

TASK = "分析 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案。"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "autoteam_output"


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def print_session(session, show_markdown: bool = True) -> None:
    print("=" * 68)
    print(f"Run ID    : {session.run_id}")
    print(f"Task      : {session.task}")
    plan = session.plan
    print(f"Team      : {', '.join(agent.role.name for agent in plan.agents)}")
    for index, layer in enumerate(plan.execution_layers, start=1):
        names = ", ".join(
            next(a.role.name for a in plan.agents if a.id == agent_id) for agent_id in layer
        )
        print(f"Layer {index}    : {names}")
    print("Agent Results:")
    names = session.agent_names()
    for agent_id, result in session.agent_results.items():
        output = result.output
        title = getattr(output, "title", "") if output is not None else ""
        print(f"  - {names.get(agent_id, agent_id)}: {result.status.value} — {title}")
    print("Artifacts:")
    for artifact in session.artifacts:
        deps = ", ".join(artifact.dependencies) or "—"
        print(
            f"  - {artifact.artifact_id} ({artifact.output_type.value}) "
            f"deps: {deps} data: {artifact.structured_data}"
        )
    status = session.status.value.upper()
    print(f"Final Status: {status}")
    if session.final_artifact is not None:
        path = session.save_markdown(OUTPUT_DIR)
        print(f"Final Artifact Path: {path}")
        if show_markdown:
            print("-" * 68)
            print(session.final_artifact.to_markdown())
            print("-" * 68)


def main() -> None:
    configure_utf8_output()

    print(">>> Killer Demo: complex task, full pipeline, offline")
    session = execute_task(TASK)
    print_session(session)

    print()
    print(">>> Failure Recovery Demo 1: retry then succeed (database fails once)")
    retry_session = execute_task(
        "设计一个 FastAPI 电商后端系统", failures_before_success={"database_engineer": 1}
    )
    retries = retry_session.trace.of_type("AGENT_RETRY")
    retry_ids = [e.agent_id for e in retries]
    print(f"Status: {retry_session.status.value.upper()} | retries: {retry_ids}")

    print()
    print(">>> Failure Recovery Demo 2: retry exhausted → replan → partial success")
    failed_session = execute_task(
        "设计一个 FastAPI 电商后端系统", fail_agent_ids={"database_engineer"}
    )
    replanned = failed_session.trace.of_type("AGENT_REPLANNED")
    skipped = [
        agent_id
        for agent_id, result in failed_session.agent_results.items()
        if result.status.value == "skipped"
    ]
    replanned_ids = [e.agent_id for e in replanned]
    print(
        f"Status: {failed_session.status.value.upper()} | replanned: {replanned_ids} "
        f"| skipped: {skipped}"
    )


if __name__ == "__main__":
    main()
