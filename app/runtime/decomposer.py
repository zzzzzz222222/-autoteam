"""Task decomposition and team/topology derivation (v0.2.0 planner layer).

``TaskDecomposer`` turns a free-text task into a schema-constrained ``SubtaskPlan``
via the LLM provider. ``build_team`` and ``build_topology`` then derive the agent
team and the collaboration DAG directly from that plan.

This is a *new* layer on top of the v0.1.0 engine. It deliberately does not reuse
``TaskAnalyzer`` / ``RoleAllocator`` / ``TopologyGenerator``: the plan already
encodes each subtask's role and dependencies, so re-deriving them from capability
keywords would be redundant and would lose the planner's structure.
"""

from __future__ import annotations

import re

from app.llm.provider import LLMProvider, MockLLMProvider
from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.runtime.models import SubtaskPlan
from app.topology.validator import TopologyValidator, compute_parallel_layers

_DECOMPOSE_PROMPT = (
    "Decompose the task into 3-5 research subtasks performed by a team of "
    "specialist agents (Research Agent, Competitor Analyst, Technology Analyst, "
    "Report Writer). For each subtask provide: description, required_capabilities "
    "(from the capability pool), depends_on (0-based indices of prior subtasks it "
    "needs), and target_role. Return JSON matching SubtaskPlan."
)


class TaskDecomposer:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or MockLLMProvider()

    def decompose(self, task: Task) -> SubtaskPlan:
        prompt = (
            f"{_DECOMPOSE_PROMPT}\n\n"
            f"TASK: {task.description}\nCONTEXT: {task.context or ''}"
        )
        return self.provider.structured_completion(prompt, SubtaskPlan)


def _safe_capabilities(names: list[str]) -> list[CapabilityName]:
    capabilities: list[CapabilityName] = []
    for name in names:
        try:
            capabilities.append(CapabilityName(name))
        except Exception:
            continue
    return capabilities


def _slug(name: str, index: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or f"agent_{index}").lower()).strip("_")
    return base or f"agent_{index}"


def build_team(plan: SubtaskPlan) -> list[AgentSpec]:
    """One agent per subtask; capability set is sanitized against the capability pool."""
    agents: list[AgentSpec] = []
    seen: dict[str, int] = {}
    for index, subtask in enumerate(plan.subtasks):
        slug = _slug(subtask.target_role or f"Agent {index + 1}", index)
        if slug in seen:
            slug = f"{slug}_{index}"
        seen[slug] = 1
        role = AgentRole(
            name=subtask.target_role or f"Agent {index + 1}",
            capabilities=_safe_capabilities(subtask.required_capabilities),
            goal=subtask.description or "完成分配的研究子任务",
        )
        agents.append(
            AgentSpec(id=slug, role=role, tools=["web_search"], max_iterations=1)
        )
    return agents


def build_topology(agents: list[AgentSpec], plan: SubtaskPlan) -> Topology:
    """Edges follow each subtask's ``depends_on`` indices; fan-in graphs have no root."""
    ids = [agent.id for agent in agents]
    edges: list[TopologyEdge] = []
    for index, subtask in enumerate(plan.subtasks):
        if index >= len(ids):
            continue
        for dependency in subtask.depends_on:
            if 0 <= dependency < len(ids) and dependency != index:
                edges.append(TopologyEdge(source=ids[dependency], target=ids[index]))
    topology = Topology(
        type=TopologyType.HIERARCHICAL,
        agents=ids,
        edges=edges,
        root_agent=None,  # fan-in graphs have no single root; reachability check is skipped
    )
    validator = TopologyValidator()
    validator.validate(topology)
    topology.parallel_layers = compute_parallel_layers(validator.build_graph(topology))
    return topology
