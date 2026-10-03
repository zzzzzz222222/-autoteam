"""Run one validation scenario repeatably and persist an auditable record.

Usage (offline self-test — the only mode enabled in this phase)::

    python validation/run_scenario.py --scenario A --runs 1 --mode offline

Budget model (validation layer only; the core engine is untouched)
-----------------------------------------------------------------
* ``--max-llm-calls``  hard ceiling on **real** provider requests for the run,
  enforced atomically inside ``CountingProvider`` (concurrency-safe).
* ``--max-total-minutes`` batch wall clock **and** per-run wall clock: each run
  is given the remaining batch budget and is executed in a worker thread that we
  stop waiting on when the budget expires.
* ``--max-tool-calls`` / ``--max-iterations`` / ``--timeout`` are forwarded to
  the core engine's existing per-agent bounds.

Honest limits: the provider acts as a **cooperative cancellation point** (no new
request once the budget or deadline is reached, so agents fail fast and the core
usually returns a partial session). A synchronous HTTP request that is already
in flight cannot be interrupted; the worker thread is abandoned (daemon) and
that gap is recorded in ``metrics.json`` and ``report.md``. Nothing is silently
switched to Mock: a budget stop is reported as ``aborted``/``degraded``.

Real mode is deliberately **not executable** in this phase: ``--mode real``
prints the cost warning and exits unless ``--confirm-real`` is passed, and even
then a hard code gate (``REAL_EXECUTION_ENABLED``) refuses to run.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # allow `python validation/run_scenario.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.provider import get_llm_provider  # noqa: E402
from app.runtime.session import execute_task  # noqa: E402
from validation.collect import (  # noqa: E402
    build_truth_flags,
    collect_aborted_metrics,
    collect_metrics,
)
from validation.counting_provider import CountingProvider  # noqa: E402
from validation.scenarios import DEFAULT_SCENARIO_ID, get_scenario  # noqa: E402

# ---------------------------------------------------------------------------
# Phase-2 safety gate. Real LLM + Tavily calls cost money and are irreversible;
# they must only run after an explicit decision by the maintainer.
# ---------------------------------------------------------------------------
# Real execution is a deliberate, maintainer-controlled decision: it spends real
# API credits and is irreversible. Set to True only for a supervised real
# validation window, and restore to False afterwards.
# Real execution is a deliberate, maintainer-controlled decision: it spends real
# API credits and is irreversible. Set to True only for a supervised real
# validation window, and restore to False afterwards.
REAL_EXECUTION_ENABLED = False

REAL_MODE_NOTICE = (
    "REAL MODE requested: this runs the real LLM provider AND real Tavily web search.\n"
    "  * It spends real API credits. Token usage IS captured (app/llm/provider.py ->\n"
    "    last_response_meta, aggregated by validation/counting_provider.py) and, when a\n"
    "    model price is listed in validation/pricing.py, an estimated cost is reported.\n"
    "    Unknown models / offline runs report cost as null (never guessed).\n"
    "  * It sends your scenario text to the configured LLM endpoint.\n"
    "  * Budget controls: --max-llm-calls, --max-tool-calls, --max-iterations,\n"
    "    --timeout, --max-total-minutes. They are enforced, not guaranteed safe."
)

# Conservative starting point for the first real Scenario A round. These are
# *choices*, not validated safety guarantees.
DEFAULT_RUNS = 1
DEFAULT_MAX_TOOL_CALLS = 6
DEFAULT_MAX_ITERATIONS = 4
DEFAULT_TIMEOUT = 300.0
DEFAULT_MAX_TOTAL_MINUTES = 10.0
DEFAULT_MAX_LLM_CALLS = 20


def _stringify(value: Any) -> Any:
    """Recursively coerce arbitrary objects into JSON-serializable structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _stringify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_stringify(v) for v in value]
    for attr in ("model_dump", "dict"):
        dump = getattr(value, attr, None)
        if callable(dump):
            try:
                return _stringify(dump())
            except Exception:  # noqa: BLE001 - fall through to repr
                pass
    return f"<non-serializable:{type(value).__name__}>"


def write_json(path: Path, payload: Any) -> list[str]:
    """Write JSON, never losing the record; returns serialization errors."""
    errors: list[str] = []
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=_stringify)
    except (TypeError, ValueError) as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        try:
            text = json.dumps(_stringify(payload), ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError) as exc2:
            errors.append(f"{path.name}: fallback failed: {type(exc2).__name__}: {exc2}")
            text = json.dumps({"serialization_failed": True}, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_scenario",
        description="AutoTeam v0.6.0 scenario validation runner (offline by default).",
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO_ID, help="scenario id (A|B|C)")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="independent runs (>=1)")
    parser.add_argument("--out", default="validation/runs", help="output root directory")
    parser.add_argument(
        "--mode",
        choices=("offline", "real"),
        default="offline",
        help="offline (default, mock provider) | real (disabled in this phase)",
    )
    parser.add_argument(
        "--max-tool-calls",
        type=int,
        default=DEFAULT_MAX_TOOL_CALLS,
        help="per-agent tool budget (>=1)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help="per-agent LLM decision loop budget (>=1)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="per-attempt timeout in seconds (>0)",
    )
    parser.add_argument(
        "--max-total-minutes",
        type=float,
        default=DEFAULT_MAX_TOTAL_MINUTES,
        help="batch AND per-run wall-clock budget in minutes (>0)",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=DEFAULT_MAX_LLM_CALLS,
        help="hard ceiling on real LLM requests for one run (>=1)",
    )
    parser.add_argument(
        "--confirm-real",
        action="store_true",
        help="acknowledge that real mode spends API credits (still gated)",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="print the resolved plan and exit without executing anything",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    """Reject illegal budgets before any work starts."""
    if args.runs < 1:
        raise SystemExit("error: --runs must be >= 1")
    if args.max_tool_calls < 1:
        raise SystemExit("error: --max-tool-calls must be >= 1")
    if args.max_iterations < 1:
        raise SystemExit("error: --max-iterations must be >= 1")
    if args.timeout <= 0:
        raise SystemExit("error: --timeout must be > 0")
    if args.max_total_minutes <= 0:
        raise SystemExit("error: --max-total-minutes must be > 0")
    if args.max_llm_calls < 1:
        raise SystemExit("error: --max-llm-calls must be >= 1")


def real_mode_gate(args: argparse.Namespace) -> None:
    """Refuse to run real mode unless every guard is satisfied (Phase 2: never)."""
    print(REAL_MODE_NOTICE)
    if not args.confirm_real:
        raise SystemExit("error: real mode requires --confirm-real")
    if not REAL_EXECUTION_ENABLED:
        raise SystemExit(
            "error: real execution is disabled (REAL_EXECUTION_ENABLED=False).\n"
            "       Re-run with --mode offline, or enable the gate in a later phase "
            "after the maintainer authorises real API spend."
        )


def describe_plan(args: argparse.Namespace, scenario_id: str) -> dict[str, Any]:
    scenario = get_scenario(scenario_id)
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.name,
        "mode": args.mode,
        "runs": args.runs,
        "max_tool_calls": args.max_tool_calls,
        "max_iterations": args.max_iterations,
        "timeout": args.timeout,
        "max_total_minutes": args.max_total_minutes,
        "max_llm_calls": args.max_llm_calls,
        "out": str(Path(args.out)),
        "checklist_items": len(scenario.checklist),
        "real_execution_enabled": REAL_EXECUTION_ENABLED,
        "budget_note": (
            "budgets are enforced ceilings, not validated safety guarantees; "
            "an in-flight synchronous HTTP request cannot be interrupted"
        ),
    }


def _resolve_real_provider() -> Any:
    """Seam so tests can inject an offline provider double."""
    return get_llm_provider()


@dataclass
class RunOutcome:
    session: Any | None
    counting: Any | None
    elapsed: float
    termination_reason: str
    aborted: bool
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _run_once_guarded(
    *,
    task: str,
    mode: str,
    args: argparse.Namespace,
    run_deadline: float,
    provider_resolver: Any = None,
) -> RunOutcome:
    """Execute one session under a wall-clock budget + LLM call budget.

    The provider is the cooperative cancellation point; the worker thread is the
    last-resort net for work that cannot be interrupted.
    """
    resolver = provider_resolver or _resolve_real_provider
    counting: CountingProvider | None = None
    provider: Any = None
    if mode == "real":
        counting = CountingProvider(
            resolver(), max_calls=args.max_llm_calls, deadline=run_deadline
        )
        provider = counting

    holder: dict[str, Any] = {}

    def _worker() -> None:
        try:
            holder["session"] = execute_task(
                task,
                provider=provider,
                tool_mode="auto" if mode == "real" else "mock",
                timeout=args.timeout,
                max_tool_calls=args.max_tool_calls,
                max_iterations=args.max_iterations,
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced to the caller below
            holder["error"] = exc

    started = time.perf_counter()
    thread = threading.Thread(target=_worker, name="validation-run", daemon=True)
    thread.start()
    thread.join(max(0.0, run_deadline - time.monotonic()))
    elapsed = time.perf_counter() - started

    if thread.is_alive():
        # Cannot force-kill a thread blocked in a synchronous HTTP call. Stop
        # waiting, keep whatever the provider log captured, and say so plainly.
        return RunOutcome(
            session=None,
            counting=counting,
            elapsed=elapsed,
            termination_reason="run_timeout",
            aborted=True,
            error=(
                "wall-clock budget exhausted while the run was still in flight; the core "
                "returns the session only on completion, so partial session data is unavailable"
            ),
        )
    if "error" in holder:
        raise holder["error"]

    session = holder.get("session")
    reason = "completed"
    aborted = False
    if counting is not None:
        summary = counting.summary()
        if summary.get("blocked"):
            by_reason = summary.get("blocked_by_reason", {})
            if "run_deadline" in by_reason:
                reason = "run_deadline_exceeded"
            else:
                reason = "llm_budget_exhausted"
            aborted = True
    return RunOutcome(session=session, counting=counting, elapsed=elapsed,
                      termination_reason=reason, aborted=aborted)


def _trace_payload(session: Any) -> list[dict[str, Any]]:
    from validation.sanitize import redact_text

    rows: list[dict[str, Any]] = []
    for event in getattr(getattr(session, "trace", None), "events", []) or []:
        metadata = {
            key: redact_text(value, limit=200)
            for key, value in (getattr(event, "metadata", {}) or {}).items()
            if key not in {"prompt", "response", "content"}
        }
        rows.append(
            {
                "event_id": getattr(event, "event_id", ""),
                "type": getattr(event, "type", ""),
                "agent_id": getattr(event, "agent_id", ""),
                "timestamp": getattr(event, "timestamp", None),
                "message": redact_text(getattr(event, "message", ""), limit=300),
                "metadata": metadata,
            }
        )
    return rows


def _synthesis_audit(session: Any | None) -> dict[str, Any]:
    """Code-owned audits from the final bundle (empty when unavailable)."""
    bundle = getattr(session, "synthesis_bundle", None) if session is not None else None
    if bundle is None:
        return {"available": False}
    return {
        "available": True,
        "evidence_selection": dict(getattr(bundle, "evidence_selection", {}) or {}),
        "claim_audit": list(getattr(bundle, "claim_audit", []) or []),
        "source_gaps": list(getattr(bundle, "source_gaps", []) or []),
        "source_conflicts": list(getattr(bundle, "source_conflicts", []) or []),
    }


def persist_run(
    *,
    run_dir: Path,
    session: Any | None,
    metrics: dict[str, Any],
    scenario: Any,
    config: dict[str, Any],
) -> tuple[Path, list[str]]:
    """Write the full audit record for one run; returns (report_path, errors)."""
    errors: list[str] = []
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "task.txt").write_text(scenario.task, encoding="utf-8")
    errors += write_json(run_dir / "config.json", config)
    errors += write_json(run_dir / "checklist.json", {"items": list(scenario.checklist)})
    errors += write_json(run_dir / "team.json", metrics.get("team", {}))
    errors += write_json(run_dir / "dag.json", metrics.get("team", {}).get("dag", {}))
    errors += write_json(run_dir / "trace.json", _trace_payload(session) if session else [])
    errors += write_json(run_dir / "agent_results.json", metrics.get("execution", {}))
    errors += write_json(run_dir / "artifacts.json", metrics.get("artifacts", {}))
    errors += write_json(run_dir / "evidence.json", metrics.get("evidence", {}))
    errors += write_json(run_dir / "sources.json", metrics.get("sources", {}))
    errors += write_json(run_dir / "synthesis.json", metrics.get("synthesis", {}))
    # v0.6.6: full evidence-selection / citation / source-gap audits (the
    # per-record selection reasons are kept here so synthesis.json stays compact).
    errors += write_json(run_dir / "synthesis_audit.json", _synthesis_audit(session))
    errors += write_json(run_dir / "metrics.json", metrics)

    termination = metrics.get("termination", {})
    report_path = run_dir / "report.md"
    final = getattr(session, "final_artifact", None) if session is not None else None
    if final is not None and hasattr(final, "to_markdown"):
        report_path.write_text(final.to_markdown(), encoding="utf-8")
        try:  # keep the engine's own file naming convention alongside it
            session.save_markdown(run_dir)
        except Exception as exc:  # noqa: BLE001 - report already written
            errors.append(f"save_markdown: {type(exc).__name__}")
    else:
        reason = termination.get("reason", "no_final_artifact")
        truth = metrics.get("truth", {})
        report_path.write_text(
            "\n".join(
                [
                    "# Run did not produce a final artifact",
                    "",
                    f"- termination reason: `{reason}`",
                    f"- session status: `{metrics.get('session_status')}`",
                    f"- verdict: `{truth.get('verdict')}` (valid_real_e2e="
                    f"{truth.get('is_valid_real_e2e')})",
                    f"- provider: `{metrics.get('provider', {}).get('type')}` "
                    f"(real_llm={truth.get('is_real_llm')})",
                    f"- llm calls: {metrics.get('provider', {}).get('llm_call_count')} "
                    f"| blocked: {truth.get('blocked_llm_calls')}",
                    "",
                    f"> {termination.get('note', '')}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if session is None:
        errors += write_json(
            run_dir / "partial_provider_log.json",
            {
                "reason": termination.get("reason"),
                "provider": metrics.get("provider", {}),
                "note": "captured from the counting provider after the run was abandoned",
            },
        )
    errors += write_json(run_dir / "serialization_errors.json", {"errors": errors})
    return report_path, errors


def print_run_summary(metrics: dict[str, Any], report_path: Path, run_dir: Path) -> None:
    truth = metrics.get("truth", {})
    tools = metrics.get("tools", {})
    execution = metrics.get("execution", {})
    counts = execution.get("counts", {})
    termination = metrics.get("termination", {})
    print("-" * 78)
    print(f"run_id        : {metrics.get('run_id') or '(aborted)'}")
    print(f"scenario      : {metrics.get('scenario_id')} ({metrics.get('mode')})")
    print(f"provider      : {truth.get('provider_type')} | is_real_llm={truth.get('is_real_llm')}")
    print(
        f"real web      : {truth.get('is_real_web_search')} "
        f"(web={truth.get('web_search_calls')}, offline={truth.get('offline_search_calls')})"
    )
    print(f"agents        : {metrics.get('team', {}).get('agent_count')}")
    print(
        f"elapsed       : {execution.get('total_elapsed_seconds')}s "
        f"| termination={termination.get('reason')}"
    )
    print(
        f"success/fail/skip: {counts.get('success', 0)}/{counts.get('failed', 0)}"
        f"/{counts.get('skipped', 0)}  retries={execution.get('retry_total')}"
    )
    print(f"tool calls    : {tools.get('total')} {tools.get('by_kind')}")
    print(
        f"llm calls     : {metrics.get('provider', {}).get('llm_call_count')} "
        f"| blocked={truth.get('blocked_llm_calls')}"
    )
    print(
        f"verdict       : {truth.get('verdict')} "
        f"| valid_real_e2e={truth.get('is_valid_real_e2e')}"
    )
    if truth.get("reasons"):
        print(f"  reasons     : {'; '.join(truth['reasons'])}")
    print(f"report        : {report_path}")
    print(f"output dir    : {run_dir}")
    print("-" * 78)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    validate_args(args)
    scenario = get_scenario(args.scenario)
    plan = describe_plan(args, scenario.scenario_id)

    if args.prepare_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("prepare-only: nothing was executed.")
        return 0

    if args.mode == "real":
        real_mode_gate(args)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_dir = Path(args.out) / f"{stamp}_{scenario.scenario_id}_{args.mode}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.max_total_minutes * 60

    results: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.append(
                {
                    "run": index,
                    "status": "skipped",
                    "reason": f"wall-clock budget ({args.max_total_minutes} min) exhausted",
                }
            )
            print(f"[skip] run {index}: wall-clock budget exhausted")
            continue

        try:
            outcome = _run_once_guarded(
                task=scenario.task,
                mode=args.mode,
                args=args,
                run_deadline=deadline,
            )
        except Exception as exc:  # noqa: BLE001 - one bad run must not kill the batch
            results.append(
                {"run": index, "status": "crashed", "reason": f"{type(exc).__name__}: {exc}"}
            )
            print(f"[crash] run {index}: {type(exc).__name__}: {exc}")
            continue

        if outcome.session is not None:
            metrics = collect_metrics(
                outcome.session,
                scenario_id=scenario.scenario_id,
                mode=args.mode,
                provider=outcome.counting,
                counting=outcome.counting,
                measured_elapsed=outcome.elapsed,
                requires_web_search=True,
                termination_reason=outcome.termination_reason,
                aborted=outcome.aborted,
            )
        else:
            metrics = collect_aborted_metrics(
                scenario_id=scenario.scenario_id,
                mode=args.mode,
                provider=outcome.counting,
                counting=outcome.counting,
                reason=outcome.termination_reason,
                elapsed=outcome.elapsed,
                task=scenario.task,
            )

        run_dir = batch_dir / f"run{index}_{metrics.get('run_id') or 'aborted'}"
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path, errors = persist_run(
            run_dir=run_dir,
            session=outcome.session,
            metrics=metrics,
            scenario=scenario,
            config={**plan, "run_index": index, "termination_reason": outcome.termination_reason},
        )
        print_run_summary(metrics, report_path, run_dir)
        results.append(
            {
                "run": index,
                "run_id": metrics.get("run_id"),
                "dir": str(run_dir),
                "report": str(report_path),
                "session_status": metrics.get("session_status"),
                "termination_reason": outcome.termination_reason,
                "metrics": {
                    "agent_count": metrics.get("team", {}).get("agent_count"),
                    "layer_count": metrics.get("team", {}).get("dag", {}).get("layer_count"),
                    "edge_count": metrics.get("team", {}).get("dag", {}).get("edge_count"),
                    "elapsed_seconds": metrics.get("execution", {}).get("total_elapsed_seconds"),
                    "tool_calls": metrics.get("tools", {}).get("total"),
                    "tools_by_kind": metrics.get("tools", {}).get("by_kind"),
                    "llm_call_count": metrics.get("provider", {}).get("llm_call_count"),
                    "llm_blocked": metrics.get("truth", {}).get("blocked_llm_calls"),
                },
                "truth": build_truth_flags(metrics),
                "serialization_errors": errors,
            }
        )
        if outcome.aborted:
            # Stop launching further work once the budget has been hit.
            print(f"[stop] run {index} hit the budget ({outcome.termination_reason}); "
                  f"not starting further runs")
            break

    errors = write_json(
        batch_dir / "batch.json",
        {
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "mode": args.mode,
            "config": plan,
            "generated_at": stamp,
            "runs": results,
        },
    )
    print(f"\nbatch index: {batch_dir / 'batch.json'}")
    if errors:
        print(f"batch serialization errors: {errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
