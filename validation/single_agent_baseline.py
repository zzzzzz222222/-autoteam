"""Single-agent baseline for honest AutoTeam comparison.

Design
------
The baseline must be *fair*: same model, same tool registry/permissions, same
task text, same tool-call and iteration budgets. It deliberately does **not**
use dynamic team formation or the DAG scheduler — instead it drives the very
same ``AgentRuntime`` (the component AutoTeam uses per agent) with a single
hand-configured agent. That keeps the provider/tool code path identical while
removing multi-agent coordination, so the comparison isolates *coordination*,
not the model or the tools.

Structural difference (must be stated in any comparison)
--------------------------------------------------------
AutoTeam: N dynamically created agents + dependency DAG + per-agent evidence
collection + cross-agent synthesis.
Baseline: 1 agent, no dependencies, no synthesis — its report is that single
agent's deliverable. Coverage/quality differences may therefore come from
coordination *or* simply from having one agent instead of several.

Real mode is gated exactly like ``run_scenario.py`` (disabled in Phase 2).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # allow `python validation/single_agent_baseline.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.provider import MockLLMProvider, get_llm_provider  # noqa: E402
from app.models.agent import AgentRole  # noqa: E402
from app.models.capability import CapabilityName  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.topology import Topology, TopologyType  # noqa: E402
from app.runtime.agent_runtime import AgentRuntime  # noqa: E402
from app.runtime.artifacts import AgentDeliverable  # noqa: E402
from app.runtime.dynamic_models import DynamicAgentSpec  # noqa: E402
from app.runtime.events import ExecutionTrace  # noqa: E402
from app.scheduler.models import ExecutionContext  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402
from validation.collect import determine_truth  # noqa: E402
from validation.counting_provider import CountingProvider  # noqa: E402
from validation.run_scenario import (  # noqa: E402
    REAL_EXECUTION_ENABLED,
    REAL_MODE_NOTICE,
    write_json,
)
from validation.sanitize import redact_text, sanitize_url  # noqa: E402
from validation.scenarios import DEFAULT_SCENARIO_ID, get_scenario  # noqa: E402

# Tools the baseline is allowed to call. This mirrors the registry that
# AutoTeam's ToolSelector draws from; the baseline is not given extra powers.
BASELINE_TOOLS = ("web_search", "calculator", "local_knowledge")

BASELINE_AGENT_ID = "solo_agent"


def build_solo_agent(task: str, *, max_iterations: int) -> DynamicAgentSpec:
    """One agent that must cover the whole task without any collaborators."""
    agent = DynamicAgentSpec(
        id=BASELINE_AGENT_ID,
        role=AgentRole(
            name="Solo Analyst",
            capabilities=[
                CapabilityName.MARKET_RESEARCH,
                CapabilityName.COMPETITOR_ANALYSIS,
                CapabilityName.TECHNOLOGY_ANALYSIS,
                CapabilityName.RISK_ANALYSIS,
                CapabilityName.STRATEGY_PLANNING,
                CapabilityName.REPORT_WRITING,
            ],
            goal=task[:300],
            backstory="A single generalist analyst working alone on the full task.",
        ),
        tools=list(BASELINE_TOOLS),
        max_iterations=max_iterations,
        system_prompt="You are a single analyst covering the whole task end to end.",
    )
    # Mirrors execute_task(): the core assigns this attribute on plan agents
    # rather than constructing it (the declared field type is TaskDeliverable,
    # while the runtime switches on the AgentDeliverable identity).
    agent.output_schema = AgentDeliverable
    return agent


def run_single_agent(
    task: str,
    *,
    provider: Any = None,
    timeout: float | None = None,
    max_tool_calls: int = 6,
    max_iterations: int = 6,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Execute the whole task with exactly one agent (no scheduler, no DAG)."""
    del timeout  # the single-agent path runs synchronously; budget is iteration-bounded
    run_id = run_id or f"baseline_{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
    trace = ExecutionTrace(run_id)
    # Resolve the provider FIRST: the tool mode must follow the provider that is
    # actually used, otherwise an offline baseline could reach live tools.
    resolved = provider if provider is not None else MockLLMProvider()
    runtime = AgentRuntime(
        provider=resolved,
        tool_registry=ToolRegistry(
            mode="mock" if isinstance(resolved, MockLLMProvider) else "auto"
        ),
        trace=trace,
        run_id=run_id,
        max_tool_calls=max_tool_calls,
        max_iterations=max_iterations,
    )
    agent = build_solo_agent(task, max_iterations=max_iterations)
    topology = Topology(
        type=TopologyType.CHAIN,
        agents=[BASELINE_AGENT_ID],
        edges=[],
        root_agent=BASELINE_AGENT_ID,
        parallel_layers=[[BASELINE_AGENT_ID]],
    )
    context = ExecutionContext(
        Task(description=task), topology, {BASELINE_AGENT_ID: agent}, {}
    )
    started = time.perf_counter()
    artifact = asyncio.run(runtime.execute(agent, context))
    elapsed = time.perf_counter() - started
    return {"run_id": run_id, "artifact": artifact, "trace": trace, "elapsed": elapsed}


def _artifact_markdown(artifact: Any, task: str, run_id: str) -> str:
    """Minimal markdown for the baseline deliverable (sanitized URLs)."""
    lines = [f"# {getattr(artifact, 'title', '') or 'Single-Agent Report'}", ""]
    lines.append(f"_AutoTeam single-agent baseline `{run_id}` (no DAG, no synthesis)_")
    lines.extend(["", "## Task", "", task, "", "## Deliverable", "",
                  getattr(artifact, "content", "") or "(empty)", ""])
    structured = getattr(artifact, "structured_data", {}) or {}
    if structured:
        lines.extend(["**Key data:**", ""])
        lines.extend(f"- `{key}` = `{value}`" for key, value in structured.items())
        lines.append("")
    evidence = getattr(artifact, "evidence", []) or []
    if evidence:
        lines.extend(["## Evidence", ""])
        for item in evidence:
            lines.append(
                f"- {redact_text(getattr(item, 'claim', ''), limit=300)} "
                f"(`{getattr(item, 'source_id', '')}`)"
            )
        lines.append("")
    sources = getattr(artifact, "source_records", []) or []
    if sources:
        lines.extend(["## Sources", ""])
        for index, source in enumerate(sources, start=1):
            url = sanitize_url(getattr(source, "url", ""))
            title = redact_text(getattr(source, "title", ""), limit=200) or getattr(
                source, "id", ""
            )
            source_type = getattr(source, "source_type", "")
            lines.append(f"{index}. {title} ({source_type}{', ' + url if url else ''})")
        lines.append("")
    return "\n".join(lines)


def collect_baseline_metrics(
    *,
    result: dict[str, Any],
    scenario_id: str,
    mode: str,
    provider: Any,
    counting: Any | None,
    task: str = "",
) -> dict[str, Any]:
    artifact = result["artifact"]
    trace = result["trace"]
    events = list(getattr(trace, "events", []) or [])

    tool_calls: list[dict[str, Any]] = []
    for event in events:
        if getattr(event, "type", "") != "TOOL_CALLED":
            continue
        meta = getattr(event, "metadata", {}) or {}
        tool_calls.append(
            {
                "tool": str(meta.get("tool", "") or ""),
                "kind": str(meta.get("tool_kind", "") or ""),
                "offline": bool(meta.get("offline", False)),
                "error": redact_text(meta.get("error", ""), limit=200) if meta.get("error") else "",
            }
        )
    by_kind: dict[str, int] = {}
    for call in tool_calls:
        by_kind[call["kind"]] = by_kind.get(call["kind"], 0) + 1

    llm_summary = counting.summary() if counting is not None else None
    llm_count = llm_summary.get("count") if llm_summary else None
    blocked = llm_summary.get("blocked", 0) if llm_summary else 0
    token_usage = llm_summary.get("token_usage") if llm_summary else None
    model = getattr(provider, "model", "") if provider is not None else ""
    estimated_cost: float | None = None
    if isinstance(token_usage, dict) and model:
        try:
            from validation.pricing import compute_cost

            estimated_cost = compute_cost(model, token_usage)
        except Exception:  # noqa: BLE001 - best-effort, never fatal
            estimated_cost = None
    cost_available = token_usage is not None

    sources = list(getattr(artifact, "source_records", []) or [])
    evidence = list(getattr(artifact, "evidence", []) or [])
    truth = determine_truth(
        provider=provider,
        tool_metrics={"by_kind": by_kind},
        llm_call_count=llm_count,
        provider_fallback=False,
        synthesis_degraded=False,  # baseline has no synthesis step at all
        core_data_present=artifact is not None,
        requires_web_search=False,  # informational: the baseline may not need search
        blocked_llm_calls=blocked,
    )
    return {
        "schema_version": "1",
        "baseline": True,
        "structure": "single_agent_no_dag_no_synthesis",
        "run_id": result["run_id"],
        "scenario_id": scenario_id,
        "mode": mode,
        "task": redact_text(task, limit=2000),
        "provider": {
            "type": type(provider).__name__ if provider is not None else "MockLLMProvider",
            "model": getattr(provider, "model", "") if provider is not None else "mock",
            "is_real_llm": truth["is_real_llm"],
            "llm_calls": llm_summary,
            "llm_call_count": llm_count,
        },
        "agent_count": 1,
        "elapsed_seconds": round(result["elapsed"], 3),
        "tools": {"total": len(tool_calls), "by_kind": by_kind, "calls": tool_calls},
        "artifacts": {"count": 1 if artifact is not None else 0},
        "evidence_count": len(evidence),
        "source_count": len(sources),
        "sources": [
            {
                "source_id": getattr(source, "id", ""),
                "title": redact_text(getattr(source, "title", ""), limit=200),
                "source_type": getattr(source, "source_type", ""),
                "url": sanitize_url(getattr(source, "url", "")),
            }
            for source in sources
        ],
        "truth": truth,
        "cost_data_available": cost_available,
        "cost_data_reason": (
            ""
            if cost_available
            else "Token usage is only observed when a real CountingProvider wraps a "
            "provider that returns response.usage. Offline runs (and real runs whose "
            "endpoint omitted usage) have no observed usage, so cost data is null "
            "(never guessed)."
        ),
        "estimated_cost_usd": estimated_cost,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="single_agent_baseline",
        description="AutoTeam v0.6.0 single-agent baseline (offline by default).",
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO_ID, help="scenario id (A|B|C)")
    parser.add_argument("--out", default="validation/runs/baseline", help="output root")
    parser.add_argument("--mode", choices=("offline", "real"), default="offline")
    parser.add_argument("--max-tool-calls", type=int, default=6)
    parser.add_argument("--max-iterations", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--max-llm-calls", type=int, default=20)
    parser.add_argument("--confirm-real", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_tool_calls < 1 or args.max_iterations < 1:
        raise SystemExit("error: budgets must be >= 1")
    if args.timeout <= 0:
        raise SystemExit("error: --timeout must be > 0")
    if args.max_llm_calls < 1:
        raise SystemExit("error: --max-llm-calls must be >= 1")
    scenario = get_scenario(args.scenario)

    plan = {
        "scenario_id": scenario.scenario_id,
        "mode": args.mode,
        "structure": "single_agent_no_dag_no_synthesis",
        "tools": list(BASELINE_TOOLS),
        "max_tool_calls": args.max_tool_calls,
        "max_iterations": args.max_iterations,
        "max_llm_calls": args.max_llm_calls,
        "out": args.out,
        "real_execution_enabled": REAL_EXECUTION_ENABLED,
    }
    if args.prepare_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.mode == "real":
        print(REAL_MODE_NOTICE)
        if not args.confirm_real:
            raise SystemExit("error: real mode requires --confirm-real")
        if not REAL_EXECUTION_ENABLED:
            raise SystemExit(
                "error: real execution is disabled in Phase 2 (REAL_EXECUTION_ENABLED=False)."
            )

    counting = None
    provider: Any = None
    if args.mode == "real":
        provider = get_llm_provider()
        counting = CountingProvider(provider, max_calls=args.max_llm_calls)

    result = run_single_agent(
        scenario.task,
        provider=counting if counting is not None else provider,
        timeout=args.timeout,
        max_tool_calls=args.max_tool_calls,
        max_iterations=args.max_iterations,
    )
    metrics = collect_baseline_metrics(
        result=result,
        scenario_id=scenario.scenario_id,
        mode=args.mode,
        provider=counting if counting is not None else provider,
        counting=counting,
        task=scenario.task,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / f"{stamp}_{scenario.scenario_id}_{args.mode}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "task.txt").write_text(scenario.task, encoding="utf-8")
    errors = write_json(out_dir / "config.json", plan)
    errors += write_json(out_dir / "metrics.json", metrics)
    errors += write_json(out_dir / "sources.json", {"items": metrics["sources"]})
    (out_dir / "report.md").write_text(
        _artifact_markdown(result["artifact"], scenario.task, result["run_id"]), encoding="utf-8"
    )

    truth = metrics["truth"]
    print("-" * 78)
    print(f"baseline run  : {result['run_id']} ({args.mode}, single agent)")
    print(f"provider      : {metrics['provider']['type']} | is_real_llm={truth['is_real_llm']}")
    print(f"elapsed       : {metrics['elapsed_seconds']}s")
    print(f"tool calls    : {metrics['tools']['total']} {metrics['tools']['by_kind']}")
    print(f"llm calls     : {metrics['provider']['llm_call_count']}")
    print(f"evidence/source: {metrics['evidence_count']}/{metrics['source_count']}")
    if metrics["cost_data_available"]:
        print(f"cost data     : available (estimated_cost_usd={metrics['estimated_cost_usd']})")
    else:
        print(f"cost data     : unavailable ({metrics['cost_data_reason']})")
    print(f"output dir    : {out_dir}")
    print("-" * 78)
    if errors:
        print(f"serialization errors: {errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
