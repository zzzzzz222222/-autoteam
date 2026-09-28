"""Offline demo: AutoTeam v0.3.0 — Dynamic Team Intelligence.

Three different tasks produce three visibly different teams (capabilities,
roles, agents, tools, dependencies, execution layers). Then one team is
executed end-to-end through the existing scheduler and runtime — fully offline.

Run with:
    python examples/dynamic_team_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.dynamic_team import build_dynamic_team, run_dynamic_team  # noqa: E402

DEMO_TASKS = {
    "A · AI Agent Market Analysis": "分析 AI Agent 市场竞争格局",
    "B · FastAPI E-commerce Backend": "设计一个 FastAPI 电商后端系统",
    "C · SaaS Market Entry Strategy": "制定 SaaS 产品进入某行业的市场策略",
}


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def print_plan(label: str, plan) -> None:
    print("=" * 64)
    print(f"Demo {label}")
    print("=" * 64)
    print(f"Task       : {plan.task}")
    u = plan.understanding
    print(
        f"Understanding: domain={u.domain} objective={u.objective} "
        f"expected_output={u.expected_output} complexity={u.complexity.value}"
    )
    print("Capabilities:", ", ".join(c.value for c in u.required_capabilities))
    print("Roles       :", ", ".join(role.name for role in plan.roles))
    print("Agents      :", ", ".join(agent.role.name for agent in plan.agents))
    print("Tools       :")
    for agent_id, tools in plan.tools.items():
        print(f"  - {agent_id}: {', '.join(tools) or '(none)'}")
    print("Dependencies:")
    for edge in plan.dependencies:
        print(f"  - {edge.source} -> {edge.target} ({edge.reason})")
    for index, layer in enumerate(plan.execution_layers, start=1):
        names = ", ".join(
            next(a.role.name for a in plan.agents if a.id == agent_id)
            for agent_id in layer
        )
        print(f"Layer {index}     : {names}")
    print("Why this team?")
    print(f"  {plan.explanation.reasoning}")
    for reason in plan.explanation.agents:
        deps = ", ".join(reason.depends_on) or "—"
        print(f"  - {reason.agent_name}: {reason.reason} Tools: {reason.tools or '—'} Deps: {deps}")
    print()


def main() -> None:
    configure_utf8_output()
    plans = {label: build_dynamic_team(task) for label, task in DEMO_TASKS.items()}
    for label, plan in plans.items():
        print_plan(label, plan)

    print("Running Demo B end-to-end offline (existing scheduler + runtime)...")
    results = asyncio.run(run_dynamic_team(plans["B · FastAPI E-commerce Backend"]))
    for agent_id, result in results.items():
        output = result.output
        summary = getattr(output, "summary", "")
        print(f"  {agent_id}: {result.status.value} — {summary}")
    statuses = {result.status.value for result in results.values()}
    print("E2E statuses:", statuses)


if __name__ == "__main__":
    main()
