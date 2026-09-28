"""v0.3.0 tests — Dynamic Team Intelligence.

Covers: TaskUnderstanding, CapabilityDiscovery, dynamic decomposition, dynamic
role allocation, AgentFactory, ToolSelector, DependencyAnalyzer (incl. cycle /
missing / self dependencies), ExecutionPlan, multi-task differentiation, the
acceptance test from the spec (three tasks → three different teams), offline
E2E execution and the Dynamic Team UI. All offline and deterministic.

The pre-existing 83 tests must keep passing alongside this file.
"""

import asyncio

import pytest

from app.models.agent import AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.runtime.agent_factory import DynamicAgentSpec
from app.runtime.decomposer import TaskDecomposer
from app.runtime.dependency import DependencyAnalyzer
from app.runtime.dynamic_models import DynamicPlan, DynamicSubtask
from app.runtime.dynamic_team import build_dynamic_team, run_dynamic_team
from app.runtime.models import SubtaskPlan, TaskDeliverable
from app.runtime.role_allocation import DynamicRoleAllocator
from app.runtime.tool_selector import ToolSelector
from app.tools.registry import ToolRegistry
from app.topology.validator import TopologyValidator

TASK_A = "分析 AI Agent 市场竞争格局"
TASK_B = "设计一个 FastAPI 电商后端系统"
TASK_C = "制定 SaaS 产品进入某行业的市场策略"


def build(task: str):
    return build_dynamic_team(task)


# ---------------------------------------------------------------------------
# TaskUnderstanding & CapabilityDiscovery
# ---------------------------------------------------------------------------


def test_market_task_understanding():
    u = build(TASK_A).understanding
    assert u.domain == "market_research"
    caps = {c for c in u.required_capabilities}
    assert {CapabilityName.MARKET_RESEARCH, CapabilityName.COMPETITOR_ANALYSIS} <= caps
    assert CapabilityName.REPORT_WRITING in caps


def test_software_task_understanding():
    u = build(TASK_B).understanding
    assert u.domain == "software_engineering"
    caps = set(u.required_capabilities)
    assert {
        CapabilityName.REQUIREMENT_ANALYSIS,
        CapabilityName.SYSTEM_ARCHITECTURE,
        CapabilityName.API_DESIGN,
        CapabilityName.DATABASE_DESIGN,
        CapabilityName.BACKEND_DEVELOPMENT,
        CapabilityName.TEST_WRITING,
    } <= caps
    assert u.expected_output == "technical_design"


def test_strategy_task_understanding():
    u = build(TASK_C).understanding
    assert u.domain == "business_strategy"
    caps = set(u.required_capabilities)
    assert {
        CapabilityName.STRATEGY_PLANNING,
        CapabilityName.CUSTOMER_RESEARCH,
        CapabilityName.FINANCIAL_ANALYSIS,
        CapabilityName.PROPOSAL_WRITING,
    } <= caps


def test_unknown_task_falls_back_to_planning():
    u = build("帮忙随便整理一下思路").understanding
    assert u.domain == "general"
    assert u.required_capabilities == [CapabilityName.TASK_PLANNING]


def test_discovery_is_deterministic_offline():
    first = build(TASK_B).understanding
    second = build(TASK_B).understanding
    assert first == second


# ---------------------------------------------------------------------------
# Dynamic decomposition
# ---------------------------------------------------------------------------


def test_plan_uses_structured_dependencies():
    plan = build(TASK_B)
    ids = {subtask.id for subtask in plan.subtasks}
    for subtask in plan.subtasks:
        assert set(subtask.dependencies) <= ids
        assert subtask.id not in subtask.dependencies
        assert subtask.expected_output
        assert subtask.required_capabilities


def test_plan_follows_stage_layering():
    plan = build(TASK_B)
    by_id = {subtask.id: subtask for subtask in plan.subtasks}
    research = next(s for s in plan.subtasks if s.id == "subtask_1")
    assert research.required_capabilities == [CapabilityName.REQUIREMENT_ANALYSIS]
    assert research.dependencies == []
    test_task = plan.subtasks[-1]
    assert test_task.required_capabilities == [CapabilityName.TEST_WRITING]
    assert by_id[test_task.dependencies[0]].required_capabilities == [
        CapabilityName.BACKEND_DEVELOPMENT
    ]


# ---------------------------------------------------------------------------
# Dynamic role allocation
# ---------------------------------------------------------------------------


def test_roles_merge_subtasks_by_capability():
    plan = build(TASK_B)
    backend = next(role for role in plan.roles if role.name == "Backend Developer")
    assert len(backend.assigned_subtasks) == 2
    assert {CapabilityName.API_DESIGN, CapabilityName.BACKEND_DEVELOPMENT} <= set(
        backend.capabilities
    )


def test_roles_cover_every_subtask_exactly_once():
    for task in (TASK_A, TASK_B, TASK_C):
        plan = build(task)
        assigned = [sid for role in plan.roles for sid in role.assigned_subtasks]
        assert sorted(assigned) == sorted(subtask.id for subtask in plan.subtasks)


# ---------------------------------------------------------------------------
# AgentFactory & ToolSelector
# ---------------------------------------------------------------------------


def test_agents_are_first_class_dynamic_specs():
    for agent in build(TASK_B).agents:
        assert isinstance(agent, DynamicAgentSpec)
        assert isinstance(agent, AgentSpec)  # scheduler-compatible
        assert agent.system_prompt
        assert agent.output_schema is TaskDeliverable
        assert "capability" in agent.metadata["reason"]


def test_agent_tools_come_from_registry():
    registry = ToolRegistry(mode="auto")
    plan = build(TASK_B)
    for agent in plan.agents:
        assert set(agent.tools) <= set(registry.available())
    assert "schema_validator" in plan.tools["database_engineer"]
    assert "code_analysis" in plan.tools["backend_developer"]
    market_plan = build(TASK_A)
    assert "web_search" in market_plan.tools["market_researcher"]


def test_tool_selector_maps_capabilities():
    selector = ToolSelector(ToolRegistry(mode="auto"))
    assert selector.select([CapabilityName.DATABASE_DESIGN]) == ["schema_validator"]
    assert selector.select([CapabilityName.DATA_ANALYSIS]) == ["data_analyzer", "calculator"]
    assert selector.select([CapabilityName.REPORT_WRITING]) == []


def test_tool_selector_filters_unregistered_tools():
    class LockedRegistry:
        def available(self):
            return ["mock_search"]

    selector = ToolSelector(LockedRegistry())  # type: ignore[arg-type]
    assert selector.select([CapabilityName.DATABASE_DESIGN, CapabilityName.DATA_ANALYSIS]) == []


# ---------------------------------------------------------------------------
# DependencyAnalyzer
# ---------------------------------------------------------------------------


def test_dependency_analysis_layers_and_order():
    plan = build(TASK_B)
    analysis = DependencyAnalyzer().analyze(
        DynamicPlan(subtasks=plan.subtasks), plan.roles
    )
    assert analysis.execution_layers[0] == ["requirement_analyst"]
    assert analysis.execution_layers[-1] == ["test_engineer"]
    # db → backend_dev edge forces database_engineer before backend_developer
    assert analysis.execution_layers[2] == ["database_engineer"]
    assert analysis.execution_layers[3] == ["backend_developer"]
    assert len(analysis.execution_layers) == 5
    assert set(analysis.topological_order) == {role.id for role in plan.roles}
    edge_pairs = {(edge.source, edge.target) for edge in analysis.agent_edges}
    assert ("system_architect", "database_engineer") in edge_pairs
    assert ("database_engineer", "backend_developer") in edge_pairs


def _manual_plan(deps_by_id: dict[str, list[str]]) -> DynamicPlan:
    return DynamicPlan(
        subtasks=[
            DynamicSubtask(
                id=subtask_id,
                title=subtask_id,
                required_capabilities=[CapabilityName.TASK_PLANNING],
                dependencies=deps,
            )
            for subtask_id, deps in deps_by_id.items()
        ]
    )


def test_cycle_detection_raises():
    plan = _manual_plan({"subtask_1": ["subtask_2"], "subtask_2": ["subtask_1"]})
    roles = DynamicRoleAllocator().allocate(plan)
    with pytest.raises(ValueError):
        DependencyAnalyzer().analyze(plan, roles)


def test_missing_dependency_raises():
    plan = _manual_plan({"subtask_1": ["ghost"]})
    roles = DynamicRoleAllocator().allocate(plan)
    with pytest.raises(ValueError):
        DependencyAnalyzer().analyze(plan, roles)


def test_self_dependency_raises():
    plan = _manual_plan({"subtask_1": ["subtask_1"]})
    roles = DynamicRoleAllocator().allocate(plan)
    with pytest.raises(ValueError):
        DependencyAnalyzer().analyze(plan, roles)


def test_isolated_agents_detected():
    plan = build("帮忙随便整理一下思路")  # single planning capability → single agent
    analysis = DependencyAnalyzer().analyze(
        DynamicPlan(subtasks=plan.subtasks), plan.roles
    )
    assert analysis.agent_edges == []
    assert analysis.isolated_agents == [plan.agents[0].id]


# ---------------------------------------------------------------------------
# ExecutionPlan & explanation
# ---------------------------------------------------------------------------


def test_execution_plan_is_consistent_and_valid():
    plan = build(TASK_B)
    assert [agent.id for agent in plan.agents] == plan.topology.agents
    assert plan.execution_layers == plan.topology.parallel_layers
    TopologyValidator().validate(plan.topology)  # must not raise
    assert set(plan.tools) == set(plan.topology.agents)


def test_explanation_is_structured_and_displayable():
    explanation = build(TASK_B).explanation
    assert explanation.reasoning
    assert len(explanation.agents) == 5
    for reason in explanation.agents:
        assert reason.reason.startswith("Created because the task requires")
        assert reason.capabilities
        assert len(reason.reason) < 400  # structured reason, not chain-of-thought


# ---------------------------------------------------------------------------
# Acceptance: three tasks → three different teams
# ---------------------------------------------------------------------------


def test_dynamic_team_multi_task_differentiation():
    plan_a, plan_b, plan_c = build(TASK_A), build(TASK_B), build(TASK_C)
    plans = (plan_a, plan_b, plan_c)

    name_sets = [frozenset(agent.role.name for agent in plan.agents) for plan in plans]
    cap_sets = [
        frozenset(c.value for c in plan.understanding.required_capabilities) for plan in plans
    ]
    shapes = [
        (tuple(tuple(layer) for layer in plan.execution_layers),
         tuple((edge.source, edge.target) for edge in plan.dependencies))
        for plan in plans
    ]
    assert name_sets[0] != name_sets[1]
    assert name_sets[1] != name_sets[2]
    assert name_sets[0] != name_sets[2]
    assert cap_sets[0] != cap_sets[1]
    assert cap_sets[1] != cap_sets[2]
    assert cap_sets[0] != cap_sets[2]
    assert shapes[0] != shapes[1]
    assert shapes[1] != shapes[2]

    for plan in plans:  # all AgentSpecs stay valid
        assert len({agent.id for agent in plan.agents}) == len(plan.agents)
        assert [agent.id for agent in plan.agents] == plan.topology.agents
        for agent in plan.agents:
            assert all(isinstance(c, CapabilityName) for c in agent.role.capabilities)


# ---------------------------------------------------------------------------
# Offline E2E (existing scheduler + existing runtime)
# ---------------------------------------------------------------------------


def test_offline_e2e_all_three_tasks():
    for task in (TASK_A, TASK_B, TASK_C):
        plan = build(task)
        results = asyncio.run(run_dynamic_team(plan))
        assert set(results) == set(plan.topology.agents)
        for result in results.values():
            assert result.status.value == "success"
            assert isinstance(result.output, TaskDeliverable)


def test_offline_e2e_deliverable_references_task():
    plan = build(TASK_B)
    results = asyncio.run(run_dynamic_team(plan))
    deliverable = next(iter(results.values())).output
    assert "FastAPI 电商后端" in deliverable.summary or "FastAPI" in deliverable.title


# ---------------------------------------------------------------------------
# Backward compatibility guards (v0.2.0 must keep working)
# ---------------------------------------------------------------------------


def test_v02_decomposer_still_works():
    plan = TaskDecomposer(None).decompose(Task(description="分析某市场"))
    assert isinstance(plan, SubtaskPlan)
    assert len(plan.subtasks) == 4


def test_registry_keeps_legacy_tools():
    available = ToolRegistry(mode="auto").available()
    assert "web_search" in available
    assert "mock_search" in available


def test_role_specs_have_ids_names_capabilities():
    for role in build(TASK_C).roles:
        assert role.id and role.name and role.capabilities


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def test_ui_dynamic_renders_initial_state():
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    repo_root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(repo_root / "app" / "ui_dynamic.py")).run(timeout=30)
    assert not at.exception
    assert any("Dynamic Team" in (item.value or "") for item in at.title)
    assert any("离线" in (item.value or "") for item in at.info)
