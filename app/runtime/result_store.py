"""Thread-safe run state shared between the orchestrator and the Live View (v0.2.0).

The orchestrator writes agent lifecycle events, the run structure, the per-agent
results, and the final report here while a background thread runs the pipeline.
The Streamlit ``ui_live`` page polls ``snapshot()``, giving a live "AI Team" view
without coupling the scheduler to the UI.
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


class ResultStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[RunEvent] = []
        self.results: dict[str, AgentResult] = {}
        self.report: ResearchReport | None = None
        self.structure: dict[str, Any] | None = None
        self.done: bool = False
        self.error: str | None = None

    def record(self, event: RunEvent) -> None:
        with self._lock:
            self.events.append(event)

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

    def set_results(self, results: dict[str, AgentResult]) -> None:
        with self._lock:
            self.results = results

    def set_report(self, report: ResearchReport) -> None:
        with self._lock:
            self.report = report

    def mark_done(self, error: str | None = None) -> None:
        with self._lock:
            self.done = True
            self.error = error

    def status_of(self, agent_id: str) -> str:
        with self._lock:
            result = self.results.get(agent_id)
            if result is not None:
                return result.status.value
            last_event = None
            for event in self.events:
                if event.agent_id == agent_id:
                    last_event = event.event
            if last_event == "start":
                return "running"
            if last_event == "error":
                return "failed"
            return "pending"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events": [event.model_dump() for event in self.events],
                "results": {key: value.model_dump() for key, value in self.results.items()},
                "report": self.report.model_dump() if self.report is not None else None,
                "structure": self.structure,
                "done": self.done,
                "error": self.error,
            }
