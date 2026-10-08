"""Dynamic team pipeline (v0.3.0).

``build_dynamic_team`` runs the full dynamic chain and produces an
``ExecutionPlan``:

    Task → TaskUnderstanding → CapabilityDiscovery → DynamicDecomposition
         → RoleAllocation → AgentFactory (+ToolSelector) → DependencyAnalysis
         → ExecutionPlan (+ TeamFormationExplanation)

``run_dynamic_team`` executes that plan through the *existing*
``AsyncDAGScheduler`` + ``AgentRuntime`` — no scheduler is copied or replaced.
Offline (no real provider) the whole chain is deterministic.
"""

from __future__ import annotations

from app.llm.provider import LLMProvider, MockLLMProvider
from app.models.task import Task
from app.models.topology import Topology, TopologyEdge, TopologyType
from app.runtime.agent_factory import DynamicAgentFactory
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.capability_discovery import CapabilityDiscovery
from app.runtime.decomposer import DynamicDecomposer
from app.runtime.dependency import DependencyAnalyzer
from app.runtime.dynamic_models import (
    AgentReason,
    DependencyAnalysis,
    DynamicAgentSpec,
    DynamicPlan,
    ExecutionPlan,
    RoleSpec,
    TeamFormationExplanation,
)
from app.runtime.result_store import ResultStore
from app.runtime.role_allocation import DynamicRoleAllocator
from app.runtime.tool_selector import ToolSelector
from app.runtime.understanding import TaskUnderstanding
from app.scheduler.models import AgentResult
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.tools.registry import ToolRegistry
from app.topology.validator import TopologyValidator, compute_parallel_layers


def build_dynamic_team(
    task: str | Task,
    provider: LLMProvider | None = None,
    registry: ToolRegistry | None = None,
) -> ExecutionPlan:
    agent_task = task if isinstance(task, Task) else Task(description=task)
    tool_registry = registry or ToolRegistry(mode="auto")

    understanding = CapabilityDiscovery(provider).discover(agent_task)
    plan: DynamicPlan = DynamicDecomposer(provider).decompose(understanding)
    roles: list[RoleSpec] = DynamicRoleAllocator().allocate(plan)
    factory = DynamicAgentFactory(ToolSelector(tool_registry))
    agents: list[DynamicAgentSpec] = [factory.create(role, plan, understanding) for role in roles]
    analysis: DependencyAnalysis = DependencyAnalyzer().analyze(plan, roles)

    topology = Topology(
        type=TopologyType.HIERARCHICAL,
        agents=[agent.id for agent in agents],
        edges=[
            TopologyEdge(source=edge.source, target=edge.target) for edge in analysis.agent_edges
        ],
        root_agent=None,  # fan-in / layered graphs may have several entry agents
    )
    TopologyValidator().validate(topology)
    topology.parallel_layers = compute_parallel_layers(
        TopologyValidator().build_graph(topology)
    )

    tools_map = {agent.id: list(agent.tools) for agent in agents}
    explanation = _build_explanation(
        agent_task.description, understanding, roles, agents, analysis, tools_map
    )
    return ExecutionPlan(
        task=agent_task.description,
        understanding=understanding,
        subtasks=plan.subtasks,
        roles=roles,
        agents=agents,
        dependencies=analysis.agent_edges,
        execution_layers=analysis.execution_layers,
        topology=topology,
        tools=tools_map,
        explanation=explanation,
    )


async def run_dynamic_team(
    plan: ExecutionPlan,
    provider: LLMProvider | None = None,
    tool_mode: str = "auto",
    store: ResultStore | None = None,
    max_concurrency: int | None = None,
) -> dict[str, AgentResult]:
    """Execute an ExecutionPlan with the existing scheduler and runtime."""
    runtime = AgentRuntime(
        provider=provider or MockLLMProvider(),
        tool_registry=ToolRegistry(mode=tool_mode),
        store=store or ResultStore(),
    )
    if store is not None:
        store.set_structure(
            DynamicPlan(
                objective=plan.understanding.objective,
                domain=plan.understanding.domain,
                subtasks=plan.subtasks,
            ),
            list(plan.agents),
            plan.topology,
        )
    scheduler = AsyncDAGScheduler(
        executor=runtime,
        max_concurrency=max_concurrency,
        retry_policy=RetryPolicy(max_retries=1),
    )
    return await scheduler.run(Task(description=plan.task), plan.topology, plan.agents)


def _build_explanation(
    task: str,
    understanding: TaskUnderstanding,
    roles: list[RoleSpec],
    agents: list[DynamicAgentSpec],
    analysis: DependencyAnalysis,
    tools_map: dict[str, list[str]],
) -> TeamFormationExplanation:
    depends_on: dict[str, list[str]] = {agent.id: [] for agent in agents}
    names = {agent.id: agent.role.name for agent in agents}
    for edge in analysis.agent_edges:
        depends_on[edge.target].append(names.get(edge.source, edge.source))

    agent_reasons: list[AgentReason] = []
    for role, agent in zip(roles, agents):
        subtasks_text = ", ".join(role.assigned_subtasks)
        agent_reasons.append(
            AgentReason(
                agent_id=agent.id,
                agent_name=agent.role.name,
                reason=(
                    f"Created because the task requires "
                    f"{', '.join(c.value for c in role.capabilities)} capability "
                    f"(assigned subtasks: {subtasks_text})."
                ),
                capabilities=[capability.value for capability in role.capabilities],
                tools=list(tools_map.get(agent.id, [])),
                depends_on=depends_on.get(agent.id, []),
            )
        )
    return TeamFormationExplanation(
        task=task,
        domain=understanding.domain,
        reasoning=(
            f"Discovered {len(understanding.required_capabilities)} required capabilities "
            f"in the {understanding.domain} domain; decomposed the task into "
            f"{len(roles)} roles and {len(agents)} agents arranged in "
            f"{len(analysis.execution_layers)} execution layers."
        ),
        required_capabilities=[
            capability.value for capability in understanding.required_capabilities
        ],
        agents=agent_reasons,
    )
