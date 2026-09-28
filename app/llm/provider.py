"""LLM provider abstraction for AutoTeam v0.2.0.

Replaces the single hardcoded OpenAI client with a provider interface so the
offline demo can run on a deterministic MockProvider and a real key enables an
OpenAI / DeepSeek compatible provider. Every provider exposes one method:

    structured_completion(prompt, response_model) -> response_model

which returns a Pydantic-validated object. This keeps the rule
"LLM proposes, Schema constrains, Code validates, Executor executes".
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class LLMProvider(Protocol):
    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        ...


class ProviderError(RuntimeError):
    """A real provider call failed (auth, network, rate limit, bad response).

    The message intentionally contains only the exception type — never the API
    key, request headers or raw response. Callers decide whether to fall back
    to the mock provider or fail the run.
    """


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

    def __init__(self, *, api_key: str, base_url: str | None, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Return only valid JSON matching the requested schema.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("LLM returned an empty response.")
            return response_model.model_validate(json.loads(content))
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"LLM provider call failed: {type(exc).__name__}") from exc


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
    return OpenAILLMProvider(api_key=api_key, base_url=base_url, model=model)


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
