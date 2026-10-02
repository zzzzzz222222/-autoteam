"""Structured execution trace (v0.4.0).

Records what happened during a task run as a flat list of typed events —
never chain-of-thought. Kept in its own module so both the runtime and the
session can import it without circular dependencies.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

EVENT_TYPES = (
    "TASK_STARTED",
    "TEAM_FORMED",
    "AGENT_READY",
    "AGENT_STARTED",
    "TOOL_CALLED",
    "AGENT_OUTPUT",
    "ARTIFACT_CREATED",
    "ARTIFACT_REJECTED",
    "AGENT_FAILED",
    "AGENT_RETRY",
    "AGENT_REPLANNED",
    "PROVIDER_FALLBACK",
    "SYNTHESIS_STARTED",
    "EVIDENCE_FILTERED",
    "SYNTHESIS_VALIDATED",
    "INSIGHT_EXTRACTED",
    "CONTRADICTION_FOUND",
    "TRADEOFF_FOUND",
    "SYNTHESIS_COMPLETED",
    "SYNTHESIS_FAILED",
    "TASK_COMPLETED",
)


class ExecutionEvent(BaseModel):
    event_id: str
    run_id: str
    timestamp: float
    type: str
    agent_id: str = ""
    message: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class ExecutionTrace:
    """In-memory, append-only event log for one run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[ExecutionEvent] = []

    def record(
        self,
        event_type: str,
        agent_id: str = "",
        message: str = "",
        **metadata: object,
    ) -> ExecutionEvent:
        event = ExecutionEvent(
            event_id=f"evt_{len(self.events) + 1:04d}",
            run_id=self.run_id,
            timestamp=time.time(),
            type=event_type,
            agent_id=agent_id,
            message=message[:300],  # structured messages only, never CoT
            metadata=metadata,
        )
        self.events.append(event)
        return event

    def of_type(self, event_type: str) -> list[ExecutionEvent]:
        return [event for event in self.events if event.type == event_type]
