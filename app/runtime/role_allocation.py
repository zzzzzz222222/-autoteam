"""Dynamic role allocation (v0.3.0).

Groups decomposed subtasks into roles. One role may own several subtasks —
subtasks whose primary capability maps to the same role name are merged, so the
team size follows the task instead of the subtask count.

Capability ≠ Role ≠ Agent is preserved: roles carry the union of their
subtasks' capabilities; agents are created from roles by the AgentFactory.
"""

from __future__ import annotations

import re

from app.models.capability import CapabilityName
from app.runtime.dynamic_models import DynamicPlan, RoleSpec

ROLE_BY_CAPABILITY: dict[CapabilityName, str] = {
    CapabilityName.MARKET_RESEARCH: "Market Researcher",
    CapabilityName.COMPETITOR_ANALYSIS: "Competitor Analyst",
    CapabilityName.TECHNOLOGY_ANALYSIS: "Technology Analyst",
    CapabilityName.DATA_ANALYSIS: "Data Analyst",
    CapabilityName.FINANCIAL_ANALYSIS: "Financial Analyst",
    CapabilityName.FACT_CHECKING: "Fact Checker",
    CapabilityName.REPORT_WRITING: "Report Writer",
    CapabilityName.PROPOSAL_WRITING: "Proposal Writer",
    CapabilityName.REQUIREMENT_ANALYSIS: "Requirement Analyst",
    CapabilityName.SYSTEM_ARCHITECTURE: "System Architect",
    CapabilityName.API_DESIGN: "Backend Developer",
    CapabilityName.BACKEND_DEVELOPMENT: "Backend Developer",
    CapabilityName.DATABASE_DESIGN: "Database Engineer",
    CapabilityName.TEST_WRITING: "Test Engineer",
    CapabilityName.CUSTOMER_RESEARCH: "Customer Researcher",
    CapabilityName.STRATEGY_PLANNING: "Strategy Planner",
    CapabilityName.PRODUCT_DESIGN: "Product Designer",
    CapabilityName.RISK_ANALYSIS: "Risk Analyst",
    CapabilityName.CODE_GENERATION: "Developer",
    CapabilityName.CODE_REVIEW: "Code Reviewer",
    CapabilityName.TASK_PLANNING: "Task Planner",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class DynamicRoleAllocator:
    def allocate(self, plan: DynamicPlan) -> list[RoleSpec]:
        roles: dict[str, RoleSpec] = {}
        order: list[str] = []
        for subtask in plan.subtasks:
            primary = (
                subtask.required_capabilities[0]
                if subtask.required_capabilities
                else CapabilityName.TASK_PLANNING
            )
            role_name = ROLE_BY_CAPABILITY.get(primary, "General Specialist")
            if role_name not in roles:
                roles[role_name] = RoleSpec(
                    id=_slug(role_name),
                    name=role_name,
                    description="",
                    capabilities=[],
                    assigned_subtasks=[],
                )
                order.append(role_name)
            role = roles[role_name]
            for capability in subtask.required_capabilities:
                if capability not in role.capabilities:
                    role.capabilities.append(capability)
            role.assigned_subtasks.append(subtask.id)
        for role in roles.values():
            caps = ", ".join(capability.value for capability in role.capabilities)
            role.description = f"Covers {caps} across {len(role.assigned_subtasks)} subtask(s)."
        return [roles[name] for name in order]
