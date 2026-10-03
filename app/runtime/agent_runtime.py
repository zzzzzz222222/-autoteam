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

import re
import time
from typing import Any, Callable

from pydantic import BaseModel

from app.llm.provider import LLMProvider, MockLLMProvider, ProviderError  # noqa: F401
from app.llm.structured import CATEGORY_LENGTH_LIMIT
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
from app.runtime.claim_quality import assess_claim
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
from app.synthesis.source_identity import derive_source_identity
from app.synthesis.source_policy import SOURCE_REQUIRED_INTENTS
from app.tools.registry import (
    ToolError,
    ToolNotAllowed,
    ToolNotFound,
    ToolRegistry,
    ToolResult,
)

# --- D1: bounded adaptive recovery for confirmed `length_limit` stops ---------
#
# A ``length_limit`` stop is *deterministic*: the endpoint stopped because the
# answer reached the output ceiling, so re-sending the identical request with the
# identical ceiling reproduces the identical truncation. Only that category is
# adapted here; every other failure keeps its previous behaviour (the scheduler's
# plain retry, or immediate propagation for non-retryable errors).
#
# Each adaption is a REAL provider call, so it is bounded twice: by
# ``LENGTH_LIMIT_ADAPTIONS`` (per single structured completion) and by the run's
# own LLM budget, which ``CountingProvider`` still enforces atomically.
LENGTH_LIMIT_ADAPTIONS = 2  # extra attempts, on top of the original call
LENGTH_LIMIT_TOKEN_GROWTH = 1.5  # multiplicative growth per adaption
LENGTH_LIMIT_TOKEN_CAP = 8192  # hard ceiling; never exceeded
LENGTH_LIMIT_CONCISE_HINT = (
    "\n\nIMPORTANT: the previous reply was CUT OFF because it hit the output "
    "length limit. Return a SMALLER answer that still matches the schema: at most "
    "3 key_points, each <= 120 characters, summary <= 2 sentences, no extra "
    "commentary. Valid JSON only."
)


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
        length_limit_adaptions: int = LENGTH_LIMIT_ADAPTIONS,
        length_limit_token_cap: int = LENGTH_LIMIT_TOKEN_CAP,
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
        # D1: extra attempts allowed for a confirmed ``length_limit`` stop.
        # ``0`` disables adaption entirely (previous behaviour).
        self.length_limit_adaptions = max(0, int(length_limit_adaptions))
        self.length_limit_token_cap = max(1, int(length_limit_token_cap))
        self.call_counts: dict[str, int] = {}
        # Non-sensitive audit trail of every adaption attempt (D1).
        self.length_adaptions: list[dict[str, object]] = []

    @staticmethod
    def _resolve_behavior(role_name: str) -> ResearchBehavior:
        name = (role_name or "").lower()
        for behavior in _BEHAVIORS:
            if any(keyword in name for keyword in behavior.keywords):
                return behavior
        return _BEHAVIORS[-1]

    @staticmethod
    def _sourcing_requirement_note(agent: AgentSpec, agent_context: object) -> str:
        """D4: make a source-required intent explicit in the agent's instruction.

        Only intents listed in ``SOURCE_REQUIRED_INTENTS`` are mentioned, so an
        agent whose work does not depend on external sources is never nudged into
        a pointless search. The note states the requirement; it does not call a
        tool and does not invent one.
        """
        intent = str(getattr(agent_context, "expected_output", "") or "").strip().lower()
        if not intent:
            metadata = getattr(agent, "metadata", {}) or {}
            intent = str(metadata.get("expected_output", "") or "").strip().lower()
        requirement = SOURCE_REQUIRED_INTENTS.get(intent, "")
        if not requirement:
            return ""
        return (
            f"\nSOURCING REQUIREMENT: this deliverable ('{intent}') must be grounded "
            f"in retrieved sources ({requirement}). Use an authorised tool (for "
            "example web_search) to obtain them and cite only tool-provided "
            "information. If you cannot retrieve sources, state that limitation in "
            "the deliverable instead of asserting unsourced facts.\n"
        )

    # -- D1: bounded adaptive recovery for confirmed `length_limit` stops -----
    @staticmethod
    def _is_length_limit(exc: BaseException) -> bool:
        """True only for a *confirmed*, retryable output-length stop."""
        if not getattr(exc, "retryable", False):
            return False
        return str(getattr(exc, "parse_category", "") or "") == CATEGORY_LENGTH_LIMIT

    def _token_ceiling_host(self) -> object | None:
        """The object that actually owns ``max_tokens`` (if any).

        ``CountingProvider`` wraps the real provider, so the ceiling must be
        raised on ``inner`` for it to reach the endpoint. Offline/mock providers
        have no real output ceiling, so there is nothing to adapt.
        """
        provider = self.provider
        if isinstance(provider, MockLLMProvider) or getattr(provider, "is_mock", False):
            return None
        inner = getattr(provider, "inner", None)
        return inner if inner is not None else provider

    def _budget_allows_retry(self) -> bool:
        """Conservative pre-check so an adaption never races a spent budget.

        ``CountingProvider`` still enforces the ceiling atomically; this only
        avoids issuing a call that is certain to be refused.
        """
        summary = getattr(self.provider, "summary", None)
        if not callable(summary):
            return True
        try:
            snapshot = summary()
        except Exception:  # noqa: BLE001 - a broken counter must not block work
            return True
        if not isinstance(snapshot, dict):
            return True
        max_calls = snapshot.get("max_calls")
        if isinstance(max_calls, int) and max_calls > 0:
            spent = int(snapshot.get("count") or 0) + int(snapshot.get("blocked") or 0)
            if spent + 1 > max_calls:
                return False
        return True

    def _next_token_ceiling(self, base: int | None, step: int) -> int | None:
        """Bounded multiplicative growth, clamped by the hard cap.

        ``None`` means no ceiling is configured - the endpoint's own default is
        then unknown and inventing one would be a guess, so the caller falls back
        to the concise-output hint alone (compatible path, explicitly recorded).
        """
        if not isinstance(base, int) or base <= 0:
            return None
        grown = int(round(base * (LENGTH_LIMIT_TOKEN_GROWTH ** step)))
        return min(grown, self.length_limit_token_cap)

    def _record_length_adaption(
        self, agent_id: str, stage: str, attempt: int, ceiling: int | None, outcome: str
    ) -> None:
        """Audit trail: reason, ceiling change and result (never the content)."""
        self.length_adaptions.append(
            {
                "agent_id": agent_id,
                "stage": stage,
                "attempt": attempt,
                "max_tokens": ceiling,
                "outcome": outcome,
            }
        )
        if self.trace is not None:
            self.trace.record(
                "LENGTH_LIMIT_ADAPTED",
                agent_id=agent_id,
                message=f"{stage} attempt={attempt} max_tokens={ceiling} outcome={outcome}",
            )

    def _complete_with_length_recovery(
        self, prompt: str, response_model: type[BaseModel], *, agent_id: str, stage: str
    ) -> BaseModel:
        """``structured_completion`` + bounded ``length_limit`` adaption (D1).

        Only a *confirmed* length stop is adapted: the output ceiling is raised
        (bounded, clamped, restored afterwards) and the re-ask carries a
        concise-output instruction. Every other category - random truncation,
        invalid JSON, schema mismatch, transport/auth/budget - keeps its previous
        behaviour, so ordinary retries are untouched.
        """
        try:
            return self.provider.structured_completion(prompt, response_model)
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            if not self._is_length_limit(exc):
                raise
            last_error = exc
        host = self._token_ceiling_host()
        if host is None:
            raise last_error
        base = getattr(host, "max_tokens", None)
        for attempt in range(1, self.length_limit_adaptions + 1):
            if not self._budget_allows_retry():
                self._record_length_adaption(agent_id, stage, attempt, base, "budget_blocked")
                break
            ceiling = self._next_token_ceiling(base, attempt)
            if ceiling is not None and ceiling <= (base or 0):
                self._record_length_adaption(agent_id, stage, attempt, ceiling, "cap_reached")
                break
            try:
                if ceiling is not None:
                    setattr(host, "max_tokens", ceiling)
                outcome = "ceiling_raised" if ceiling is not None else "concise_hint_only"
                self._record_length_adaption(agent_id, stage, attempt, ceiling, outcome)
                return self.provider.structured_completion(
                    prompt + LENGTH_LIMIT_CONCISE_HINT, response_model
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._is_length_limit(exc):
                    raise
            finally:
                setattr(host, "max_tokens", base)
        raise last_error

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

    def _record_tool_event(
        self,
        *,
        agent_id: str,
        tool_name: str,
        result: ToolResult,
        attempt: int,
        arguments: dict[str, str] | None = None,
        outcome: str = "ok",
        denial_reason: str = "",
    ) -> None:
        """Structured, cross-checkable tool audit (v0.6.11).

        Records the tool name, a bounded argument summary, the execution status,
        the produced result/source counts and the agent attempt, so the tool log
        can be reconciled with the Source/Evidence layer after the run.
        """
        if self.trace is None:
            return
        self.trace.record(
            "TOOL_DENIED" if outcome == "denied" else "TOOL_CALLED",
            agent_id=agent_id,
            message=(
                f"{tool_name} denied ({denial_reason})"
                if outcome == "denied"
                else f"{tool_name} ({_tool_label(result)})"
            ),
            tool=tool_name,
            tool_kind=result.kind,
            offline=result.offline,
            error=result.error or "",
            attempt=attempt,
            outcome=outcome,
            denial_reason=denial_reason,
            arguments=_summarize_arguments(arguments or {}),
            result_count=len(result.search_results) or len(result.results),
        )

    def _invoke_tools(
        self, tool_names: list[str], task: Task, agent_id: str = ""
    ) -> list[ToolResult]:
        """Run tools and return structured results (never raises).

        Used by the offline/mock and fixed-behaviour paths, where the declared
        tool list *is* the plan. The real LLM-driven path must not pre-fetch
        (v0.6.11, P610-1) — it calls ``_real_execution`` instead.
        """
        attempt = self.call_counts.get(agent_id, 1)
        results: list[ToolResult] = []
        for tool_name in tool_names:
            try:
                result = self.tool_registry.run(tool_name, task.description)
            except Exception as exc:  # defensive: run() already catches, but stay safe
                result = ToolResult(query=task.description, offline=True, error=str(exc))
            results.append(result)
            # Kept as TOOL_CALLED for backward compatibility with existing logs.
            self._record_tool_event(
                agent_id=agent_id,
                tool_name=tool_name,
                result=result,
                attempt=attempt,
                arguments={"query": task.description},
                outcome="error" if result.error else "ok",
            )
        return results

    def _format_tool_blocks(self, results: list[ToolResult]) -> str:
        blocks: list[str] = []
        for result in results:
            tool_name = result.tool or "tool"
            label = _tool_label(result)
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
            for ordinal, item in enumerate(result.search_results, start=1):
                # v0.6.9 (F13): identity comes from *what the source is* (its
                # normalised URL, or the producing artifact for URL-less stubs),
                # never from a per-artifact positional counter — otherwise two
                # agents mint the same id for different sources and the merge
                # below mixes their url/type.
                source_id, basis = derive_source_identity(
                    url=item.url,
                    artifact_id=artifact_id,
                    title=item.title,
                    ordinal=ordinal,
                )
                sources.append(
                    Source(
                        id=source_id,
                        identity=basis,
                        title=item.title,
                        url=item.url,
                        source_type="offline_mock" if result.offline else item.source,
                        retrieved_at=now_iso(),
                    )
                )
                snippets.append(item.snippet)
        evidence: list[Evidence] = []
        candidates = list(zip(sources, snippets, strict=False))
        for point in deliverable.key_points:
            usable, quality_reason = assess_claim(point)
            if not usable:
                # Keep the raw text (never silently drop) but do not bind it to
                # any source: a table row / fragment is not a verifiable claim.
                evidence.append(
                    Evidence(
                        claim=point[:300],
                        evidence="",
                        source_id="",
                        producer_agent=agent_id,
                        artifact_id=artifact_id,
                        claim_type="unverified_claim",
                        review_status="unsupported",
                        match_score=0.0,
                        match_method=f"low_quality:{quality_reason}",
                    )
                )
                continue
            index, score, numeric, lexical = match_claim_to_snippet(point, candidates)
            if index is None:
                # No retrieved snippet supports this claim: keep the claim but
                # leave it UNBOUND rather than attaching an arbitrary source.
                evidence.append(
                    Evidence(
                        claim=point[:300],
                        evidence="",
                        source_id="",
                        producer_agent=agent_id,
                        artifact_id=artifact_id,
                        claim_type="unverified_claim",
                        review_status="unsupported",
                        match_score=score,
                        match_method=(
                            "no_snippet_above_threshold" if candidates else "no_candidates"
                        ),
                    )
                )
                continue
            source, snippet = candidates[index]
            evidence.append(
                Evidence(
                    claim=point[:300],
                    evidence=snippet,
                    source_id=source.id,
                    producer_agent=agent_id,
                    artifact_id=artifact_id,
                    claim_type="source_fact",
                    review_status="not_checked",
                    match_score=score,
                    match_method=f"numeric={numeric};lexical={lexical}",
                )
            )
        return sources, evidence

    def _real_execution(
        self, agent: AgentSpec, agent_context, task: Task
    ) -> tuple[AgentDeliverable, list[Source], list[Evidence], list[str], bool]:
        """Real-LLM tool-calling loop: the LLM decides between calling a
        registered tool (schema: ToolCall) and finishing with a deliverable.
        Bounded by max_tool_calls / max_iterations; tool failures become
        structured ToolResults fed back into the prompt — never crashes.

        Returns ``(deliverable, sources, evidence, used_tools, partial)``. ``partial``
        is ``True`` when the agent could not finish a complete deliverable (ran out
        of tool/iteration budget, or finished without a deliverable but had partial
        tool results) so the scheduler/session can mark the outcome honestly
        instead of counting an incomplete result as a full success.
        """
        agent_id = agent.id or "unknown"
        collected: list[ToolResult] = []
        used_tools: list[str] = []
        partial = False
        # v0.6.11 (P610-2): ``Agent.tools`` is the permission boundary. The LLM is
        # only shown the authorised tools, and every requested call is checked
        # again in code *before* execution.
        allowed = list(agent.tools or [])
        attempt = self.call_counts.get(agent_id, 1)
        base_prompt = self._artifact_prompt(agent_context, task, "")
        advertised = self.tool_registry.available_for(allowed)
        available = ", ".join(advertised) or "(none - this agent has no tool permission)"
        deliverable: AgentDeliverable | None = None
        # D4: tool *authorisation* is not an obligation to call one - but when the
        # declared intent is source-required, the requirement is stated explicitly
        # instead of being left implicit. This never forces a call and never
        # fabricates one: if the agent still does not search, the missing source
        # is reported as a gap and the run is judged honestly (not loosened).
        sourcing_note = self._sourcing_requirement_note(agent, agent_context)
        for _ in range(self.max_iterations):
            decision_prompt = (
                base_prompt
                + self._format_decision_results(collected)
                + f"\nAvailable tools: {available}\n"
                + sourcing_note
                + "Decide the next step. Return JSON matching AgentDecision: "
                "either action='call_tool' with tool_call{tool_name, arguments} "
                "(arguments must include the required keys for that tool), "
                "or action='finish' with deliverable{title, summary, key_points, "
                "structured_data, sources}. Cite only tool-provided information."
            )
            decision = self._complete_with_length_recovery(
                decision_prompt,
                AgentDecision,
                agent_id=agent_id,
                stage="agent_decision",
            )
            if decision.action == "call_tool" and decision.tool_call is not None:
                if len(collected) >= self.max_tool_calls:
                    break  # tool budget exhausted — synthesize partial below
                tool_name = decision.tool_call.tool_name
                call_arguments = dict(decision.tool_call.arguments)
                # --- permission gate: never execute an unauthorised tool ------
                denial = ""
                try:
                    self.tool_registry.validate_allowed(tool_name, allowed)
                except ToolNotAllowed as exc:
                    denial = f"tool_not_allowed: {exc}"
                except ToolNotFound as exc:
                    denial = f"unknown_tool: {exc}"
                if denial:
                    result = ToolResult(
                        query=str(call_arguments.get("query") or tool_name),
                        offline=True,
                        error=denial,
                    )
                    # Feed the refusal back so the model can correct itself within
                    # the existing iteration / LLM-call budget (no execution, no
                    # external call, no cost).
                    collected.append(result)
                    self._record_tool_event(
                        agent_id=agent_id,
                        tool_name=tool_name,
                        result=result,
                        attempt=attempt,
                        arguments=call_arguments,
                        outcome="denied",
                        denial_reason=denial.split(":", 1)[0],
                    )
                    continue
                try:
                    result = self.tool_registry.execute(tool_name, call_arguments)
                except ToolError as exc:
                    result = ToolResult(query=tool_name, offline=True, error=str(exc))
                collected.append(result)
                used_tools.append(tool_name)
                self._record_tool_event(
                    agent_id=agent_id,
                    tool_name=tool_name,
                    result=result,
                    attempt=attempt,
                    arguments=call_arguments,
                    outcome="error" if result.error else "ok",
                )
                continue
            if decision.deliverable is not None:
                deliverable = decision.deliverable
                break
            # The model chose to finish without a deliverable. Do NOT fabricate
            # success: if tools produced material, fall back to an explicitly
            # partial deliverable; otherwise fail so retry/replan can react.
            if collected:
                deliverable = AgentDeliverable(
                    title=f"{agent.role.name} — partial deliverable",
                    summary=(
                        "[real mode] model finished without a deliverable; "
                        "partial tool results only."
                    ),
                    key_points=[item for result in collected for item in result.results][:3],
                )
                partial = True
                break
            raise ProviderError("agent finished without a deliverable")
        if deliverable is None:  # budget/iteration limit reached
            deliverable = AgentDeliverable(
                title=f"{agent.role.name} — partial deliverable",
                summary="[real mode] tool/iteration budget reached; partial results only.",
                key_points=[
                    item for result in collected for item in result.results
                ][:3],
            )
            partial = True
        sources, evidence = self._collect_evidence(
            collected,
            deliverable,
            agent_id=agent_id,
            artifact_id=f"artifact_{agent_id}",
        )
        return deliverable, sources, evidence, used_tools, partial

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
        is_partial: bool = False,
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
                # v0.6.6: the *declared* subtask intent, so the source policy can
                # ask "did this deliverable have to be sourced?" without ever
                # keying off a role name or an agent id.
                "expected_output": agent_context.expected_output,
                "expected_outputs": list(agent_context.expected_outputs),
                "tools_used": list(tools_used or []),
                # v0.6.0-final (R5): an explicitly partial deliverable (real mode
                # budget/iteration exhaustion, or finish-without-deliverable) is
                # flagged so the session never counts it as a full success.
                "partial": bool(is_partial),
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
                is_partial = False
                if isinstance(self.provider, MockLLMProvider):
                    # Offline mode (unchanged): the declared tool list *is* the
                    # plan, so the tools are invoked up-front and their results
                    # flow into the evidence/source collection.
                    collected = self._invoke_tools(list(agent.tools), context.task, agent_id)
                    tool_text = self._format_tool_blocks(collected)
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
                    # Real mode (v0.6.11, P610-1): do NOT pre-fetch the declared
                    # tools. The LLM decides which authorised tool to call, and
                    # only those results enter ``collected`` -> ``_collect_evidence``.
                    (
                        deliverable,
                        sources,
                        evidence,
                        tools_used,
                        is_partial,
                    ) = self._real_execution(agent, agent_context, context.task)
                output = self._build_artifact(
                    agent,
                    agent_context,
                    deliverable,
                    context.task,
                    source_records=sources,
                    evidence=evidence,
                    tools_used=tools_used,
                    is_partial=is_partial,
                )
            elif use_dynamic:
                output_model = dynamic_model
                tool_text = self._run_tools(list(agent.tools), context.task, agent_id)
                prompt = self._dynamic_prompt(agent, context.task, upstream_text, tool_text)
                output = self._complete_with_length_recovery(
                    prompt, output_model, agent_id=agent_id, stage="agent_output"
                )
            else:
                output_model = behavior.output_model
                tool_text = self._run_tools(behavior.tools, context.task, agent_id)
                prompt = behavior.prompt_builder(context.task, role_name, upstream_text, tool_text)
                output = self._complete_with_length_recovery(
                    prompt, output_model, agent_id=agent_id, stage="agent_output"
                )
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


# --- deterministic claim -> snippet binding (v0.6.1) ------------------------
# A claim may only cite a source whose retrieved text actually supports it.
# Matching uses the claim's own numbers and wording — never array position,
# round-robin order or agent execution order.
NUMERIC_HIT_THRESHOLD = 0.6
LEXICAL_OVERLAP_THRESHOLD = 0.45


def _numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def _claim_tokens(text: str) -> set[str]:
    """CJK character bigrams + latin/number words. Deterministic, no LLM."""
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9._%-]*", lowered))
    cjk = re.findall(r"[一-鿿]", lowered)
    tokens.update("".join(pair) for pair in zip(cjk, cjk[1:], strict=False))
    return {token for token in tokens if len(token) > 1}


def relevance_score(claim: str, snippet: str) -> tuple[float, float, float]:
    """(score, numeric_hit_ratio, lexical_overlap) between a claim and a snippet."""
    claim_numbers = _numbers_in(claim)
    snippet_numbers = _numbers_in(snippet)
    numeric = (
        len(claim_numbers & snippet_numbers) / len(claim_numbers) if claim_numbers else 0.0
    )
    claim_tokens = _claim_tokens(claim)
    lexical = (
        len(claim_tokens & _claim_tokens(snippet)) / len(claim_tokens) if claim_tokens else 0.0
    )
    score = (0.7 * numeric + 0.3 * lexical) if claim_numbers else lexical
    return round(score, 4), round(numeric, 4), round(lexical, 4)


def match_claim_to_snippet(
    claim: str, candidates: list[tuple[Any, str]]
) -> tuple[int | None, float, float, float]:
    """Bind a claim to the best supporting snippet, or to nothing.

    Returns ``(index | None, score, numeric, lexical)``. ``None`` means no
    candidate cleared the threshold, so the claim stays unbound instead of being
    attached to an arbitrary source.
    """
    if not candidates:
        return None, 0.0, 0.0, 0.0
    best_score, best_index, best_numeric, best_lexical = -1.0, None, 0.0, 0.0
    for index, (_source, snippet) in enumerate(candidates):
        score, numeric, lexical = relevance_score(claim, snippet)
        if score > best_score:
            best_score, best_index, best_numeric, best_lexical = score, index, numeric, lexical
    has_numbers = bool(_numbers_in(claim))
    ok = (
        best_numeric >= NUMERIC_HIT_THRESHOLD
        if has_numbers
        else best_lexical >= LEXICAL_OVERLAP_THRESHOLD
    )
    if not ok:
        return None, best_score, best_numeric, best_lexical
    return best_index, best_score, best_numeric, best_lexical


def _summarize_arguments(arguments: dict[str, str], limit: int = 120) -> str:
    """Bounded, secret-free summary of tool arguments for the audit trail."""
    parts = []
    for key in sorted(arguments or {}):
        value = " ".join(str(arguments[key] or "").split())
        parts.append(f"{key}={value[:limit]}")
    return "; ".join(parts)[:limit * 2]


def _tool_label(result: ToolResult) -> str:
    """Accurate, honest label for a tool result's execution nature."""
    return {
        "web": "web",
        "local": "local",
        "offline_mock": "offline mock",
        "offline_fallback": "offline fallback",
    }.get(result.kind, "offline")


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
    if "without a deliverable" in text:
        return "Agent execution failed: model returned no deliverable"
    return f"Agent execution failed: {name}"
