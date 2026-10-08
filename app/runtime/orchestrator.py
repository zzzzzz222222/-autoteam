"""End-to-end research pipeline (v0.2.0).

Composes the planner (``TaskDecomposer``), the existing engine
(``AsyncDAGScheduler`` + ``AgentRuntime``), and the aggregator (``build_report``)
into one callable. The scheduler is reused *verbatim* — only the executor and the
aggregation are new, so retry / replan / evaluation from v0.1.0 apply unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.llm.provider import LLMProvider, get_llm_provider
from app.models.agent import AgentSpec
from app.models.task import Task
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.decomposer import TaskDecomposer, build_team, build_topology
from app.runtime.models import (
    CompetitorFindings,
    ResearchFindings,
    ResearchReport,
    TechnologyFindings,
)
from app.runtime.result_store import ResultStore
from app.scheduler.models import AgentResult, ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.tools.registry import ToolRegistry


class ResearchOrchestrator:
    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        tool_mode: str = "auto",
        store: ResultStore | None = None,
        fail_agent_ids: set[str] | None = None,
        failures_before_success: dict[str, int] | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        # AT-AUDIT-001: accepted here and handed to the scheduler in ``run`` so
        # the configured cap governs this pipeline too instead of being dropped.
        self.max_concurrency = max_concurrency
        self.provider = provider or get_llm_provider()
        self.tool_registry = ToolRegistry(mode=tool_mode)
        self.store = store or ResultStore()
        # AT-AUDIT-002: keep the constructor arguments so every run can get its
        # own runtime carrying that run's id. Mutating a single shared runtime's
        # ``run_id`` would be global mutable state, which interleaved runs could
        # overwrite and which is exactly the class of bug being fixed here.
        self._runtime_kwargs: dict[str, object] = {
            "provider": self.provider,
            "tool_registry": self.tool_registry,
            "store": self.store,
            "fail_agent_ids": fail_agent_ids,
            "failures_before_success": failures_before_success,
        }
        self.runtime = AgentRuntime(**self._runtime_kwargs)

    def _runtime_for(self, run_id: str) -> AgentRuntime:
        """A runtime bound to one specific run (same config, tagged run id)."""
        kwargs = dict(self._runtime_kwargs)
        kwargs["run_id"] = run_id
        return AgentRuntime(**kwargs)

    async def run(self, task_description: str, task_context: str | None = None) -> ResearchReport:
        # AT-AUDIT-002: this execution owns a fresh run id, so its events and
        # results can never be read back as part of a previous run's state.
        run_id = self.store.start_run(f"run_{uuid.uuid4().hex[:8]}")
        runtime = self._runtime_for(run_id)
        task = Task(description=task_description, context=task_context)
        plan = TaskDecomposer(self.provider).decompose(task)
        agents = build_team(plan)
        topology = build_topology(agents, plan)
        self.store.set_structure(plan, agents, topology)

        scheduler = AsyncDAGScheduler(
            executor=runtime,
            max_concurrency=self.max_concurrency,
            retry_policy=RetryPolicy(max_retries=1),
        )
        results = await scheduler.run(task, topology, agents)
        self.store.set_results(results, run_id=run_id)
        report = build_report(task, plan, agents, results)
        self.store.set_report(report)
        return report


def _output_of(results: dict[str, AgentResult], agent_id: str) -> BaseModel | None:
    result = results.get(agent_id)
    if result is not None and result.status is ExecutionStatus.SUCCESS and isinstance(
        result.output, BaseModel
    ):
        return result.output
    return None


def _synthesize_summary(
    market: Any, competitor: Any, technology: Any, draft: Any
) -> str:
    if draft is not None and getattr(draft, "summary", ""):
        return draft.summary
    parts: list[str] = []
    if market is not None and getattr(market, "summary", ""):
        parts.append(f"市场概览：{market.summary}")
    if competitor is not None and getattr(competitor, "summary", ""):
        parts.append(f"竞争格局：{competitor.summary}")
    if technology is not None and getattr(technology, "summary", ""):
        parts.append(f"技术趋势：{technology.summary}")
    if parts:
        return " ".join(parts)
    return "研究报告已生成，但部分分析模块未返回结构化结果。"


def build_report(
    task: Task,
    plan: Any,
    agents: list[AgentSpec],
    results: dict[str, AgentResult],
) -> ResearchReport:
    """Code-level aggregation: map each agent's output onto the report sections."""
    market = competitor = technology = draft = None
    for subtask, agent in zip(plan.subtasks, agents):
        output = _output_of(results, agent.id)
        if output is None:
            continue
        key = (subtask.target_role or "").lower()
        if "competitor" in key:
            competitor = output
        elif "technolog" in key or "tech" in key:
            technology = output
        elif "report" in key or "writer" in key or "synthes" in key:
            draft = output
        else:
            market = output

    sources: list[str] = []
    for output in (market, competitor, technology, draft):
        if output is None:
            continue
        collected = getattr(output, "sources", None)
        if isinstance(collected, list):
            sources.extend(str(item) for item in collected)

    return ResearchReport(
        task=task.description,
        summary=_synthesize_summary(market, competitor, technology, draft),
        market_overview=market if isinstance(market, ResearchFindings) else None,
        competitors=competitor if isinstance(competitor, CompetitorFindings) else None,
        technology=technology if isinstance(technology, TechnologyFindings) else None,
        sources=sources,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
