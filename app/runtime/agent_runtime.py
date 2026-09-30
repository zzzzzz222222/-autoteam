"""Real agent runtime for the v0.2.0 research demo.

``AgentRuntime`` implements the existing ``AgentExecutor`` Protocol, so it drops
into ``AsyncDAGScheduler`` unchanged and automatically inherits retry / replan.

Each agent:
  1. resolves a role-specific behavior (output model + tools + prompt builder),
  2. reads its upstream siblings via ``ExecutionContext.get_upstream_results``,
  3. enriches the prompt with tool results,
  4. calls the configured LLM provider for a schema-validated object,
  5. returns that object — it becomes ``AgentResult.output`` and is shared with
     downstream agents and the final report.

This is the "LLM proposes, Schema constrains, Code validates, Executor executes"
half that lives at execution time (the schema layer is ``app.runtime.models``).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import BaseModel

from app.llm.provider import LLMProvider, MockLLMProvider, ProviderError  # noqa: F401
from app.models.agent import AgentSpec
from app.models.task import Task
from app.runtime.artifacts import (
    AgentArtifact,
    AgentDecision,
    AgentDeliverable,
    Evidence,
    Source,
    artifact_type_for,
    now_iso,
)
from app.runtime.context import assemble_agent_context
from app.runtime.events import ExecutionTrace
from app.runtime.models import (
    CompetitorFindings,
    ReportDraft,
    ResearchFindings,
    TechnologyFindings,
)
from app.runtime.result_store import ResultStore, RunEvent
from app.runtime.validation import validate_artifact
from app.scheduler.models import ExecutionContext
from app.tools.registry import ToolError, ToolRegistry, ToolResult


def _market_prompt(task: Task, role: str, upstream: str, tools: str) -> str:
    return (
        f"You are the {role}. Survey the overall market for the task below, "
        f"identify key trends, and collect sources.\n\n"
        f"TASK: {task.description}\nCONTEXT: {task.context or ''}\n"
        f"{upstream}{tools}"
        f"Return JSON matching ResearchFindings."
    )


def _competitor_prompt(task: Task, role: str, upstream: str, tools: str) -> str:
    return (
        f"You are the {role}. Analyze the main vendors, their product direction, "
        f"and relative positioning for the task below.\n\n"
        f"TASK: {task.description}\nCONTEXT: {task.context or ''}\n"
        f"{upstream}{tools}"
        f"Return JSON matching CompetitorFindings."
    )


def _technology_prompt(task: Task, role: str, upstream: str, tools: str) -> str:
    return (
        f"You are the {role}. Summarize the current technology routes and emerging "
        f"trends relevant to the task below.\n\n"
        f"TASK: {task.description}\nCONTEXT: {task.context or ''}\n"
        f"{upstream}{tools}"
        f"Return JSON matching TechnologyFindings."
    )


def _report_prompt(task: Task, role: str, upstream: str, tools: str) -> str:
    return (
        f"You are the {role}. Synthesize the upstream research findings into a "
        f"concise executive report with highlights and sources.\n\n"
        f"TASK: {task.description}\n"
        f"{upstream}{tools}"
        f"Return JSON matching ReportDraft."
    )


class ResearchBehavior:
    def __init__(
        self,
        *,
        keywords: tuple[str, ...],
        output_model: type[BaseModel],
        tools: list[str],
        prompt_builder: Callable[[Task, str, str, str], str],
    ) -> None:
        self.keywords = keywords
        self.output_model = output_model
        self.tools = tools
        self.prompt_builder = prompt_builder


# Order matters: specific roles first, generic "research" falls through last.
_BEHAVIORS = [
    ResearchBehavior(
        keywords=("competitor", "竞争", "竞品"),
        output_model=CompetitorFindings,
        tools=["web_search"],
        prompt_builder=_competitor_prompt,
    ),
    ResearchBehavior(
        keywords=("technolog", "tech", "技术"),
        output_model=TechnologyFindings,
        tools=["web_search"],
        prompt_builder=_technology_prompt,
    ),
    ResearchBehavior(
        keywords=("report", "writer", "报告", "synthes", "总结"),
        output_model=ReportDraft,
        tools=[],
        prompt_builder=_report_prompt,
    ),
    ResearchBehavior(
        keywords=("research", "market", "研究", "市场"),
        output_model=ResearchFindings,
        tools=["web_search"],
        prompt_builder=_market_prompt,
    ),
]


def _model_to_text(model: BaseModel) -> str:
    lines: list[str] = []
    for key, value in model.model_dump().items():
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                rendered = "; ".join(
                    ", ".join(f"{k}={v}" for k, v in item.items()) for item in value
                )
            else:
                rendered = ", ".join(str(item) for item in value)
            lines.append(f"{key}: {rendered}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


class AgentRuntime:
    """Drop-in ``AgentExecutor`` driven by an LLM provider and a tool registry."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        store: ResultStore | None = None,
        fail_agent_ids: set[str] | None = None,
        raise_agent_ids: set[str] | None = None,
        failures_before_success: dict[str, int] | None = None,
        trace: ExecutionTrace | None = None,
        run_id: str = "",
        max_tool_calls: int = 3,
        max_iterations: int = 5,
    ) -> None:
        self.provider = provider or MockLLMProvider()
        self.tool_registry = tool_registry or ToolRegistry(mode="auto")
        self.store = store or ResultStore()
        self.fail_agent_ids = set(fail_agent_ids or [])
        self.raise_agent_ids = set(raise_agent_ids or [])
        self.failures_before_success = dict(failures_before_success or {})
        self.trace = trace
        self.run_id = run_id
        self.max_tool_calls = max_tool_calls
        self.max_iterations = max_iterations
        self.call_counts: dict[str, int] = {}

    @staticmethod
    def _resolve_behavior(role_name: str) -> ResearchBehavior:
        name = (role_name or "").lower()
        for behavior in _BEHAVIORS:
            if any(keyword in name for keyword in behavior.keywords):
                return behavior
        return _BEHAVIORS[-1]

    def _format_upstream(self, upstream: dict[str, Any]) -> str:
        if not upstream:
            return ""
        parts: list[str] = []
        for source_id, result in upstream.items():
            output = result.output
            if isinstance(output, BaseModel):
                parts.append(f"[{source_id} findings]\n{_model_to_text(output)}")
            elif output is not None:
                parts.append(f"[{source_id}] {output}")
        return ("\n\nUpstream inputs:\n" + "\n\n".join(parts) + "\n\n") if parts else ""

    def _invoke_tools(
        self, tool_names: list[str], task: Task, agent_id: str = ""
    ) -> list[ToolResult]:
        """Run tools and return structured results (never raises)."""
        results: list[ToolResult] = []
        for tool_name in tool_names:
            try:
                result = self.tool_registry.run(tool_name, task.description)
            except Exception as exc:  # defensive: run() already catches, but stay safe
                result = ToolResult(query=task.description, offline=True, error=str(exc))
            results.append(result)
            label = "offline mock" if result.offline else "web"
            if self.trace is not None:
                self.trace.record(
                    "TOOL_CALLED",
                    agent_id=agent_id,
                    message=f"{tool_name} ({label})",
                    tool=tool_name,
                    offline=result.offline,
                    error=result.error or "",
                )
        return results

    def _format_tool_blocks(self, results: list[ToolResult]) -> str:
        blocks: list[str] = []
        for result in results:
            tool_name = result.tool or "tool"
            label = "offline mock" if result.offline else "web"
            items = "\n".join(f"- {item}" for item in result.results) or "- (no results)"
            error = f"\n- error: {result.error}" if result.error else ""
            blocks.append(f"[{tool_name} ({label})]\n{items}{error}")
        return ("\n\nTool results:\n" + "\n\n".join(blocks) + "\n\n") if blocks else ""

    def _run_tools(self, tool_names: list[str], task: Task, agent_id: str = "") -> str:
        return self._format_tool_blocks(self._invoke_tools(tool_names, task, agent_id))

    def _collect_evidence(
        self,
        collected: list[ToolResult],
        deliverable: AgentDeliverable,
        *,
        agent_id: str = "",
        artifact_id: str = "",
    ) -> tuple[list[Source], list[Evidence]]:
        """Deterministic provenance: sources come only from real tool results;
        each key point is linked to a retrieved snippet. Nothing is invented —
        offline tool results are marked ``offline_mock`` with empty URLs.

        v0.6: every evidence item carries ``producer_agent`` / ``artifact_id``
        so the synthesis layer can trace claims end-to-end.
        """
        sources: list[Source] = []
        snippets: list[str] = []
        for result in collected:
            for item in result.search_results:
                sources.append(
                    Source(
                        id=f"source_{len(sources) + 1:03d}",
                        title=item.title,
                        url=item.url,
                        source_type="offline_mock" if result.offline else item.source,
                        retrieved_at=now_iso(),
                    )
                )
                snippets.append(item.snippet)
        evidence: list[Evidence] = []
        if sources:
            for index, point in enumerate(deliverable.key_points):
                source = sources[index % len(sources)]
                evidence.append(
                    Evidence(
                        claim=point[:200],
                        evidence=snippets[index % len(snippets)],
                        source_id=source.id,
                        producer_agent=agent_id,
                        artifact_id=artifact_id,
                    )
                )
        return sources, evidence

    def _real_execution(
        self, agent: AgentSpec, agent_context, task: Task
    ) -> tuple[AgentDeliverable, list[Source], list[Evidence], list[str]]:
        """Real-LLM tool-calling loop: the LLM decides between calling a
        registered tool (schema: ToolCall) and finishing with a deliverable.
        Bounded by max_tool_calls / max_iterations; tool failures become
        structured ToolResults fed back into the prompt — never crashes."""
        agent_id = agent.id or "unknown"
        collected: list[ToolResult] = []
        used_tools: list[str] = []
        base_prompt = self._artifact_prompt(agent_context, task, "")
        available = ", ".join(self.tool_registry.available())
        deliverable: AgentDeliverable | None = None
        for _ in range(self.max_iterations):
            decision_prompt = (
                base_prompt
                + self._format_decision_results(collected)
                + f"\nAvailable tools: {available}\n"
                "Decide the next step. Return JSON matching AgentDecision: "
                "either action='call_tool' with tool_call{tool_name, arguments} "
                "(arguments must include the required keys for that tool), "
                "or action='finish' with deliverable{title, summary, key_points, "
                "structured_data, sources}. Cite only tool-provided information."
            )
            decision = self.provider.structured_completion(decision_prompt, AgentDecision)
            if decision.action == "call_tool" and decision.tool_call is not None:
                if len(collected) >= self.max_tool_calls:
                    break  # tool budget exhausted — synthesize partial below
                tool_name = decision.tool_call.tool_name
                try:
                    self.tool_registry.validate(tool_name)
                    result = self.tool_registry.execute(
                        tool_name, dict(decision.tool_call.arguments)
                    )
                except ToolError as exc:
                    result = ToolResult(query=tool_name, offline=True, error=str(exc))
                collected.append(result)
                used_tools.append(tool_name)
                if self.trace is not None:
                    self.trace.record(
                        "TOOL_CALLED",
                        agent_id=agent_id,
                        message=f"{tool_name} via tool-call",
                        tool=tool_name,
                        error=result.error or "",
                    )
                continue
            deliverable = decision.deliverable or AgentDeliverable(
                summary="[real mode] decision without deliverable"
            )
            break
        if deliverable is None:  # budget/iteration limit reached
            deliverable = AgentDeliverable(
                title=f"{agent.role.name} — partial deliverable",
                summary="[real mode] tool/iteration budget reached; partial results only.",
                key_points=[
                    item for result in collected for item in result.results
                ][:3],
            )
        sources, evidence = self._collect_evidence(
            collected,
            deliverable,
            agent_id=agent_id,
            artifact_id=f"artifact_{agent_id}",
        )
        return deliverable, sources, evidence, used_tools

    @staticmethod
    def _format_decision_results(collected: list[ToolResult]) -> str:
        if not collected:
            return "\nTool results so far: (none)\n"
        lines = []
        for result in collected:
            status = f"error: {result.error}" if result.error else "; ".join(result.results)
            lines.append(f"- {status}")
        return "\nTool results so far:\n" + "\n".join(lines) + "\n"

    def _dynamic_prompt(self, agent: AgentSpec, task: Task, upstream: str, tools: str) -> str:
        system_prompt = getattr(agent, "system_prompt", "") or f"You are {agent.role.name}."
        return (
            f"{system_prompt}\n\n"
            f"TASK: {task.description}\nCONTEXT: {task.context or ''}\n"
            f"{upstream}{tools}"
            f"Return JSON matching TaskDeliverable."
        )

    def _artifact_prompt(self, agent_context, task: Task, tools: str) -> str:
        system_prompt = (
            f"You are the {agent_context.role_name}, responsible for "
            f"{agent_context.expected_output or 'your assigned subtask'}."
        )
        expected_line = ", ".join(agent_context.expected_outputs) or agent_context.expected_output
        upstream_lines = [
            f"- [{artifact.artifact_id}] {artifact.title} ({artifact.output_type.value}): "
            + "; ".join(f"{k}={v}" for k, v in artifact.structured_data.items())
            for artifact in agent_context.upstream_artifacts
        ]
        upstream_block = (
            "UPSTREAM ARTIFACTS:\n" + "\n".join(upstream_lines)
            if upstream_lines
            else "UPSTREAM ARTIFACTS:\n- (none — you are an entry agent)"
        )
        return (
            f"{system_prompt}\n\n"
            f"ROLE: {agent_context.role_name}\n"
            f"EXPECTED_OUTPUT: {expected_line}\n"
            f"TASK: {task.description}\n"
            f"SUBTASK: {', '.join(agent_context.subtask_titles) or 'assigned work'}\n\n"
            f"{upstream_block}\n"
            f"{tools}"
            f"Return JSON matching AgentDeliverable."
        )

    def _build_artifact(
        self,
        agent: AgentSpec,
        agent_context,
        deliverable: AgentDeliverable,
        task: Task,
        source_records: list[Source] | None = None,
        evidence: list[Evidence] | None = None,
        tools_used: list[str] | None = None,
    ) -> AgentArtifact:
        agent_id = agent.id or "unknown"
        artifact = AgentArtifact(
            artifact_id=f"artifact_{agent_id}",
            agent_id=agent_id,
            task_id=self.run_id,
            output_type=artifact_type_for(agent_context.expected_output),
            title=deliverable.title or f"{agent.role.name} deliverable",
            content=(
                f"**{deliverable.summary}**\n\n"
                + "\n".join(f"- {point}" for point in deliverable.key_points)
            ),
            structured_data=dict(deliverable.structured_data),
            sources=list(deliverable.sources),
            source_records=list(source_records or []),
            evidence=list(evidence or []),
            dependencies=list(agent_context.upstream_artifact_ids),
            created_at=now_iso(),
            metadata={
                "source_type": "offline_mock"
                if isinstance(self.provider, MockLLMProvider)
                else "llm",
                "role_name": agent.role.name,
                "output_type_declared": agent_context.output_type,
                "tools_used": list(tools_used or []),
            },
        )
        # v0.5.0: nothing invalid reaches downstream agents or the report.
        validate_artifact(artifact)
        if self.trace is not None:
            self.trace.record(
                "AGENT_OUTPUT",
                agent_id=agent_id,
                message=f"{agent.role.name} produced {artifact.artifact_id}",
            )
            self.trace.record(
                "ARTIFACT_CREATED",
                agent_id=agent_id,
                message=f"{artifact.artifact_id} ({artifact.output_type.value})",
                artifact_id=artifact.artifact_id,
                output_type=artifact.output_type.value,
            )
        return artifact

    async def execute(self, agent: AgentSpec, context: ExecutionContext) -> Any:
        agent_id = agent.id or "unknown"
        self.call_counts[agent_id] = self.call_counts.get(agent_id, 0) + 1
        role_name = agent.role.name
        behavior = self._resolve_behavior(role_name)
        # v0.3.0: dynamic agents carry their own output schema; v0.4.0: agents
        # upgraded to AgentDeliverable produce dependency-aware artifacts.
        # Everything else keeps the v0.2.0 behavior mapping.
        dynamic_model = getattr(agent, "output_schema", None)
        use_artifacts = dynamic_model is AgentDeliverable
        use_dynamic = isinstance(dynamic_model, type) and issubclass(
            dynamic_model, BaseModel
        ) and not use_artifacts
        if self.trace is not None:
            self.trace.record(
                "AGENT_STARTED",
                agent_id=agent_id,
                message=f"{role_name} started",
            )
        self.store.record(
            RunEvent(
                agent_id=agent_id,
                event="start",
                timestamp=time.time(),
                message=f"{role_name} started",
            )
        )
        try:
            if agent_id in self.raise_agent_ids:
                raise RuntimeError(f"AgentRuntime forced exception for {agent_id}")
            if agent_id in self.fail_agent_ids or self.call_counts[agent_id] <= (
                self.failures_before_success.get(agent_id, 0)
            ):
                raise RuntimeError(f"AgentRuntime forced failure for {agent_id}")

            upstream = context.get_upstream_results(agent_id)
            upstream_text = self._format_upstream(upstream)
            if use_artifacts:
                agent_context = assemble_agent_context(agent, context)
                collected = self._invoke_tools(list(agent.tools), context.task, agent_id)
                tool_text = self._format_tool_blocks(collected)
                if isinstance(self.provider, MockLLMProvider):
                    # Offline mode: deterministic deliverable + stub evidence.
                    prompt = self._artifact_prompt(agent_context, context.task, tool_text)
                    deliverable = self.provider.structured_completion(prompt, AgentDeliverable)
                    sources, evidence = self._collect_evidence(
                        collected,
                        deliverable,
                        agent_id=agent_id,
                        artifact_id=f"artifact_{agent_id}",
                    )
                    tools_used = list(agent.tools)
                else:
                    # Real mode: LLM-driven tool-calling loop (bounded).
                    (
                        deliverable,
                        sources,
                        evidence,
                        tools_used,
                    ) = self._real_execution(agent, agent_context, context.task)
                output = self._build_artifact(
                    agent,
                    agent_context,
                    deliverable,
                    context.task,
                    source_records=sources,
                    evidence=evidence,
                    tools_used=tools_used,
                )
            elif use_dynamic:
                output_model = dynamic_model
                tool_text = self._run_tools(list(agent.tools), context.task, agent_id)
                prompt = self._dynamic_prompt(agent, context.task, upstream_text, tool_text)
                output = self.provider.structured_completion(prompt, output_model)
            else:
                output_model = behavior.output_model
                tool_text = self._run_tools(behavior.tools, context.task, agent_id)
                prompt = behavior.prompt_builder(context.task, role_name, upstream_text, tool_text)
                output = self.provider.structured_completion(prompt, output_model)
            self.store.record(
                RunEvent(
                    agent_id=agent_id,
                    event="done",
                    timestamp=time.time(),
                    message=f"{role_name} completed",
                )
            )
            return output
        except Exception as exc:
            friendly = _friendly_error(exc)
            self.store.record(
                RunEvent(
                    agent_id=agent_id,
                    event="error",
                    timestamp=time.time(),
                    message=friendly,
                )
            )
            if self.trace is not None:
                self.trace.record(
                    "AGENT_FAILED",
                    agent_id=agent_id,
                    message=friendly,
                    error_type=type(exc).__name__,
                )
            raise


def _friendly_error(exc: Exception) -> str:
    """User-facing failure reason. Full exception stays in logs / raise chain."""
    name = type(exc).__name__
    text = str(exc)
    if name in {"JSONDecodeError", "ValidationError", "SynthesisError"} or any(
        marker in text
        for marker in (
            "JSONDecodeError",
            "Expecting value",
            "Invalid structured response",
            "structured_completion",
            "model_validate",
        )
    ):
        return "Agent execution failed: invalid structured response"
    if "LLM provider call failed" in text:
        return "Agent execution failed: provider unavailable"
    return f"Agent execution failed: {name}"
