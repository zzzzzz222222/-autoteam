"""Context assembly (v0.4.0).

Builds the per-agent ``AgentExecutionContext``: the task, the agent's own
subtasks, and the *transitive* upstream artifacts it needs — nothing more.
An agent never sees the whole system state; unrelated agents' outputs are
excluded by the dependency graph itself, and only upstream artifacts flow in.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.agent import AgentSpec
from app.runtime.artifacts import AgentArtifact
from app.scheduler.models import ExecutionContext


def upstream_agent_ids(topology, agent_id: str) -> list[str]:
    """All (transitive) upstream agent ids, ordered from the roots downwards."""
    predecessors: dict[str, list[str]] = {target: [] for target in topology.agents}
    for edge in topology.edges:
        predecessors[edge.target].append(edge.source)
    ordered: list[str] = []
    frontier = list(predecessors.get(agent_id, []))
    while frontier:
        current = frontier.pop(0)
        if current in ordered:
            continue
        ordered.append(current)
        frontier.extend(predecessors.get(current, []))
    ordered.reverse()  # roots first, direct upstream last
    return ordered


class AgentExecutionContext(BaseModel):
    """Exactly what one agent needs — no more."""

    agent_id: str
    role_name: str
    task: str
    domain: str = ""
    expected_output: str = ""
    expected_outputs: list[str] = Field(default_factory=list)
    output_type: str = ""
    capabilities: list[str] = Field(default_factory=list)
    subtask_ids: list[str] = Field(default_factory=list)
    subtask_titles: list[str] = Field(default_factory=list)
    upstream_artifacts: list[AgentArtifact] = Field(default_factory=list)
    upstream_findings: dict[str, str] = Field(default_factory=dict)

    @property
    def upstream_artifact_ids(self) -> list[str]:
        return [artifact.artifact_id for artifact in self.upstream_artifacts]

    @property
    def upstream_keys(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for artifact in self.upstream_artifacts:
            merged.update(artifact.structured_data)
        return merged


def assemble_agent_context(agent: AgentSpec, context: ExecutionContext) -> AgentExecutionContext:
    metadata = getattr(agent, "metadata", {}) or {}
    upstream_ids = set(upstream_agent_ids(context.topology, agent.id or ""))

    artifacts: list[AgentArtifact] = []
    findings: dict[str, str] = {}
    for source_id, result in context.results.items():
        output = result.output
        if isinstance(output, AgentArtifact):
            if source_id in upstream_ids:
                artifacts.append(output)
        elif result.status.value == "success" and output is not None and source_id in upstream_ids:
            findings[source_id] = str(output)

    return AgentExecutionContext(
        agent_id=agent.id or "unknown",
        role_name=agent.role.name,
        task=context.task.description,
        domain=str(metadata.get("domain", "")),
        expected_output=str(metadata.get("expected_output", "")),
        expected_outputs=[str(item) for item in (metadata.get("expected_outputs", []) or [])],
        output_type=str(metadata.get("output_type", "")),
        capabilities=[capability.value for capability in agent.role.capabilities],
        subtask_ids=list(metadata.get("assigned_subtasks", []) or []),
        subtask_titles=list(metadata.get("subtask_titles", []) or []),
        upstream_artifacts=artifacts,
        upstream_findings=findings,
    )
