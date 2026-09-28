import pytest
from pydantic import ValidationError

from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import ComplexityLevel, TaskAnalysis


def test_task_analysis_creation_and_confidence_bounds() -> None:
    analysis = TaskAnalysis(
        complexity=ComplexityLevel.LOW,
        required_capabilities=[CapabilityName.TASK_PLANNING],
        reasoning="ok",
        confidence=0,
    )
    assert analysis.confidence == 0
    assert (
        TaskAnalysis(
            complexity=ComplexityLevel.LOW, required_capabilities=[], reasoning="ok", confidence=1
        ).confidence
        == 1
    )
    with pytest.raises(ValidationError):
        TaskAnalysis(
            complexity=ComplexityLevel.LOW,
            required_capabilities=[],
            reasoning="bad",
            confidence=1.1,
        )
    with pytest.raises(ValidationError):
        TaskAnalysis(
            complexity=ComplexityLevel.LOW,
            required_capabilities=[],
            reasoning="bad",
            confidence=-0.1,
        )


def test_agent_spec_json_round_trip() -> None:
    spec = AgentSpec(
        role=AgentRole(
            name="Developer", capabilities=[CapabilityName.CODE_GENERATION], goal="写代码"
        ),
        tools=["code_interpreter"],
    )
    assert AgentSpec.model_validate_json(spec.model_dump_json()) == spec
