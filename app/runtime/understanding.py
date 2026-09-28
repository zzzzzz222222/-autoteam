"""TaskUnderstanding schema (v0.3.0).

The first stage of the dynamic pipeline: a structured reading of the task —
domain, objective, constraints, expected output and the capability set the task
requires. Offline mode fills it with deterministic rules; a real LLM may refine
it, but the schema and the capability vocabulary always constrain the result.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.capability import CapabilityName
from app.models.task import ComplexityLevel


class TaskUnderstanding(BaseModel):
    task: str
    domain: str = "general"
    objective: str = ""
    constraints: list[str] = Field(default_factory=list)
    expected_output: str = ""
    required_capabilities: list[CapabilityName] = Field(default_factory=list)
    complexity: ComplexityLevel = ComplexityLevel.MEDIUM
