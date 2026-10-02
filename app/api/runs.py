"""Run registry: start async executions of the existing Core session backend
and expose thread-safe read-only snapshots to the API routes.

Mirrors the v0.2 ``ResultStore`` pattern (background thread + snapshot) without
touching any Core module: ``execute_task`` remains the single orchestration
entry.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.runtime.session import CompletionCriteria, execute_task


@dataclass(eq=False)
class RunHandle:
    """One task run owned by the API layer."""

    task_id: str
    task: str
    mode: str  # "real" | "offline"
    created_at: float
    session: Any | None = None
    error: str | None = None  # background-thread crash (none if task-level)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _done_event: threading.Event = field(default_factory=threading.Event)

    @property
    def done(self) -> bool:
        return self._done_event.is_set()

    def snapshot(self) -> dict[str, Any]:
        """Thread-safe summary used by most API endpoints."""
        with self._lock:
            if self.session is None:
                return {
                    "task_id": self.task_id,
                    "task": self.task,
                    "mode": self.mode,
                    "created_at": self.created_at,
                    "status": "running",
                    "agent_results": {},
                    "agent_names": {},
                    "layers": [],
                    "edges": [],
                    "final_artifact": None,
                    "event_count": 0,
                    "started_at": None,
                    "finished_at": None,
                }
            session = self.session
            plan = getattr(session, "plan", None)
            layers = (
                [list(entry) for entry in plan.execution_layers]
                if plan is not None and getattr(plan, "execution_layers", None)
                else []
            )
            edges = [
                {"source": edge.source, "target": edge.target}
                for edge in (plan.dependencies if plan is not None else [])
            ]
            agent_results = {
                agent_id: {
                    "status": result.status.value,
                    "attempt": result.attempt,
                    "error": result.error,
                    "duration": result.duration,
                }
                for agent_id, result in session.agent_results.items()
            }
            final = None
            if session.final_artifact is not None:
                bundle = getattr(session, "synthesis_bundle", None)
                synthesis = getattr(bundle, "synthesis", None) if bundle is not None else None
                final = {
                    "status": session.status.value,
                    "title": session.final_artifact.title,
                    "markdown": session.final_artifact.to_markdown(),
                    "sources": [r.model_dump() for r in session.final_artifact.source_records],
                    "evidence": [e.model_dump() for e in session.final_artifact.evidence],
                    "sections": [
                        {
                            "title": section.title,
                            "agent_id": section.agent_id,
                            "agent_name": section.agent_name,
                            "output_type": section.output_type,
                            "content": section.content,
                            "structured_data": dict(section.structured_data),
                        }
                        for section in session.final_artifact.sections
                    ],
                    "insights": (
                        [item.model_dump() for item in synthesis.cross_agent_insights]
                        if synthesis is not None
                        else []
                    ),
                    "findings": _serialize_findings(synthesis),
                    "contradictions": (
                        [item.model_dump() for item in synthesis.contradictions]
                        if synthesis is not None
                        else []
                    ),
                    "uncertainties": (
                        [item.model_dump() for item in synthesis.uncertainties]
                        if synthesis is not None
                        else []
                    ),
                    "tradeoffs": (
                        [item.model_dump() for item in synthesis.tradeoffs]
                        if synthesis is not None
                        else []
                    ),
                    "recommendations": (
                        [item.model_dump() for item in synthesis.recommendations]
                        if synthesis is not None
                        else []
                    ),
                    "synthesis_status": str(
                        getattr(bundle, "status", "")
                        or session.final_artifact.metadata.get("synthesis_status", "")
                    ),
                    "synthesis_degradation_reason": str(
                        getattr(bundle, "degradation_reason", "")
                        or session.final_artifact.metadata.get(
                            "synthesis_degradation_reason", ""
                        )
                    ),
                    "reference_issues": list(
                        getattr(bundle, "reference_issues", []) or []
                    ),
                }
            return {
                "task_id": self.task_id,
                "task": self.task,
                "mode": self.mode,
                "created_at": self.created_at,
                "run_id": session.run_id,
                "status": session.status.value,
                "agent_results": agent_results,
                "agent_names": session.agent_names(),
                "layers": layers,
                "edges": edges,
                "final_artifact": final,
                "event_count": len(session.trace.events),
                "started_at": session.started_at,
                "finished_at": session.finished_at,
            }

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        """New ExecutionEvents since index ``after`` (Core objects, serialized)."""
        with self._lock:
            if self.session is None:
                return []
            events = self.session.trace.events[after:]
            return [
                {
                    "event_id": event.event_id,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp,
                    "type": event.type,
                    "agent_id": event.agent_id,
                    "message": event.message,
                    "metadata": dict(event.metadata),
                }
                for event in events
            ]

    def event_count(self) -> int:
        with self._lock:
            if self.session is None:
                return 0
            return len(self.session.trace.events)


class RunRegistry:
    """In-memory registry of runs (restart loses history — acceptable for a UI)."""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._lock = threading.Lock()

    def create(self, task: str, mode: str = "real") -> RunHandle:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        handle = RunHandle(
            task_id=task_id,
            task=task,
            mode=mode,
            created_at=time.time(),
        )
        with self._lock:
            self._runs[task_id] = handle
        return handle

    def start(self, handle: RunHandle) -> None:
        """Launch the existing Core ``execute_task`` in a daemon thread."""

        def _run() -> None:
            try:
                provider = None
                if handle.mode == "real":
                    from app.llm.provider import get_llm_provider

                    provider = get_llm_provider()
                # Offline runs must never hit live tools, even when .env
                # carries real search keys (LLM stays mock via provider=None).
                session = execute_task(
                    handle.task,
                    provider=provider,
                    tool_mode="auto" if handle.mode == "real" else "mock",
                    criteria=CompletionCriteria(
                        minimum_successful_agents=1, allow_partial=True
                    ),
                    timeout=600,
                    max_tool_calls=6,
                    max_iterations=6,
                )
                with handle._lock:
                    handle.session = session
            except Exception as exc:  # structured; never leak secrets
                with handle._lock:
                    handle.error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    handle.session = _failed_session(handle.task, exc)
            finally:
                handle._done_event.set()

        threading.Thread(target=_run, daemon=True, name=f"autoteam-{handle.task_id}").start()

    def get(self, task_id: str) -> RunHandle | None:
        with self._lock:
            return self._runs.get(task_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshots = [handle.snapshot() for handle in self._runs.values()]
        snapshots.sort(key=lambda snap: snap.get("created_at", 0), reverse=True)
        return snapshots


def _failed_session(task: str, exc: Exception) -> Any:
    """Minimal Session object when the background thread itself crashed."""
    import time as _time

    from app.runtime.session import SessionStatus, TaskExecutionSession

    session = TaskExecutionSession(task)
    session.status = SessionStatus.FAILED
    session.started_at = _time.time()
    session.finished_at = _time.time()
    session.error = f"{type(exc).__name__}: {str(exc)[:200]}"
    session.trace.record("TASK_COMPLETED", message="failed")
    return session


def _serialize_findings(synthesis: Any) -> list[dict[str, Any]]:
    """Merge key/supported/single-source findings, de-duplicated by id.

    Read-only projection of the real synthesis structure — no invented items.
    """
    if synthesis is None:
        return []
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in (
        getattr(synthesis, "key_findings", []),
        getattr(synthesis, "supported_findings", []),
        getattr(synthesis, "single_source_findings", []),
    ):
        for item in group:
            key = item.finding_id or f"_{len(merged)}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item.model_dump())
    return merged