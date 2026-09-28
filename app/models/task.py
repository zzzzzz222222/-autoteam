from enum import Enum

from pydantic import BaseModel, Field

from .capability import CapabilityName


class ComplexityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Task(BaseModel):
    description: str
    context: str | None = None


class TaskAnalysis(BaseModel):
    complexity: ComplexityLevel
    required_capabilities: list[CapabilityName]
    reasoning: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
