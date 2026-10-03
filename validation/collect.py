"""Extract audit metrics from a real ``TaskExecutionSession``.

Every value here comes from a field that actually exists on the live models
(``ExecutionPlan``, ``AgentResult``, ``ExecutionTrace``, ``AgentArtifact``,
``ReportBundle``). Nothing is inferred from the task text, and unavailable
metrics are reported as ``null`` with a reason instead of a guess.

Truth flags (``provider_type`` / ``is_real_llm`` / ``provider_fallback`` /
``has_offline_fallback`` / ``synthesis_degraded`` / ``is_valid_real_e2e``) are
computed from the provider object and the recorded ``TOOL_CALLED`` events, so a
mock run can never be described as a real E2E run.
"""

from __future__ import annotations

import json
from typing import Any

from app.llm.provider import LLMProvider, MockLLMProvider

from .sanitize import domain_of, redact_text, sanitize_url

SCHEMA_VERSION = "1"

TOOL_KINDS = ("web", "local", "offline_mock", "offline_fallback")

# Metrics the current core cannot produce reliably. Kept explicit so the
# report never implies we measured something we did not.
UNAVAILABLE_METRICS: dict[str, str] = {
    "token_usage": (
        "Available only when a real CountingProvider observed a provider that returned "
        "response.usage (app/llm/provider.py captures it into last_response_meta and "
        "validation/counting_provider.py aggregates it). Offline runs and runs without a "
        "counting provider report null."
    ),
    "api_cost": (
        "Derived only from validation/pricing.py when token_usage is observed AND the model "
        "price is known; otherwise null. Never estimated or guessed."
    ),
    "tool_latency": "TOOL_CALLED events carry no timing fields.",
    "llm_call_latency_per_agent": (
        "Provider calls are not attributed to agents by the engine; only total per-call "
        "timings are available when a counting provider is used."
    ),
}


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _agent_rows(session: Any) -> list[dict[str, Any]]:
    plan = getattr(session, "plan", None)
    rows: list[dict[str, Any]] = []
    for agent in getattr(plan, "agents", []) or []:
        role = getattr(agent, "role", None)
        capabilities = getattr(role, "capabilities", []) or []
        rows.append(
            {
                "id": getattr(agent, "id", "") or "",
                "name": getattr(role, "name", "") or "",
                "goal": redact_text(getattr(role, "goal", ""), limit=400),
                "capabilities": [_enum_value(c) for c in capabilities],
                "tools": list(getattr(agent, "tools", []) or []),
            }
        )
    return rows


def _dag(session: Any) -> dict[str, Any]:
    plan = getattr(session, "plan", None)
    topology = getattr(plan, "topology", None)
    edges = [
        {"source": getattr(e, "source", ""), "target": getattr(e, "target", "")}
        for e in (getattr(topology, "edges", []) or [])
    ]
    layers = [[str(a) for a in layer] for layer in (getattr(plan, "execution_layers", []) or [])]
    return {
        "layer_count": len(layers),
        "layers": layers,
        "edges": edges,
        "edge_count": len(edges),
        "topology_type": _enum_value(getattr(topology, "type", None)),
    }


def _attempt_row(attempt: Any) -> dict[str, Any]:
    return {
        "attempt": getattr(attempt, "attempt", None),
        "status": _enum_value(getattr(attempt, "status", None)),
        "started_at": getattr(attempt, "started_at", None),
        "finished_at": getattr(attempt, "finished_at", None),
        "duration": getattr(attempt, "duration", None),
        "error": redact_text(getattr(attempt, "error", ""), limit=300)
        if getattr(attempt, "error", None)
        else "",
    }


def _execution_rows(session: Any, names: dict[str, str]) -> tuple[list[dict], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counts = {"success": 0, "failed": 0, "skipped": 0, "pending": 0, "running": 0, "ready": 0}
    for agent_id, result in (getattr(session, "agent_results", {}) or {}).items():
        status = str(_enum_value(getattr(result, "status", "pending")))
        counts[status] = counts.get(status, 0) + 1
        attempts = [_attempt_row(a) for a in (getattr(result, "attempts", []) or [])]
        attempt = int(getattr(result, "attempt", 1) or 1)
        rows.append(
            {
                "agent_id": agent_id,
                "agent_name": names.get(agent_id, agent_id),
                "status": status,
                "attempt": attempt,
                "retries": max(0, attempt - 1),
                "error": redact_text(getattr(result, "error", ""), limit=300)
                if getattr(result, "error", None)
                else "",
                "started_at": getattr(result, "started_at", None),
                "finished_at": getattr(result, "finished_at", None),
                "duration": getattr(result, "duration", None),
                "attempts": attempts,
            }
        )
    return rows, counts


def max_concurrency_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive peak concurrency from agent/attempt intervals.

    This is a *derived* value: the core records per-agent monotonic timestamps
    but no explicit concurrency counter for the real runtime, so we sweep the
    intervals. It is explicitly labelled as derived.
    """
    events: list[tuple[float, int]] = []
    for row in results:
        intervals = [
            (a.get("started_at"), a.get("finished_at"))
            for a in row.get("attempts", [])
            if a.get("started_at") is not None and a.get("finished_at") is not None
        ]
        has_span = row.get("started_at") is not None and row.get("finished_at") is not None
        if not intervals and has_span:
            intervals = [(row["started_at"], row["finished_at"])]
        for start, end in intervals:
            if end < start:
                start, end = end, start
            events.append((float(start), 1))
            events.append((float(end), -1))
    if not events:
        return {
            "value": None,
            "is_derived": True,
            "method": "interval_sweep",
            "note": "no attempt intervals available",
        }
    events.sort(key=lambda item: (item[0], -item[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return {
        "value": peak,
        "is_derived": True,
        "method": "interval_sweep",
        "note": (
            "derived from per-agent monotonic start/finish intervals; the core records no "
            "explicit concurrency counter for the real runtime"
        ),
    }


def _trace_events(session: Any) -> list[Any]:
    trace = getattr(session, "trace", None)
    return list(getattr(trace, "events", []) or [])


def _tools_from_trace(events: list[Any]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    for event in events:
        if getattr(event, "type", "") != "TOOL_CALLED":
            continue
        meta = getattr(event, "metadata", {}) or {}
        calls.append(
            {
                "agent_id": getattr(event, "agent_id", "") or "",
                "tool": str(meta.get("tool", "") or ""),
                "kind": str(meta.get("tool_kind", "") or ""),
                "offline": bool(meta.get("offline", False)),
                "error": redact_text(meta.get("error", ""), limit=200)
                if meta.get("error")
                else "",
                "message": redact_text(getattr(event, "message", ""), limit=200),
            }
        )
    by_kind = {kind: 0 for kind in TOOL_KINDS}
    for call in calls:
        by_kind[call["kind"]] = by_kind.get(call["kind"], 0) + 1
    return {
        "total": len(calls),
        "by_kind": by_kind,
        "failures": sum(1 for c in calls if c["error"]),
        "calls": calls,
    }


def _events_of_type(events: list[Any], event_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if getattr(event, "type", "") != event_type:
            continue
        rows.append(
            {
                "agent_id": getattr(event, "agent_id", "") or "",
                "message": redact_text(getattr(event, "message", ""), limit=300),
                "metadata": {
                    key: redact_text(value, limit=200)
                    for key, value in (getattr(event, "metadata", {}) or {}).items()
                    if key not in {"prompt", "response", "content"}
                },
            }
        )
    return rows


def _artifacts(session: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    for artifact in getattr(session, "artifacts", []) or []:
        items.append(
            {
                "artifact_id": getattr(artifact, "artifact_id", ""),
                "agent_id": getattr(artifact, "agent_id", ""),
                "output_type": str(_enum_value(getattr(artifact, "output_type", ""))),
                "title": redact_text(getattr(artifact, "title", ""), limit=200),
                "content_chars": len(getattr(artifact, "content", "") or ""),
                "dependency_count": len(getattr(artifact, "dependencies", []) or []),
                "source_count": len(getattr(artifact, "source_records", []) or []),
                "evidence_count": len(getattr(artifact, "evidence", []) or []),
            }
        )
    return {"count": len(items), "items": items}, items


def _provenance(session: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = getattr(session, "synthesis_bundle", None)
    final = getattr(session, "final_artifact", None)
    evidence: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    if bundle is not None and getattr(bundle, "evidence", None):
        for item in bundle.evidence:
            evidence.append(
                {
                    "evidence_id": getattr(item, "evidence_id", ""),
                    "claim": redact_text(getattr(item, "claim", ""), limit=300),
                    "source_id": getattr(item, "source_id", ""),
                    "source_type": getattr(item, "source_type", ""),
                    "producer_agent": getattr(item, "producer_agent", ""),
                    "artifact_id": getattr(item, "artifact_id", ""),
                    "claim_type": getattr(item, "claim_type", ""),
                    "verified": bool(getattr(item, "verified", False)),
                    "review_status": getattr(item, "review_status", "not_checked"),
                    "match_score": getattr(item, "match_score", None),
                    "match_method": getattr(item, "match_method", ""),
                    # Full retrieved snippet lives here (the report renders only a clip).
                    "evidence_text": redact_text(getattr(item, "evidence", ""), limit=4000),
                    "source_domain": domain_of(getattr(item, "source_url", "")),
                }
            )
    elif final is not None:
        for item in getattr(final, "evidence", []) or []:
            evidence.append(
                {
                    "evidence_id": getattr(item, "evidence_id", ""),
                    "claim": redact_text(getattr(item, "claim", ""), limit=300),
                    "source_id": getattr(item, "source_id", ""),
                    "source_type": "",
                    "producer_agent": getattr(item, "producer_agent", ""),
                    "artifact_id": getattr(item, "artifact_id", ""),
                    "claim_type": getattr(item, "claim_type", ""),
                    "verified": True,
                    "source_domain": "",
                }
            )

    if bundle is not None and getattr(bundle, "sources", None):
        for item in bundle.sources:
            url = getattr(item, "url", "")
            sources.append(
                {
                    "source_id": getattr(item, "source_id", ""),
                    "title": redact_text(getattr(item, "title", ""), limit=200),
                    "source_type": getattr(item, "source_type", ""),
                    "url": sanitize_url(url),
                    "domain": domain_of(url),
                    "retrieved_at": redact_text(getattr(item, "retrieved_at", ""), limit=40),
                    "producer_agents": list(getattr(item, "producer_agents", []) or []),
                    "artifact_ids": list(getattr(item, "artifact_ids", []) or []),
                    # v0.6.9 (F13): stable identity + audit fields.
                    "identity": redact_text(getattr(item, "identity", ""), limit=200),
                    "alt_titles": [
                        redact_text(title, limit=120)
                        for title in (getattr(item, "alt_titles", []) or [])
                    ],
                    "first_seen_agent": redact_text(
                        getattr(item, "first_seen_agent", ""), limit=80
                    ),
                    "access_status": getattr(item, "access_status", ""),
                    "access_note": redact_text(getattr(item, "access_note", ""), limit=120),
                }
            )
    elif final is not None:
        for item in getattr(final, "source_records", []) or []:
            url = getattr(item, "url", "")
            sources.append(
                {
                    "source_id": getattr(item, "id", ""),
                    "title": redact_text(getattr(item, "title", ""), limit=200),
                    "source_type": getattr(item, "source_type", ""),
                    "url": sanitize_url(url),
                    "domain": domain_of(url),
                    "retrieved_at": redact_text(getattr(item, "retrieved_at", ""), limit=40),
                    "producer_agents": [],
                    "artifact_ids": [],
                }
            )

    by_type: dict[str, int] = {}
    for source in sources:
        key = source["source_type"] or "unknown"
        by_type[key] = by_type.get(key, 0) + 1

    return (
        {"count": len(evidence), "items": evidence},
        {"count": len(sources), "by_type": by_type, "items": sources},
    )


def _dump_items(items: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Serialise synthesis items by their real fields (missing -> None)."""
    rows: list[dict[str, Any]] = []
    for item in items or []:
        row: dict[str, Any] = {}
        for field in fields:
            value = getattr(item, field, None)
            if isinstance(value, list):
                row[field] = [
                    redact_text(entry, limit=200) if isinstance(entry, str) else entry
                    for entry in value
                ]
            elif isinstance(value, str):
                row[field] = redact_text(value, limit=600)
            else:
                row[field] = value
        rows.append(row)
    return rows


def parse_dedup_audit(notes: str) -> dict[str, Any]:
    """Extract the deterministic finding-dedup audit appended to synthesis notes."""
    marker = "dedup: "
    index = (notes or "").find(marker)
    if index < 0:
        return {}
    try:
        parsed = json.loads(notes[index + len(marker):])
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _selection_summary(selection: dict[str, Any]) -> dict[str, Any]:
    """Compact view of the evidence-selection audit (v0.6.6, A2).

    Keeps the coverage comparison + gap list and drops the per-record ``dropped``
    rows, which are written in full to ``synthesis_audit.json``.
    """
    if not selection:
        return {}
    keep = (
        "policy_version", "criteria", "total", "per_agent_cap", "before",
        "selected_count", "distinct_evidence_ids", "duplicate_ids_removed",
        "coverage_before", "coverage_after", "coverage_gaps", "coverage_gap_note",
        "dropped_count",
    )
    return {key: selection.get(key) for key in keep if key in selection}


def _synthesis(session: Any, events: list[Any]) -> dict[str, Any]:
    bundle = getattr(session, "synthesis_bundle", None)
    failed_events = _events_of_type(events, "SYNTHESIS_FAILED")
    if bundle is None:
        return {
            "available": False,
            "status": "unavailable",
            "synthesis_status": "unavailable",
            "fallback_used": True,
            "fallback_reason": "",
            "retry_count": 0,
            "validation_errors": [],
            "dedup": {},
            "dedup_audit": {},
            "findings": [],
            "insights": [],
            "contradictions": [],
            "uncertainties": [],
            "tradeoffs": [],
            "recommendations": [],
            "degraded": True,
            "degradation_reason": failed_events[0]["message"] if failed_events else "",
            "counts": {},
            "evidence_selection": {},
            "claim_audit": [],
            "source_gaps": [],
            "reference_issues": [],
            "events": _events_of_type(events, "SYNTHESIS_COMPLETED")
            + _events_of_type(events, "SYNTHESIS_VALIDATED")
            + failed_events,
        }
    result = getattr(bundle, "synthesis", None)
    counts = {
        "key_findings": len(getattr(result, "key_findings", []) or []),
        # Legacy LLM-proposed lists, kept verbatim for compatibility. They are
        # routinely empty; the authoritative breakdown is ``finding_counts``.
        "supported_findings": len(getattr(result, "supported_findings", []) or []),
        "single_source_findings": len(getattr(result, "single_source_findings", []) or []),
        "cross_agent_insights": len(getattr(result, "cross_agent_insights", []) or []),
        "contradictions": len(getattr(result, "contradictions", []) or []),
        "uncertainties": len(getattr(result, "uncertainties", []) or []),
        "tradeoffs": len(getattr(result, "tradeoffs", []) or []),
        "recommendations": len(getattr(result, "recommendations", []) or []),
    }
    # D2: deterministic, code-derived classification of the *same* findings.
    counts["finding_counts"] = dict(getattr(result, "finding_counts", {}) or {})
    status = str(getattr(bundle, "status", "") or "unknown")
    dedup_audit = parse_dedup_audit(getattr(result, "notes", "") or "")
    return {
        "available": True,
        "status": status,
        "synthesis_status": status,
        "fallback_used": bool(getattr(bundle, "fallback_used", status != "completed")),
        "fallback_reason": redact_text(getattr(bundle, "fallback_reason", ""), limit=300),
        "retry_count": int(getattr(bundle, "retry_count", 0) or 0),
        "validation_errors": [
            redact_text(issue, limit=200)
            for issue in (getattr(bundle, "validation_errors", []) or [])
        ],
        "stage_audit": list(
            getattr(bundle, "stage_audit", []) or getattr(result, "stage_audit", []) or []
        ),
        # v0.6.6 audits: selection coverage (A2), per-claim citation checks (A1)
        # and structured source gaps (A3). The full per-record selection audit
        # lives in synthesis_audit.json so this file stays readable.
        "evidence_selection": _selection_summary(
            getattr(bundle, "evidence_selection", {})
            or getattr(result, "evidence_selection", {})
            or {}
        ),
        "claim_audit": list(getattr(bundle, "claim_audit", []) or []),
        "source_gaps": list(getattr(bundle, "source_gaps", []) or []),
        "source_conflicts": list(getattr(bundle, "source_conflicts", []) or []),
        "dedup": dedup_audit,
        "dedup_audit": dedup_audit,
        "findings": _dump_items(
            getattr(result, "key_findings", []),
            ("finding_id", "statement", "evidence_ids", "supporting_agents",
             "support_kind", "claim_type", "notes", "derivation",
             # v0.6.6: agent vs independent-source counts + citation check.
             "support_level", "evidence_count", "agent_support_count",
             "independent_source_count", "review_status", "unsupported_parts"),
        ),
        "insights": _dump_items(
            getattr(result, "cross_agent_insights", []),
            ("insight_id", "statement", "supporting_evidence_ids",
             "supporting_artifact_ids", "producer_agents", "contributing_agents",
             "uncertainty", "claim_type", "derivation"),
        ),
        "contradictions": _dump_items(
            getattr(result, "contradictions", []),
            ("contradiction_id", "claim_a", "claim_b", "evidence_ids",
             "source_ids", "agents", "status", "resolution"),
        ),
        "uncertainties": _dump_items(
            getattr(result, "uncertainties", []),
            ("uncertainty_id", "statement", "evidence_ids", "kind", "note"),
        ),
        "tradeoffs": _dump_items(
            getattr(result, "tradeoffs", []),
            ("tradeoff_id", "dimension", "option_a", "option_b", "gains_a",
             "costs_a", "gains_b", "costs_b", "evidence_ids", "implications"),
        ),
        "recommendations": _dump_items(
            getattr(result, "recommendations", []),
            ("recommendation_id", "statement", "supporting_insight_ids",
             "supporting_tradeoff_ids", "supporting_evidence_ids", "status",
             "limitations", "claim_type"),
        ),
        "degraded": status != "completed",
        "degradation_reason": redact_text(
            getattr(bundle, "degradation_reason", ""), limit=300
        ),
        "counts": counts,
        "summary_chars": len(getattr(result, "summary", "") or ""),
        # D3: disclose how the summary was obtained (never a silent fallback).
        "summary_status": str(getattr(result, "summary_status", "") or ""),
        "summary_reason": redact_text(getattr(result, "summary_reason", ""), limit=300),
        "summary": redact_text(getattr(result, "summary", "") or "", limit=2000),
        "reference_issues": [
            redact_text(issue, limit=200)
            for issue in (getattr(bundle, "reference_issues", []) or [])
        ],
        "events": _events_of_type(events, "SYNTHESIS_COMPLETED")
        + _events_of_type(events, "SYNTHESIS_VALIDATED")
        + failed_events,
    }


def determine_truth(
    *,
    provider: LLMProvider | Any | None,
    tool_metrics: dict[str, Any],
    llm_call_count: int | None,
    provider_fallback: bool,
    synthesis_degraded: bool,
    core_data_present: bool,
    requires_web_search: bool = True,
    blocked_llm_calls: int = 0,
    aborted: bool = False,
    abort_reason: str = "",
) -> dict[str, Any]:
    """Decide whether a run counts as a *valid real E2E* run — strictly.

    A run stopped by the validation budget (hard timeout, or provider requests
    refused by ``--max-llm-calls``) can never be a valid real E2E run.
    """
    is_mock = provider is None or isinstance(provider, MockLLMProvider)
    is_real_llm = provider is not None and not is_mock
    web_calls = int(tool_metrics.get("by_kind", {}).get("web", 0))
    offline_calls = sum(
        int(tool_metrics.get("by_kind", {}).get(kind, 0))
        for kind in ("offline_mock", "offline_fallback")
    )
    has_offline_fallback = int(tool_metrics.get("by_kind", {}).get("offline_fallback", 0)) > 0
    all_searches_offline = offline_calls > 0 and web_calls == 0

    reasons: list[str] = []
    if is_mock:
        reasons.append("provider is MockLLMProvider (or unset) - not a real LLM run")
    if not is_mock and llm_call_count == 0:
        reasons.append("no provider calls were observed")
    if provider_fallback:
        reasons.append("provider fell back to the deterministic mock mid-run")
    if requires_web_search and web_calls == 0:
        reasons.append("no real web_search call observed although the scenario needs one")
    if all_searches_offline:
        reasons.append("every search call was offline_mock/offline_fallback")
    if has_offline_fallback:
        reasons.append("at least one search degraded to offline_fallback")
    if synthesis_degraded:
        reasons.append("synthesis did not complete cleanly")
    if not core_data_present:
        reasons.append("plan/agent results missing - cannot confirm the execution path")
    if aborted:
        reasons.append(f"run was aborted by the validation budget ({abort_reason or 'unknown'})")
    if blocked_llm_calls:
        reasons.append(f"{blocked_llm_calls} provider request(s) were refused by the budget")

    if aborted:
        verdict = "aborted_budget"
    elif not is_real_llm or (llm_call_count == 0 and not is_mock):
        verdict = "not_real_llm"
    elif provider_fallback:
        verdict = "invalid_provider_fallback"
    elif blocked_llm_calls > 0:
        # Real execution happened but the budget cut it short -> partial, never a pass.
        verdict = "degraded_partial"
    elif requires_web_search and web_calls == 0:
        verdict = "invalid_missing_real_web_search"
    elif not core_data_present:
        verdict = "invalid_missing_core_data"
    elif has_offline_fallback or synthesis_degraded:
        verdict = "degraded_partial"
    else:
        verdict = "valid_real_e2e"

    return {
        "provider_type": type(provider).__name__ if provider is not None else "MockLLMProvider",
        "provider_instance_provided": provider is not None,
        "provider_note": (
            ""
            if provider is not None
            else "no provider object was passed; execute_task uses its internal MockLLMProvider"
        ),
        "is_mock": is_mock,
        "is_real_llm": is_real_llm,
        "is_real_web_search": web_calls > 0,
        "provider_fallback": provider_fallback,
        "has_offline_fallback": has_offline_fallback,
        "all_searches_offline": all_searches_offline,
        "synthesis_degraded": synthesis_degraded,
        "llm_call_count": llm_call_count,
        "blocked_llm_calls": blocked_llm_calls,
        "aborted": aborted,
        "abort_reason": abort_reason,
        "web_search_calls": web_calls,
        "offline_search_calls": offline_calls,
        "is_valid_real_e2e": verdict == "valid_real_e2e",
        "is_real_execution": is_real_llm and web_calls > 0 and not provider_fallback,
        "verdict": verdict,
        "reasons": reasons,
    }


def collect_metrics(
    session: Any,
    *,
    scenario_id: str,
    mode: str,
    provider: LLMProvider | Any | None = None,
    counting: Any | None = None,
    measured_elapsed: float | None = None,
    requires_web_search: bool = True,
    termination_reason: str = "completed",
    aborted: bool = False,
) -> dict[str, Any]:
    """Build the metrics document for one run. Pure function of the session."""
    events = _trace_events(session)
    names = {}
    if hasattr(session, "agent_names"):
        try:
            names = dict(session.agent_names())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - defensive: never lose the run record
            names = {}

    agent_rows, counts = _execution_rows(session, names)
    tool_metrics = _tools_from_trace(events)
    artifact_metrics, _ = _artifacts(session)
    evidence_metrics, source_metrics = _provenance(session)
    synthesis = _synthesis(session, events)

    started = getattr(session, "started_at", None)
    finished = getattr(session, "finished_at", None)
    elapsed = (finished - started) if (started and finished) else measured_elapsed

    provider_fallback_events = _events_of_type(events, "PROVIDER_FALLBACK")
    final = getattr(session, "final_artifact", None)
    metadata = getattr(final, "metadata", {}) or {}
    provider_fallback = bool(metadata.get("provider_fallback")) or bool(provider_fallback_events)

    llm_summary = None
    llm_call_count: int | None = None
    blocked_llm_calls = 0
    estimated_cost: float | None = None
    if counting is not None:
        llm_summary = counting.summary()
        llm_call_count = int(llm_summary.get("count", 0))
        blocked_llm_calls = int(llm_summary.get("blocked", 0))
        token_usage = llm_summary.get("token_usage")
        model = getattr(provider, "model", "") if provider is not None else ""
        if isinstance(token_usage, dict) and model:
            try:
                from .pricing import compute_cost

                estimated_cost = compute_cost(model, token_usage)
            except Exception:  # noqa: BLE001 - cost is best-effort, never fatal
                estimated_cost = None

    truth = determine_truth(
        provider=provider,
        tool_metrics=tool_metrics,
        llm_call_count=llm_call_count,
        provider_fallback=provider_fallback,
        synthesis_degraded=bool(synthesis["degraded"]),
        core_data_present=bool(agent_rows) and getattr(session, "plan", None) is not None,
        requires_web_search=requires_web_search,
        blocked_llm_calls=blocked_llm_calls,
        aborted=aborted,
        abort_reason=termination_reason,
    )

    retries = sum(int(row["retries"]) for row in agent_rows)
    unavailable = dict(UNAVAILABLE_METRICS)
    if llm_summary is None:
        unavailable["llm_call_count"] = (
            "no counting provider was attached to this run (offline runs pass provider=None "
            "so the engine's authentic offline branch and metadata stay correct)"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": getattr(session, "run_id", ""),
        "scenario_id": scenario_id,
        "mode": mode,
        "task": redact_text(getattr(session, "task", ""), limit=2000),
        "session_status": str(_enum_value(getattr(session, "status", ""))),
        "session_error": redact_text(getattr(session, "error", ""), limit=300)
        if getattr(session, "error", None)
        else "",
        "provider": {
            "type": truth["provider_type"],
            "model": getattr(provider, "model", "") if provider is not None else "",
            "is_mock": truth["is_mock"],
            "is_real_llm": truth["is_real_llm"],
            "llm_calls": llm_summary,
            "llm_call_count": llm_call_count,
            "estimated_cost_usd": estimated_cost,
        },
        "team": {
            "agent_count": len(agent_rows),
            "agents": _agent_rows(session),
            "dag": _dag(session),
        },
        "execution": {
            "total_elapsed_seconds": round(elapsed, 3) if elapsed is not None else None,
            "started_at_epoch": started,
            "finished_at_epoch": finished,
            "agent_results": agent_rows,
            "counts": counts,
            "retry_total": retries,
            "replan_events": _events_of_type(events, "AGENT_REPLANNED"),
            "max_concurrency": max_concurrency_from_results(agent_rows),
            "agent_clock_note": (
                "Agent/attempt start & finish use time.perf_counter (monotonic); they are "
                "comparable within one run only and are not wall-clock timestamps."
            ),
        },
        "tools": tool_metrics,
        "artifacts": {
            **artifact_metrics,
            "rejected": _events_of_type(events, "ARTIFACT_REJECTED"),
            "rejected_count": len(_events_of_type(events, "ARTIFACT_REJECTED")),
        },
        "evidence": evidence_metrics,
        "sources": source_metrics,
        "synthesis": synthesis,
        "termination": {
            "reason": termination_reason,
            "aborted": aborted,
            "run_timeout": termination_reason == "run_timeout",
            "budget_exhausted": termination_reason == "llm_budget_exhausted",
            "note": (
                "Cooperative cancellation stops NEW provider requests at the budget/deadline; "
                "an in-flight synchronous HTTP request cannot be interrupted."
            ),
        },
        "truth": truth,
        "unavailable_metrics": unavailable,
        "event_counts": {
            event_type: sum(1 for e in events if getattr(e, "type", "") == event_type)
            for event_type in sorted({getattr(e, "type", "") for e in events})
        },
    }


def collect_aborted_metrics(
    *,
    scenario_id: str,
    mode: str,
    provider: Any | None,
    counting: Any | None,
    reason: str,
    elapsed: float | None,
    task: str = "",
) -> dict[str, Any]:
    """Metrics document for a run hard-aborted before the core engine returned.

    ``execute_task`` returns the session only on completion, so no trace / agent
    results / artifacts are retrievable when the wall-clock timeout fires. What
    *is* observable (the provider call log, budget blocks, wall-clock) is kept,
    and the gap is stated explicitly rather than filled with invented values.
    """
    llm_summary = counting.summary() if counting is not None else None
    blocked = int(llm_summary.get("blocked", 0)) if llm_summary else 0
    truth = determine_truth(
        provider=provider,
        tool_metrics={"by_kind": {}},
        llm_call_count=int(llm_summary.get("count", 0)) if llm_summary else None,
        provider_fallback=False,
        synthesis_degraded=True,
        core_data_present=False,
        requires_web_search=True,
        blocked_llm_calls=blocked,
        aborted=True,
        abort_reason=reason,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "",
        "scenario_id": scenario_id,
        "mode": mode,
        "task": redact_text(task, limit=2000),
        "session_status": "aborted",
        "session_error": "",
        "provider": {
            "type": truth["provider_type"],
            "model": getattr(provider, "model", "") if provider is not None else "",
            "is_mock": truth["is_mock"],
            "is_real_llm": truth["is_real_llm"],
            "llm_calls": llm_summary,
            "llm_call_count": truth["llm_call_count"],
        },
        "team": {
            "agent_count": 0,
            "agents": [],
            "dag": {"layer_count": 0, "layers": [], "edges": [], "edge_count": 0},
        },
        "execution": {
            "total_elapsed_seconds": round(elapsed, 3) if elapsed is not None else None,
            "agent_results": [],
            "counts": {},
            "retry_total": 0,
            "replan_events": [],
            "max_concurrency": {
                "value": None,
                "is_derived": True,
                "method": "interval_sweep",
                "note": "run aborted before completion",
            },
        },
        "tools": {"total": 0, "by_kind": {}, "failures": 0, "calls": []},
        "artifacts": {"count": 0, "items": [], "rejected": [], "rejected_count": 0},
        "evidence": {"count": 0, "items": []},
        "sources": {"count": 0, "by_type": {}, "items": []},
        "synthesis": {
            "available": False,
            "status": "unavailable",
            "degraded": True,
            "degradation_reason": reason,
            "counts": {},
            "reference_issues": [],
            "events": [],
        },
        "termination": {
            "reason": reason,
            "aborted": True,
            "run_timeout": reason == "run_timeout",
            "budget_exhausted": reason == "llm_budget_exhausted",
            "note": (
                "Cooperative cancellation stops NEW provider requests at the budget/deadline; "
                "an in-flight synchronous HTTP request cannot be interrupted."
            ),
        },
        "truth": truth,
        "unavailable_metrics": dict(
            UNAVAILABLE_METRICS,
            session_data=(
                "the run was aborted before execute_task returned; the core exposes the "
                "session only on completion, so trace/agent results/artifacts are unavailable"
            ),
        ),
        "event_counts": {},
    }


def build_truth_flags(metrics: dict[str, Any]) -> dict[str, Any]:
    """Compact truth block for the console summary / batch index."""
    truth = metrics.get("truth", {})
    return {
        "provider_type": truth.get("provider_type"),
        "is_real_llm": truth.get("is_real_llm"),
        "is_real_web_search": truth.get("is_real_web_search"),
        "provider_fallback": truth.get("provider_fallback"),
        "has_offline_fallback": truth.get("has_offline_fallback"),
        "synthesis_degraded": truth.get("synthesis_degraded"),
        "is_valid_real_e2e": truth.get("is_valid_real_e2e"),
        "verdict": truth.get("verdict"),
        "reasons": list(truth.get("reasons", [])),
    }
