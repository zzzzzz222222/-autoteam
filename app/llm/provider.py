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
