"""LLM provider abstraction for AutoTeam v0.2.0.

Replaces the single hardcoded OpenAI client with a provider interface so the
offline demo can run on a deterministic MockProvider and a real key enables an
OpenAI / DeepSeek compatible provider. Every provider exposes one method:

    structured_completion(prompt, response_model) -> response_model

which returns a Pydantic-validated object. This keeps the rule
"LLM proposes, Schema constrains, Code validates, Executor executes".
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.llm.structured import (
    CATEGORY_LENGTH_LIMIT,
    StructuredParseError,
    parse_structured,
)


@runtime_checkable
class LLMProvider(Protocol):
    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        ...


class ProviderError(RuntimeError):
    """A real provider call failed (auth, network, rate limit, bad response).

    The message intentionally contains only the exception type (plus, for
    malformed structured output, a *classified* reason). It never contains the
    API key, request headers or the raw response.

    ``category`` distinguishes a transport/provider failure (``provider_error``)
    from unparseable structured output (``structured_parse``); ``retryable``
    tells the caller whether re-asking could plausibly help. ``diagnostics``
    carries non-reversible facts (length, hash, delimiter balance), never the
    model's raw text.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        retryable: bool = False,
        diagnostics: str = "",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.diagnostics = diagnostics


class MockLLMProvider:
    """Deterministic, offline provider.

    Returns coherent stub objects that depend only on the prompt text and the
    requested model, so the whole research demo runs with no network and no key.
    It mirrors the *shape* of a real response so the downstream code path is
    identical whether a model is real or mocked.
    """

    def __init__(self, *, model: str = "mock") -> None:
        self.model = model

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        return _mock_structured(prompt, response_model)


class OpenAILLMProvider:
    """OpenAI-compatible provider (works with DeepSeek or any /v1 endpoint)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        max_tokens: int | None = None,
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        # Optional output ceiling. ``None`` = do NOT send the parameter, so any
        # endpoint keeps its own default (no assumption about what it supports).
        self.max_tokens = max_tokens
        # Best-effort metadata from the most recent call (never contains the key,
        # headers or the raw prompt/response text).
        self.last_response_meta: dict[str, object] = {}

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        request: dict[str, object] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON matching the requested schema.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        max_tokens = getattr(self, "max_tokens", None)
        if max_tokens is not None:
            # Only sent when explicitly configured: some OpenAI-compatible
            # endpoints reject unknown request parameters.
            request["max_tokens"] = max_tokens
        try:
            response = self._client.chat.completions.create(**request)
        except ProviderError:
            raise
        except Exception as exc:
            # transport / auth / rate-limit failures are never auto-retried here
            raise ProviderError(f"LLM provider call failed: {type(exc).__name__}") from exc

        try:
            choice = response.choices[0]
            content = choice.message.content
        except Exception as exc:
            raise ProviderError(f"LLM provider call failed: {type(exc).__name__}") from exc

        finish_reason = str(getattr(choice, "finish_reason", "") or "")
        usage = getattr(response, "usage", None)
        usage_meta: dict[str, object] = {}
        if usage is not None:
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, field, None)
                if isinstance(value, int):
                    usage_meta[field] = value
        self.last_response_meta = {
            "finish_reason": finish_reason or "unavailable",
            "usage": usage_meta or None,
            "usage_available": bool(usage_meta),
        }

        try:
            # Conservative, classified parsing: fences may be stripped, truncated
            # or non-JSON payloads are rejected (never repaired, never guessed).
            return parse_structured(content, response_model)
        except StructuredParseError as exc:
            # A confirmed length stop is stronger evidence than the delimiter
            # heuristic, so it wins when the endpoint reports one.
            category = CATEGORY_LENGTH_LIMIT if finish_reason == "length" else exc.category
            diagnostics = exc.diagnostics
            if finish_reason:
                diagnostics = f"finish_reason={finish_reason} {diagnostics}"
            if usage_meta:
                diagnostics = f"{diagnostics} usage={usage_meta}"
            error = ProviderError(
                f"structured output invalid [{category}]: {exc}",
                category="structured_parse",
                retryable=True,
                diagnostics=diagnostics,
            )
            error.parse_category = category
            raise error from exc


def get_llm_provider() -> LLMProvider:
    """Resolve a provider from the environment without forcing a network call.

    Offline by default: with no provider / key the demo runs on MockLLMProvider.
    """
    provider = os.getenv("AUTOTEAM_LLM_PROVIDER", "").lower()
    if not provider or provider == "mock":
        return MockLLMProvider(model=os.getenv("AUTOTEAM_LLM_MODEL", "mock"))
    api_key = os.getenv("AUTOTEAM_API_KEY") or os.getenv("LLM_API_KEY", "")
    if not api_key:
        # No key configured -> fall back to mock so the demo still runs offline.
        return MockLLMProvider(model=os.getenv("AUTOTEAM_LLM_MODEL", "mock"))
    model = os.getenv("AUTOTEAM_LLM_MODEL") or (
        "deepseek-chat" if provider == "deepseek" else "gpt-4o-mini"
    )
    base_url = os.getenv("AUTOTEAM_LLM_BASE_URL") or (
        "https://api.deepseek.com/v1" if provider == "deepseek" else None
    )
    raw_max_tokens = os.getenv("AUTOTEAM_LLM_MAX_TOKENS", "").strip()
    max_tokens: int | None = None
    if raw_max_tokens:
        try:
            parsed = int(raw_max_tokens)
            max_tokens = parsed if parsed > 0 else None
        except ValueError:
            max_tokens = None
    return OpenAILLMProvider(
        api_key=api_key, base_url=base_url, model=model, max_tokens=max_tokens
    )


def _mock_structured(prompt: str, response_model: type[BaseModel]) -> BaseModel:
    """Fill a response model with deterministic offline stubs.

    Special-cases SubtaskPlan (so the demo decomposes into sensible research
    steps) and TaskDeliverable (so dynamic agents produce task-referencing
    deliverables); otherwise reflects on the model fields and fills values.
    """
    name = response_model.__name__
    if name == "SubtaskPlan":
        return _mock_subtask_plan(prompt)
    if name == "TaskDeliverable":
        return _mock_task_deliverable(prompt)
    if name == "AgentDeliverable":
        return _mock_agent_deliverable(prompt)
    if name == "SynthesisResult":
        return _mock_synthesis_result(prompt)
    values: dict[str, object] = {}
    for field_name, field in response_model.model_fields.items():
        annotation = field.annotation
        origin = getattr(annotation, "__origin__", None)
        is_list = origin is list or (
            hasattr(annotation, "__args__") and getattr(annotation, "__origin__", None) is list
        )
        if is_list:
            args = getattr(annotation, "__args__", (str,))
            item = args[0] if args else str
            if item is str:
                values[field_name] = [
                    f"[mock] {field_name} item 1 for {name}",
                    f"[mock] {field_name} item 2 for {name}",
                    f"[mock] {field_name} item 3 for {name}",
                ]
            else:
                try:
                    values[field_name] = [item()]
                except Exception:
                    values[field_name] = []
        elif annotation is str:
            values[field_name] = f"[mock] {field_name} derived from the task (offline stub)."
        elif annotation is int:
            values[field_name] = 1
        elif annotation is float:
            values[field_name] = 0.5
        else:
            try:
                values[field_name] = annotation()
            except Exception:
                values[field_name] = None
    return response_model(**values)


def _mock_subtask_plan(prompt: str) -> "SubtaskPlan":  # noqa: F821
    from app.runtime.models import Subtask, SubtaskPlan

    return SubtaskPlan(
        goal="Produce a structured research report for the given task.",
        subtasks=[
            Subtask(
                description="Survey the overall market and identify key trends.",
                required_capabilities=["market_research", "data_analysis"],
                depends_on=[],
                target_role="Research Agent",
            ),
            Subtask(
                description="Analyze the main vendors and their product direction.",
                required_capabilities=["competitor_analysis", "market_research"],
                depends_on=[],
                target_role="Competitor Analyst",
            ),
            Subtask(
                description="Summarize current technology routes and trends.",
                required_capabilities=["data_analysis", "product_design"],
                depends_on=[],
                target_role="Technology Analyst",
            ),
            Subtask(
                description="Synthesize findings into the final report.",
                required_capabilities=["report_writing"],
                depends_on=[0, 1, 2],
                target_role="Report Writer",
            ),
        ],
    )


def _mock_synthesis_result(prompt: str) -> "SynthesisResult":  # noqa: F821
    """Deterministic offline cross-agent synthesis (v0.6.0).

    Parses ROLE / TASK lines and the evidence ids listed in the prompt so the
    mock synthesis still cites real (mock) evidence ids — the same citation
    validation path runs in offline and real mode.
    """
    from app.synthesis.models import (
        Contradiction,
        Finding,
        Insight,
        Recommendation,
        SynthesisResult,
        Tradeoff,
        Uncertainty,
    )

    task_line = ""
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("TASK:"):
            task_line = line[len("TASK:"):].strip()
            if not task_line and index + 1 < len(lines):
                # the synthesis prompt writes the task on the line *after* "TASK:"
                task_line = lines[index + 1].strip()
            break
    evidence_ids: list[str] = []
    for token in prompt.replace("|", " ").replace("(", " ").replace(")", " ").split():
        if token.startswith("ev_") and token not in evidence_ids:
            evidence_ids.append(token)
    primary = evidence_ids[:2] or []
    secondary = evidence_ids[2:4] or []

    findings = [
        Finding(
            finding_id="find_mock_01",
            statement=(
                f"[offline_mock] Combined review of {len(evidence_ids)} evidence "
                f"records for '{task_line[:80]}' identifies a shared direction "
                "across agent outputs."
            ),
            evidence_ids=list(primary),
            supporting_agents=["mock_synthesizer"],
            support_kind="multi_source" if len(primary) > 1 else "single_source",
            # offline stub content is not a real market fact — tag it honestly
            claim_type="unverified_claim",
            derivation="deterministic offline stub (no external data)",
        )
    ]
    if secondary:
        findings.append(
            Finding(
                finding_id="find_mock_02",
                statement=(
                    "[offline_mock] Secondary evidence adds detail that only "
                    "partially overlaps with the primary claims."
                ),
                evidence_ids=list(secondary),
                supporting_agents=["mock_synthesizer"],
                support_kind="single_source",
                claim_type="unverified_claim",
                derivation="deterministic offline stub (no external data)",
            )
        )
    insights = [
        Insight(
            insight_id="ins_mock_01",
            statement=(
                "[offline_mock] Combining deployment-cost claims with integration "
                "friction claims suggests the product differentiator is likely "
                "packaging and connectivity rather than raw model capability."
            ),
            supporting_evidence_ids=list(primary + secondary),
            supporting_artifact_ids=[],
            producer_agents=["mock_synthesizer"],
            uncertainty="offline stub — verify against real evidence",
            claim_type="derived_estimate",
            derivation="offline deterministic combination of mock evidence snippets",
        )
    ]
    contradictions = [
        Contradiction(
            contradiction_id="con_mock_01",
            claim_a="Agent A reports broad platform support for feature X.",
            claim_b="Agent B reports no clear evidence that feature X is supported.",
            evidence_ids=list(primary[:1] + secondary[:1]),
            source_ids=[],
            agents=["mock_synthesizer"],
            status="unresolved",
            resolution=(
                "Available evidence is insufficient to resolve the discrepancy."
            ),
        )
    ]
    uncertainties = [
        Uncertainty(
            uncertainty_id="unc_mock_01",
            statement=(
                "[offline_mock] Pricing and ROI figures are thin in the collected "
                "evidence; treat cost conclusions as provisional."
            ),
            evidence_ids=list(primary),
            kind="insufficient_evidence",
        )
    ]
    tradeoffs = [
        Tradeoff(
            tradeoff_id="trd_mock_01",
            dimension="deployment cost vs capability depth",
            option_a="Low-cost packaged agent suite",
            option_b="Custom high-capability agent stack",
            gains_a=["faster adoption", "lower upfront cost"],
            costs_a=["less customization", "capability ceiling"],
            gains_b=["deeper capability", "tighter fit"],
            costs_b=["higher cost", "longer delivery"],
            evidence_ids=list(primary + secondary),
            implications=[
                "SME segments favour option A until internal AI staffing improves."
            ],
        )
    ]
    recommendations = [
        Recommendation(
            recommendation_id="rec_mock_01",
            statement=(
                "[offline_mock] Prioritise a modular, low-deployment-cost agent "
                "suite with standard connectors for SME customers."
            ),
            supporting_insight_ids=["ins_mock_01"],
            supporting_tradeoff_ids=["trd_mock_01"],
            supporting_evidence_ids=list(primary),
            limitations=["offline mock recommendation — not a market verdict"],
            status="supported" if primary else "unsupported",
            claim_type="planning_assumption",
        )
    ]
    return SynthesisResult(
        key_findings=findings,
        supported_findings=findings[:1],
        single_source_findings=findings[1:] or [],
        cross_agent_insights=insights,
        contradictions=contradictions,
        uncertainties=uncertainties,
        tradeoffs=tradeoffs,
        recommendations=recommendations,
        summary=(
            f"[offline_mock] Cross-agent synthesis for '{task_line[:80]}': "
            f"{len(findings)} findings, {len(insights)} insight(s), "
            f"{len(contradictions)} contradiction(s), {len(tradeoffs)} trade-off(s)."
        ),
        notes="deterministic offline synthesis stub",
    )


def _mock_agent_deliverable(prompt: str) -> "AgentDeliverable":  # noqa: F821
    """Deterministic offline deliverable for a v0.4.0 dynamic agent.

    Parses ROLE / EXPECTED_OUTPUT / TASK lines from the assembled prompt and
    emits a stable structured_data key=value pair so downstream agents and the
    final artifact demonstrably carry real intermediate results.
    """
    from app.runtime.artifacts import AgentDeliverable

    role = expected = task_line = ""
    for line in prompt.splitlines():
        if line.startswith("ROLE:"):
            role = line[len("ROLE:"):].strip()
        elif line.startswith("EXPECTED_OUTPUT:"):
            expected = line[len("EXPECTED_OUTPUT:"):].strip()
        elif line.startswith("TASK:"):
            task_line = line[len("TASK:"):].strip()

    default_key = f"{expected or 'task'}_result"
    structured: dict[str, str] = {}
    for expected_name in [item.strip() for item in expected.split(",") if item.strip()]:
        out_key, out_value = _MOCK_OUTPUT_DATA.get(
            expected_name, (f"{expected_name}_result", "completed_offline_mock")
        )
        if expected_name == "architecture_design":
            out_value = "modular_fastapi" if "fastapi" in task_line.lower() else "layered_monolith"
        structured[out_key] = out_value
    if not structured:
        structured[default_key] = "completed_offline_mock"

    title_base = (expected.split(",")[0] or "deliverable").replace("_", " ").title()
    return AgentDeliverable(
        title=f"{role or 'Agent'} — {title_base}",
        summary=(
            f"[offline_mock] {role or 'Agent'} completed '{expected}' for "
            f"'{task_line[:60]}' with deterministic stub data."
        ),
        key_points=[
            f"[offline_mock] step 1 of {expected or 'the subtask'} completed.",
            f"[offline_mock] step 2 of {expected or 'the subtask'} completed.",
            "[offline_mock] deterministic stub — no real LLM or live tools involved.",
        ],
        structured_data=structured,
        sources=[],
    )


_MOCK_OUTPUT_DATA: dict[str, tuple[str, str]] = {
    "market_overview": ("market_outlook", "growing_demand"),
    "competitor_landscape": ("competitor_positioning", "diverse_players"),
    "technology_trends": ("technology_trend", "agent_frameworks_rising"),
    "customer_insights": ("customer_needs", "automation_first"),
    "data_insights": ("data_insight", "smb_segment_leading"),
    "financial_assessment": ("financial_view", "cost_sensitive_smb"),
    "strategy_document": ("strategy_choice", "smb_focused_entry"),
    "requirements_document": ("requirements_scope", "mvp_scope_defined"),
    "architecture_design": ("architecture_decision", "modular_monolith"),
    "database_schema": ("database_schema", "relational_core_tables"),
    "api_specification": ("api_contract", "rest_json_v1"),
    "backend_implementation": ("backend_plan", "fastapi_router_service_layout"),
    "test_plan": ("test_strategy", "pytest_unit_and_integration"),
    "final_report": ("report_structure", "sectioned_markdown"),
    "proposal_document": ("proposal_outline", "phased_rollout"),
    "work_plan": ("work_plan", "milestone_based"),
}


def _mock_task_deliverable(prompt: str) -> "TaskDeliverable":  # noqa: F821
    from app.runtime.models import TaskDeliverable

    task_line = ""
    for line in prompt.splitlines():
        if line.startswith("TASK:"):
            task_line = line[len("TASK:"):].strip()
            break
    return TaskDeliverable(
        title=f"Deliverable — {task_line[:60]}" if task_line else "Deliverable (offline stub)",
        summary=(
            f"[mock] structured deliverable for '{task_line[:80]}' (offline stub)."
            if task_line
            else "[mock] structured deliverable (offline stub)."
        ),
        key_points=[
            "[mock] key point 1 derived from the task and upstream inputs.",
            "[mock] key point 2 derived from the task and upstream inputs.",
            "[mock] key point 3 derived from the task and upstream inputs.",
        ],
        sources=[],
    )
