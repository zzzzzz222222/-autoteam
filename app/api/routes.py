"""API routes — thin HTTP/SSE adapters over the existing AutoTeam Core.

Every payload is derived from real Core objects (ExecutionPlan / ExecutionTrace /
AgentArtifact / FinalArtifact). No mock data, no re-implemented orchestration.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.models import (
    ArtifactsResponse,
    FinalResultResponse,
    TaskCreatedResponse,
    TaskCreateRequest,
    TaskSnapshot,
    TeamResponse,
)
from app.api.runs import RunRegistry

router = APIRouter(prefix="/api", tags=["autoteam"])
registry = RunRegistry()

VERSION = "0.5.0"


def _serialize_event(event: dict[str, Any]) -> str:
    """One SSE ``data:`` frame. We keep the event *type* inside the JSON payload
    (``event.type``) instead of the SSE ``event:`` name so browser
    ``EventSource.onmessage`` receives every frame without per-type listeners."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _handle_or_404(task_id: str):
    handle = registry.get(task_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"unknown task '{task_id}'")
    return handle


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


@router.get("/tasks", response_model=list[TaskSnapshot])
def list_tasks() -> list[dict[str, Any]]:
    return registry.list()


@router.post("/tasks", response_model=TaskCreatedResponse, status_code=201)
def create_task(payload: TaskCreateRequest) -> TaskCreatedResponse:
    """Create the run handle now; execution starts immediately in the background,
    exactly like the existing Live View's thread. Returns the real run id."""
    handle = registry.create(payload.task, payload.mode)
    registry.start(handle)
    return TaskCreatedResponse(task_id=handle.task_id, status="created")


@router.get("/tasks/{task_id}", response_model=TaskSnapshot)
def get_task(task_id: str) -> dict[str, Any]:
    return _handle_or_404(task_id).snapshot()


@router.get("/tasks/{task_id}/team", response_model=TeamResponse)
def get_team(task_id: str) -> TeamResponse:
    handle = _handle_or_404(task_id)
    snapshot = handle.snapshot()
    session = handle.session
    plan = getattr(session, "plan", None) if session is not None else None
    explanation = None
    if plan is not None and getattr(plan, "explanation", None) is not None:
        explanation = plan.explanation.model_dump()
    agents = []
    if plan is not None:
        layer_of: dict[str, int] = {}
        for index, layer in enumerate(snapshot["layers"]):
            for agent_id in layer:
                layer_of[agent_id] = index
        for agent in plan.agents:
            agent_id = agent.id or ""
            result = snapshot["agent_results"].get(agent_id, {})
            agents.append(
                {
                    "id": agent_id,
                    "name": agent.role.name,
                    "role": str(getattr(agent.role, "goal", "")),
                    "capabilities": [c.value for c in agent.role.capabilities],
                    "tools": list(getattr(agent, "tools", []) or []),
                    "layer": layer_of.get(agent_id, 0),
                    "status": result.get("status", "pending"),
                    "attempt": result.get("attempt", 1),
                }
            )
    return TeamResponse(
        task=handle.task,
        agents=agents,
        edges=snapshot["edges"],
        layers=snapshot["layers"],
        explanation=explanation,
    )


@router.get("/tasks/{task_id}/artifacts", response_model=ArtifactsResponse)
def get_artifacts(task_id: str) -> ArtifactsResponse:
    handle = _handle_or_404(task_id)
    session = handle.session
    if session is None:
        return ArtifactsResponse(task_id=task_id, artifacts=[])
    names = session.agent_names()
    artifacts = []
    for artifact in session.artifacts:
        artifacts.append(
            {
                "artifact_id": artifact.artifact_id,
                "agent_id": artifact.agent_id,
                "agent_name": names.get(artifact.agent_id, artifact.agent_id),
                "output_type": artifact.output_type.value,
                "title": artifact.title,
                "content": artifact.content,
                "structured_data": dict(artifact.structured_data),
                "sources": list(artifact.sources),
                "source_records": [r.model_dump() for r in artifact.source_records],
                "evidence": [e.model_dump() for e in artifact.evidence],
                "dependencies": list(artifact.dependencies),
                "created_at": artifact.created_at,
                "metadata": dict(artifact.metadata),
            }
        )
    return ArtifactsResponse(task_id=task_id, artifacts=artifacts)


@router.get("/tasks/{task_id}/result", response_model=FinalResultResponse)
def get_result(task_id: str) -> FinalResultResponse:
    handle = _handle_or_404(task_id)
    snapshot = handle.snapshot()
    final = snapshot.get("final_artifact")
    if final is None:
        if handle.done:
            raise HTTPException(status_code=404, detail="run finished without a final artifact")
        return FinalResultResponse(task_id=task_id, status="running")
    return FinalResultResponse(
        task_id=task_id,
        status=final["status"],
        title=final["title"],
        markdown=final["markdown"],
        sources=final["sources"],
        evidence=final["evidence"],
        sections=final["sections"],
        insights=final.get("insights") or [],
        contradictions=final.get("contradictions") or [],
        uncertainties=final.get("uncertainties") or [],
        tradeoffs=final.get("tradeoffs") or [],
        recommendations=final.get("recommendations") or [],
        synthesis_status=final.get("synthesis_status") or "",
    )


@router.get("/tasks/{task_id}/events")
def get_events_history(task_id: str) -> dict[str, Any]:
    """Non-streaming history of all events emitted so far (for non-SSE clients)."""
    handle = _handle_or_404(task_id)
    return {
        "task_id": task_id,
        "events": handle.events(0),
        "event_count": handle.event_count(),
        "done": handle.done,
    }


@router.get("/tasks/{task_id}/stream")
async def stream_events(task_id: str):
    """Server-Sent Events: replays the run's real ExecutionEvents incrementally."""
    handle = _handle_or_404(task_id)

    async def generate():
        await asyncio.sleep(0.1)  # let the background thread start
        last = 0
        while True:
            events = handle.events(last)
            for event in events:
                yield _serialize_event(event)
            last = handle.event_count()
            if handle.done and last >= handle.event_count():
                # final heartbeat then close
                yield f"event: done\ndata: {json.dumps({'task_id': task_id, 'done': True})}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )