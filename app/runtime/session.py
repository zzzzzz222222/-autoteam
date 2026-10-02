"""Task Execution Session (v0.4.0).

One session = one attempt at completing a user task end-to-end:
dynamic team → existing scheduler/retry/replan → artifacts → final deliverable
→ deterministic completion verdict. Purely an in-memory object; persistence
can be added later without changing this contract.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from pathlib import Path

from app.llm.provider import LLMProvider, MockLLMProvider
from app.models.task import Task
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.artifacts import AgentArtifact, AgentDeliverable
from app.runtime.assembler import ArtifactAssembler, FinalArtifact
from app.runtime.dynamic_models import ExecutionPlan
from app.runtime.dynamic_team import build_dynamic_team
from app.runtime.events import ExecutionTrace
from app.runtime.result_store import ResultStore
from app.runtime.validation import ArtifactValidationError, validate_artifact
from app.scheduler.models import ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.tools.registry import ToolRegistry


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


class CompletionCriteria:
    """Transparent, code-evaluated completion rules — no LLM judge, no scores."""

    def __init__(
        self,
        required_artifact_types: list[str] | None = None,
        minimum_successful_agents: int = 1,
        allow_partial: bool = True,
    ) -> None:
        self.required_artifact_types = list(required_artifact_types or [])
        self.minimum_successful_agents = minimum_successful_agents
        self.allow_partial = allow_partial

    def evaluate(
        self,
        successful_agents: int,
        total_agents: int,
        produced_artifact_types: set[str],
    ) -> SessionStatus:
        if total_agents == 0 or successful_agents == 0:
            return SessionStatus.FAILED
        missing = [
            artifact_type
            for artifact_type in self.required_artifact_types
            if artifact_type not in produced_artifact_types
        ]
        if successful_agents == total_agents and not missing:
            return SessionStatus.SUCCESS
        if self.allow_partial and successful_agents >= self.minimum_successful_agents:
            return SessionStatus.PARTIAL_SUCCESS
        return SessionStatus.FAILED


class TaskExecutionSession:
    def __init__(self, task: str, criteria: CompletionCriteria | None = None) -> None:
        self.run_id = f"run_{uuid.uuid4().hex[:8]}"
        self.task = task
        self.status: SessionStatus = SessionStatus.PENDING
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.plan: ExecutionPlan | None = None
        self.agent_results: dict = {}
        self.artifacts: list[AgentArtifact] = []
        self.final_artifact: FinalArtifact | None = None
        self.synthesis_bundle: object | None = None  # ReportBundle | None (v0.6)
        self.criteria = criteria or CompletionCriteria()
        self.trace = ExecutionTrace(self.run_id)
        self.error: str | None = None
        self.provider_name: str = "MockLLMProvider"

    def agent_names(self) -> dict[str, str]:
        if self.plan is None:
            return {}
        return {agent.id: agent.role.name for agent in self.plan.agents}

    def agent_order(self) -> list[str]:
        if self.plan is None:
            return []
        return [agent_id for layer in self.plan.execution_layers for agent_id in layer]

    def save_markdown(self, directory: str | Path) -> Path:
        if self.final_artifact is None:
            raise RuntimeError("No final artifact to save yet.")
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{self.run_id}.md"
        path.write_text(self.final_artifact.to_markdown(), encoding="utf-8")
        return path


def execute_task(
    task: str,
    *,
    provider: LLMProvider | None = None,
    tool_mode: str = "auto",
    criteria: CompletionCriteria | None = None,
    fail_agent_ids: set[str] | None = None,
    failures_before_success: dict[str, int] | None = None,
    timeout: float | None = None,
    max_tool_calls: int = 3,
    max_iterations: int = 5,
    provider_fallback: bool = False,
) -> TaskExecutionSession:
    """Run one full task session offline-first through the existing engine.

    Offline runs must stay offline: when the provider is the deterministic mock
    (or unset), tools are forced to ``mock`` so a stray real search key in the
    environment can never turn an "Offline" run into a live one.
    """
    session = TaskExecutionSession(task, criteria)
    session.status = SessionStatus.RUNNING
    session.started_at = time.time()
    session.provider_name = type(provider).__name__ if provider is not None else "MockLLMProvider"
    if provider is None or isinstance(provider, MockLLMProvider):
        tool_mode = "mock"
    trace = session.trace
    trace.record("TASK_STARTED", message=task[:200])

    try:
        plan = build_dynamic_team(task, provider=provider)
        session.plan = plan
        trace.record(
            "TEAM_FORMED",
            message=f"{len(plan.agents)} agents, {len(plan.execution_layers)} layers",
            layers=[list(layer) for layer in plan.execution_layers],
        )
        for layer_index, layer in enumerate(plan.execution_layers):
            for agent_id in layer:
                trace.record(
                    "AGENT_READY",
                    agent_id=agent_id,
                    message=f"ready in layer {layer_index + 1}",
                )

        # v0.4.0 upgrade: dynamic agents produce dependency-aware artifacts.
        for agent in plan.agents:
            agent.output_schema = AgentDeliverable

        runtime = AgentRuntime(
            provider=provider or MockLLMProvider(),
            tool_registry=ToolRegistry(mode=tool_mode),
            store=ResultStore(),
            fail_agent_ids=fail_agent_ids,
            failures_before_success=failures_before_success,
            trace=trace,
            run_id=session.run_id,
            max_tool_calls=max_tool_calls,
            max_iterations=max_iterations,
        )
        scheduler = AsyncDAGScheduler(
            executor=runtime, retry_policy=RetryPolicy(max_retries=2), timeout=timeout
        )
        results = asyncio.run(
            scheduler.run(Task(description=task), plan.topology, plan.agents)
        )
        session.agent_results = results

        for agent_id, result in results.items():
            if len(result.attempts) > 1:
                trace.record(
                    "AGENT_RETRY",
                    agent_id=agent_id,
                    message=f"succeeded on attempt {result.attempt}",
                    attempts=len(result.attempts),
                )
        for event in scheduler.replan_events:
            trace.record(
                "AGENT_REPLANNED",
                agent_id=event.failed_agent_id,
                message=event.reason,
            )

        session.artifacts = [
            result.output
            for result in results.values()
            if result.status is ExecutionStatus.SUCCESS
            and isinstance(result.output, AgentArtifact)
        ]
        # Defensive re-validation: nothing rejected reaches the report.
        valid_artifacts: list[AgentArtifact] = []
        for artifact in session.artifacts:
            try:
                validate_artifact(artifact)
                valid_artifacts.append(artifact)
            except ArtifactValidationError as exc:
                trace.record(
                    "ARTIFACT_REJECTED",
                    agent_id=artifact.agent_id,
                    message=str(exc)[:200],
                )
        session.artifacts = valid_artifacts
        # v0.6.0: evidence filtering + cross-agent synthesis before assembly.
        # A synthesis failure never fails the task — fall back to the legacy
        # concatenation assembler and record SYNTHESIS_FAILED.
        try:
            from app.synthesis.assembler import assemble_from_bundle
            from app.synthesis.pipeline import run_synthesis_pipeline

            bundle = run_synthesis_pipeline(
                task, session.artifacts, provider=provider, trace=trace
            )
            session.synthesis_bundle = bundle
            session.final_artifact = assemble_from_bundle(
                task=task,
                artifacts=session.artifacts,
                bundle=bundle,
                agent_order=session.agent_order(),
                run_id=session.run_id,
                source_type="offline_mock" if provider is None else "llm",
            )
        except Exception as synth_exc:  # noqa: BLE001 — degrade, never fail the run
            trace.record(
                "SYNTHESIS_FAILED",
                message="Synthesis could not produce a valid structured result",
                reason=str(synth_exc)[:300],
            )
            session.synthesis_bundle = None
            session.final_artifact = ArtifactAssembler().assemble(
                task=task,
                artifacts=session.artifacts,
                agent_order=session.agent_order(),
                run_id=session.run_id,
                source_type="offline_mock" if provider is None else "llm",
            )
            session.final_artifact.metadata["synthesis_status"] = "failed"
            session.final_artifact.metadata["synthesis_degradation_reason"] = str(
                synth_exc
            )[:300]
        produced = {artifact.output_type.value for artifact in session.artifacts}
        successful = sum(
            1 for result in results.values() if result.status is ExecutionStatus.SUCCESS
        )
        session.status = session.criteria.evaluate(
            successful, len(results), produced
        )
        if session.final_artifact is not None:
            session.final_artifact.metadata["status"] = session.status.value
    except Exception as exc:
        session.error = str(exc)
        session.status = SessionStatus.FAILED

    # Real-mode resilience: a failing provider (bad key, network) must not crash
    # the run. The upper layer decides to fall back to the deterministic mock.
    provider_failed = any(
        "LLM provider call failed" in (result.error or "")
        for result in session.agent_results.values()
    )
    if (
        provider_fallback
        and provider is not None
        and (provider_failed or session.status is SessionStatus.FAILED)
        and not isinstance(provider, MockLLMProvider)
    ):
        fallback = execute_task(
            task,
            provider=None,
            tool_mode=tool_mode,
            criteria=criteria,
            fail_agent_ids=fail_agent_ids,
            failures_before_success=failures_before_success,
            timeout=timeout,
            max_tool_calls=max_tool_calls,
            max_iterations=max_iterations,
            provider_fallback=False,
        )
        fallback.trace.record(
            "PROVIDER_FALLBACK",
            message="real provider failed; rerunning with the deterministic mock",
        )
        fallback.final_artifact.metadata["provider_fallback"] = True
        return fallback

    trace.record("TASK_COMPLETED", message=session.status.value)
    session.finished_at = time.time()
    return session
