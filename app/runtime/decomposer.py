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

import networkx as nx

from app.llm.provider import LLMProvider, MockLLMProvider, OpenAILLMProvider
from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.runtime.dynamic_models import DynamicPlan, DynamicSubtask
from app.runtime.models import SubtaskPlan
from app.runtime.understanding import TaskUnderstanding
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


# ---------------------------------------------------------------------------
# v0.3.0 — dynamic decomposition driven by the discovered capability set.
# ---------------------------------------------------------------------------

# Execution stage of each capability: research/planning first, architecture and
# analysis second, implementation third, verification fourth, synthesis last.
_STAGE_BY_CAPABILITY: dict[CapabilityName, int] = {
    CapabilityName.REQUIREMENT_ANALYSIS: 0,
    CapabilityName.MARKET_RESEARCH: 0,
    CapabilityName.CUSTOMER_RESEARCH: 0,
    CapabilityName.SYSTEM_ARCHITECTURE: 1,
    CapabilityName.STRATEGY_PLANNING: 1,
    CapabilityName.COMPETITOR_ANALYSIS: 2,
    CapabilityName.TECHNOLOGY_ANALYSIS: 2,
    CapabilityName.DATA_ANALYSIS: 2,
    CapabilityName.FINANCIAL_ANALYSIS: 2,
    CapabilityName.DATABASE_DESIGN: 2,
    CapabilityName.API_DESIGN: 2,
    CapabilityName.PRODUCT_DESIGN: 2,
    CapabilityName.RISK_ANALYSIS: 2,
    CapabilityName.FACT_CHECKING: 2,
    CapabilityName.BACKEND_DEVELOPMENT: 3,
    CapabilityName.CODE_GENERATION: 3,
    CapabilityName.TEST_WRITING: 4,
    CapabilityName.CODE_REVIEW: 4,
    CapabilityName.REPORT_WRITING: 5,
    CapabilityName.PROPOSAL_WRITING: 5,
    CapabilityName.TASK_PLANNING: 5,
}

_CAPABILITY_TITLE: dict[CapabilityName, str] = {
    CapabilityName.MARKET_RESEARCH: "Market Overview Research",
    CapabilityName.COMPETITOR_ANALYSIS: "Competitor Analysis",
    CapabilityName.TECHNOLOGY_ANALYSIS: "Technology Trend Analysis",
    CapabilityName.DATA_ANALYSIS: "Data Analysis",
    CapabilityName.REPORT_WRITING: "Final Report Writing",
    CapabilityName.REQUIREMENT_ANALYSIS: "Requirement Analysis",
    CapabilityName.SYSTEM_ARCHITECTURE: "System Architecture Design",
    CapabilityName.API_DESIGN: "API Design",
    CapabilityName.DATABASE_DESIGN: "Database Design",
    CapabilityName.BACKEND_DEVELOPMENT: "Backend Implementation",
    CapabilityName.TEST_WRITING: "Testing Strategy",
    CapabilityName.CUSTOMER_RESEARCH: "Customer Research",
    CapabilityName.STRATEGY_PLANNING: "Strategy Planning",
    CapabilityName.FINANCIAL_ANALYSIS: "Financial Analysis",
    CapabilityName.PROPOSAL_WRITING: "Proposal Writing",
    CapabilityName.PRODUCT_DESIGN: "Product Design",
    CapabilityName.RISK_ANALYSIS: "Risk Analysis",
    CapabilityName.FACT_CHECKING: "Fact Checking",
    CapabilityName.CODE_GENERATION: "Implementation",
    CapabilityName.CODE_REVIEW: "Code Review",
    CapabilityName.TASK_PLANNING: "Task Planning",
}

_CAPABILITY_OUTPUT: dict[CapabilityName, str] = {
    CapabilityName.MARKET_RESEARCH: "market_overview",
    CapabilityName.COMPETITOR_ANALYSIS: "competitor_landscape",
    CapabilityName.TECHNOLOGY_ANALYSIS: "technology_trends",
    CapabilityName.DATA_ANALYSIS: "data_insights",
    CapabilityName.REPORT_WRITING: "final_report",
    CapabilityName.REQUIREMENT_ANALYSIS: "requirements_document",
    CapabilityName.SYSTEM_ARCHITECTURE: "architecture_design",
    CapabilityName.API_DESIGN: "api_specification",
    CapabilityName.DATABASE_DESIGN: "database_schema",
    CapabilityName.BACKEND_DEVELOPMENT: "backend_implementation",
    CapabilityName.TEST_WRITING: "test_plan",
    CapabilityName.CUSTOMER_RESEARCH: "customer_insights",
    CapabilityName.STRATEGY_PLANNING: "strategy_document",
    CapabilityName.FINANCIAL_ANALYSIS: "financial_assessment",
    CapabilityName.PROPOSAL_WRITING: "proposal_document",
    CapabilityName.PRODUCT_DESIGN: "product_design",
    CapabilityName.RISK_ANALYSIS: "risk_assessment",
    CapabilityName.FACT_CHECKING: "fact_check_report",
    CapabilityName.CODE_GENERATION: "implementation",
    CapabilityName.CODE_REVIEW: "review_notes",
    CapabilityName.TASK_PLANNING: "work_plan",
}

_DYNAMIC_DECOMPOSE_PROMPT = (
    "Decompose the task into 3-6 subtasks. Each subtask needs: id (subtask_N), "
    "title, description, required_capabilities (from the capability vocabulary), "
    "dependencies (ids of subtasks it depends on) and expected_output. "
    "Dependencies must reference existing subtask ids and must not form a cycle. "
    "Return JSON matching DynamicPlan.\n\nUNDERSTANDING: {understanding}"
)


class DynamicDecomposer:
    """Builds a dependency-explicit DynamicPlan from a TaskUnderstanding.

    Offline: deterministic stage-based decomposition — capabilities are ordered
    by execution stage and each subtask depends on every subtask of the previous
    stage. A real LLM may propose the plan instead; the code then validates ids,
    capability values and the dependency DAG and falls back to the deterministic
    plan on any violation.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    def decompose(self, understanding: TaskUnderstanding) -> DynamicPlan:
        baseline = self._rule_based(understanding)
        if not isinstance(self.provider, OpenAILLMProvider):
            return baseline
        try:
            proposed = self.provider.structured_completion(
                _DYNAMIC_DECOMPOSE_PROMPT.format(understanding=understanding.model_dump_json()),
                DynamicPlan,
            )
        except Exception:
            return baseline
        return self._validate(proposed) or baseline

    def _rule_based(self, understanding: TaskUnderstanding) -> DynamicPlan:
        capabilities = sorted(
            set(understanding.required_capabilities),
            key=lambda c: (_STAGE_BY_CAPABILITY.get(c, 5), c.value),
        )
        stages: dict[int, list[CapabilityName]] = {}
        for capability in capabilities:
            stages.setdefault(_STAGE_BY_CAPABILITY.get(capability, 5), []).append(capability)

        subtasks: list[DynamicSubtask] = []
        previous_ids: list[str] = []
        for stage in sorted(stages):
            current_ids: list[str] = []
            for capability in stages[stage]:
                index = len(subtasks) + 1
                title = _CAPABILITY_TITLE.get(
                    capability, capability.value.replace("_", " ").title()
                )
                subtask_id = f"subtask_{index}"
                subtasks.append(
                    DynamicSubtask(
                        id=subtask_id,
                        title=title,
                        description=f"{title} covering '{capability.value}' for the given task.",
                        required_capabilities=[capability],
                        dependencies=list(previous_ids),
                        expected_output=_CAPABILITY_OUTPUT.get(capability, "deliverable"),
                    )
                )
                current_ids.append(subtask_id)
            previous_ids = current_ids
        return DynamicPlan(
            objective=understanding.objective,
            domain=understanding.domain,
            subtasks=subtasks,
        )

    @staticmethod
    def _validate(proposed: DynamicPlan) -> DynamicPlan | None:
        """Code validates an LLM-proposed plan; None means 'reject, use rules'."""
        try:
            ids = [subtask.id for subtask in proposed.subtasks]
        except Exception:
            return None
        if not proposed.subtasks or len(ids) != len(set(ids)):
            return None
        id_set = set(ids)
        for subtask in proposed.subtasks:
            if not subtask.required_capabilities:
                return None
            if subtask.id in subtask.dependencies:
                return None
            if any(dep not in id_set for dep in subtask.dependencies):
                return None
        graph = nx.DiGraph()
        graph.add_nodes_from(ids)
        graph.add_edges_from(
            (dep, subtask.id)
            for subtask in proposed.subtasks
            for dep in subtask.dependencies
        )
        if not nx.is_directed_acyclic_graph(graph):
            return None
        return proposed
