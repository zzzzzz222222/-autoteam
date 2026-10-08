"""Thread-safe run state shared between the orchestrator and the Live View (v0.2.0).

The orchestrator writes agent lifecycle events, the run structure, the per-agent
results, and the final report here while a background thread runs the pipeline.
The Streamlit ``ui_live`` page polls ``snapshot()``, giving a live "AI Team" view
without coupling the scheduler to the UI.

v0.6.2 (AT-AUDIT-002): per-run isolation.

A long-lived ``ResultStore`` can outlive a single run (``ResearchOrchestrator``
keeps one store for its whole lifetime; Streamlit keeps one in the session while
polling). Previously every event was appended to one flat list and ``status_of``
scanned *all* of it, so a second run could read statuses left behind by the first
one. Events and results are now partitioned by ``run_id``:

* ``RunEvent`` carries the owning ``run_id`` (default ``""`` so existing
  constructors keep working);
* ``record``/``set_results`` file each entry under its run;
* ``status_of`` only consults the requested run (or the store's current run);
* ``snapshot(run_id=...)`` returns that run's slice.

Nothing is ever *cleared*: an entry filed under run A stays available to run A
even while run B is mid-flight, so concurrent runs cannot delete each other's
data. Stores that never bind a run behave exactly as before (all events share the
``""`` bucket, and the un-scoped, aggregate view is preserved for compatibility).
"""

from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel

from app.models.agent import AgentSpec
from app.models.topology import Topology
from app.runtime.models import ResearchReport, SubtaskPlan
from app.scheduler.models import AgentResult


class RunEvent(BaseModel):
    agent_id: str
    event: str  # "start" | "done" | "error"
    timestamp: float
    message: str = ""
    # v0.6.2 (AT-AUDIT-002): owning run. Empty means "no run declared", which is
    # the pre-v0.6.2 behaviour and is still accepted.
    run_id: str = ""


class ResultStore:
    def __init__(self) -> None:
        # Re-entrant: status_of/snapshot may be called while another method of
        # this store holds the lock.
        self._lock = threading.RLock()
        # Legacy aggregate views, kept for backward compatibility.
        self.events: list[RunEvent] = []
        self.results: dict[str, AgentResult] = {}
        self.report: ResearchReport | None = None
        self.structure: dict[str, Any] | None = None
        self.done: bool = False
        self.error: str | None = None
        # v0.6.2: per-run partitions (same objects as `events`, never duplicates).
        self._events_by_run: dict[str, list[RunEvent]] = {}
        self._results_by_run: dict[str, dict[str, AgentResult]] = {}
        # Run that `status_of`/`snapshot` default to. ``None`` = no run bound yet,
        # which preserves the historical aggregate behaviour.
        self.current_run_id: str | None = None

    # --- run scoping -------------------------------------------------------
    def start_run(self, run_id: str) -> str:
        """Bind (and remember) the run subsequent writes belong to.

        This never clears anything: earlier runs keep their partitions intact so
        a still-running task never loses its events.
        """
        with self._lock:
            self.current_run_id = run_id
            self._events_by_run.setdefault(run_id, [])
            return run_id

    def _resolve_run_id(self, explicit: str | None, event_run_id: str) -> str:
        """Explicit argument wins, then the event's own id, then the bound run."""
        if explicit:
            return explicit
        if event_run_id:
            return event_run_id
        with self._lock:
            return self.current_run_id or ""

    def runs(self) -> list[str]:
        """Every run id that has filed at least one event/result here."""
        with self._lock:
            return sorted(set(self._events_by_run) | set(self._results_by_run))

    def events_of(self, run_id: str) -> list[RunEvent]:
        """This run's events only, in the order they were recorded."""
        with self._lock:
            return list(self._events_by_run.get(run_id, []))

    # --- writes ------------------------------------------------------------
    def record(self, event: RunEvent, run_id: str | None = None) -> None:
        resolved = self._resolve_run_id(run_id, event.run_id)
        if not event.run_id:
            # Stamp the ownership so the entry is self-describing downstream.
            event.run_id = resolved
        with self._lock:
            self.events.append(event)
            self._events_by_run.setdefault(resolved, []).append(event)

    def set_structure(
        self, plan: SubtaskPlan, agents: list[AgentSpec], topology: Topology
    ) -> None:
        with self._lock:
            self.structure = {
                "subtasks": [sub.model_dump() for sub in plan.subtasks],
                "agents": [agent.id for agent in agents],
                "agent_names": {agent.id: agent.role.name for agent in agents},
                "parallel_layers": [list(layer) for layer in topology.parallel_layers],
            }

    def set_results(
        self, results: dict[str, AgentResult], run_id: str | None = None
    ) -> None:
        resolved = self._resolve_run_id(run_id, "")
        with self._lock:
            self.results = results
            self._results_by_run[resolved] = dict(results)

    def set_report(self, report: ResearchReport) -> None:
        with self._lock:
            self.report = report

    def mark_done(self, error: str | None = None) -> None:
        with self._lock:
            self.done = True
            self.error = error

    # --- reads -------------------------------------------------------------
    def status_of(self, agent_id: str, run_id: str | None = None) -> str:
        """Status of one agent, scoped to a single run.

        ``run_id`` given  -> only that run's results/events are consulted.
        ``run_id`` omitted-> the store's current run; if no run was ever bound,
                             the historical aggregate view is returned so
                             pre-v0.6.2 callers behave exactly as before.
        """
        with self._lock:
            if run_id is not None:
                scoped = run_id
            else:
                scoped = self.current_run_id
            if scoped is None:
                results = self.results
                events = self.events
            else:
                results = self._results_by_run.get(scoped) or {}
                events = self._events_by_run.get(scoped, [])
            result = results.get(agent_id)
            if result is not None:
                return result.status.value
            last_event = None
            for event in events:
                if event.agent_id == agent_id:
                    last_event = event.event
            if last_event == "start":
                return "running"
            if last_event == "error":
                return "failed"
            return "pending"

    def snapshot(self, run_id: str | None = None) -> dict[str, Any]:
        """Snapshot of one run, or the legacy aggregate view when unscoped."""
        with self._lock:
            if run_id is None and self.current_run_id is None:
                events = list(self.events)
                results = dict(self.results)
            elif run_id is None:
                events = list(self._events_by_run.get(self.current_run_id or "", []))
                results = dict(self._results_by_run.get(self.current_run_id or "", {}))
            else:
                events = list(self._events_by_run.get(run_id, []))
                results = dict(self._results_by_run.get(run_id, {}))
            return {
                "events": [event.model_dump() for event in events],
                "results": {key: value.model_dump() for key, value in results.items()},
                "report": self.report.model_dump() if self.report is not None else None,
                "structure": self.structure,
                "done": self.done,
                "error": self.error,
            }
