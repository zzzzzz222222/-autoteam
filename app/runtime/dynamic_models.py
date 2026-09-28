"""v0.3.0 dynamic team schemas.

These models carry the full dynamic pipeline:
TaskUnderstanding → DynamicPlan (subtasks) → RoleSpec[] → DynamicAgentSpec[]
→ DependencyAnalysis → ExecutionPlan (+ TeamFormationExplanation).

Design rules enforced here:
- Capability ≠ Role ≠ Agent: capabilities live on subtasks and roles, roles group
  subtasks, agents carry exactly one role.
- Dependencies are structured subtask ids, never prose.
- Explanations are structured, displayable reasons — never LLM chain-of-thought.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.agent import AgentSpec
from app.models.capability import CapabilityName
from app.models.topology import Topology
from app.runtime.models import TaskDeliverable
from app.runtime.understanding import TaskUnderstanding


class DynamicSubtask(BaseModel):
    id: str
    title: str
    description: str = ""
    required_capabilities: list[CapabilityName] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # ids of upstream subtasks
    expected_output: str = ""


class DynamicPlan(BaseModel):
    objective: str = ""
    domain: str = ""
    subtasks: list[DynamicSubtask] = Field(default_factory=list)


class RoleSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    capabilities: list[CapabilityName] = Field(default_factory=list)
    assigned_subtasks: list[str] = Field(default_factory=list)


class DynamicAgentSpec(AgentSpec):
    """A first-class agent configuration produced by the DynamicAgentFactory.

    Extends (never replaces) the v0.1.0 ``AgentSpec`` so every existing
    scheduler / runtime path keeps accepting it unchanged. The actual execution
    still happens in the existing ``AgentRuntime``.
    """

    system_prompt: str = ""
    input_schema: str = ""
    output_schema: type[TaskDeliverable] | None = Field(default=None, exclude=True)
    metadata: dict[str, object] = Field(default_factory=dict)


class DependencyEdge(BaseModel):
    source: str  # upstream agent id
    target: str  # downstream agent id
    reason: str = ""


class DependencyAnalysis(BaseModel):
    agent_edges: list[DependencyEdge] = Field(default_factory=list)
    execution_layers: list[list[str]] = Field(default_factory=list)
    topological_order: list[str] = Field(default_factory=list)
    isolated_agents: list[str] = Field(default_factory=list)


class AgentReason(BaseModel):
    agent_id: str
    agent_name: str
    reason: str
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class TeamFormationExplanation(BaseModel):
    task: str
    domain: str = ""
    reasoning: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    agents: list[AgentReason] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    task: str
    understanding: TaskUnderstanding
    subtasks: list[DynamicSubtask] = Field(default_factory=list)
    roles: list[RoleSpec] = Field(default_factory=list)
    agents: list[DynamicAgentSpec] = Field(default_factory=list)
    dependencies: list[DependencyEdge] = Field(default_factory=list)
    execution_layers: list[list[str]] = Field(default_factory=list)
    topology: Topology
    tools: dict[str, list[str]] = Field(default_factory=dict)
    explanation: TeamFormationExplanation
