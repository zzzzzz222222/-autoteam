"""DynamicAgentFactory (v0.3.0).

Turns a ``RoleSpec`` into a first-class ``DynamicAgentSpec``: system prompt,
tools (via the ToolSelector), input/output schemas and a structured reason for
why the agent exists. The factory only *describes* agents — execution stays in
the existing ``AgentRuntime``.
"""

from __future__ import annotations

from app.models.agent import AgentRole
from app.runtime.artifacts import artifact_type_for
from app.runtime.dynamic_models import DynamicAgentSpec, DynamicPlan, RoleSpec
from app.runtime.models import TaskDeliverable
from app.runtime.tool_selector import ToolSelector
from app.runtime.understanding import TaskUnderstanding


def _slug(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class DynamicAgentFactory:
    def __init__(self, tool_selector: ToolSelector | None = None) -> None:
        self.tool_selector = tool_selector or ToolSelector()

    def create(
        self,
        role: RoleSpec,
        plan: DynamicPlan,
        understanding: TaskUnderstanding,
    ) -> DynamicAgentSpec:
        tools = self.tool_selector.select(role.capabilities)
        titles_by_id = {subtask.id: subtask.title for subtask in plan.subtasks}
        outputs_by_id = {subtask.id: subtask.expected_output for subtask in plan.subtasks}
        goal = "; ".join(
            titles_by_id.get(subtask_id, subtask_id) for subtask_id in role.assigned_subtasks
        )
        caps = ", ".join(capability.value for capability in role.capabilities)
        expected_outputs = [
            outputs_by_id[sid] for sid in role.assigned_subtasks if outputs_by_id.get(sid)
        ]
        # A merged role's artifact is typed by its most advanced subtask
        # (e.g. Backend Developer -> backend_implementation, not api_specification).
        expected_output = expected_outputs[-1] if expected_outputs else ""
        system_prompt = (
            f"You are {role.name}, a specialist agent in the {understanding.domain} domain. "
            f"Your capabilities: {caps}. Your goal: {goal or 'complete the assigned work'}. "
            "Read the task, use the upstream results if any, and return a structured "
            "deliverable — never modify plans, graphs or code."
        )
        return DynamicAgentSpec(
            id=role.id or _slug(role.name),
            role=AgentRole(
                name=role.name,
                capabilities=list(role.capabilities),
                goal=goal or f"cover {caps}",
                backstory=f"Created dynamically for the task: {understanding.task}",
            ),
            tools=tools,
            max_iterations=1,
            system_prompt=system_prompt,
            input_schema="task_context_and_upstream_results",
            output_schema=TaskDeliverable,
            metadata={
                "assigned_subtasks": list(role.assigned_subtasks),
                "subtask_titles": [
                    titles_by_id.get(sid, sid) for sid in role.assigned_subtasks
                ],
                "expected_output": expected_output,
                "expected_outputs": expected_outputs,
                "output_type": artifact_type_for(expected_output).value,
                "reason": f"Task requires {caps} capability.",
                "domain": understanding.domain,
            },
        )
