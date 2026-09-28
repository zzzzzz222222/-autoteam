"""Dependency analysis (v0.3.0).

Answers "who should depend on whom" — nothing more. It validates the subtask
dependency graph (missing / self / cyclic references), lifts it onto agents via
the role assignment, computes execution layers with the *existing*
``compute_parallel_layers`` and a stable topological order. Execution itself
stays in the existing scheduler.
"""

from __future__ import annotations

import networkx as nx

from app.runtime.dynamic_models import DependencyAnalysis, DependencyEdge, DynamicPlan, RoleSpec
from app.topology.validator import compute_parallel_layers


class DependencyAnalyzer:
    def analyze(self, plan: DynamicPlan, roles: list[RoleSpec]) -> DependencyAnalysis:
        self._validate_subtask_dependencies(plan)

        role_of = {
            subtask_id: role.id
            for role in roles
            for subtask_id in role.assigned_subtasks
        }
        unassigned = [subtask.id for subtask in plan.subtasks if subtask.id not in role_of]
        if unassigned:
            raise ValueError(f"Subtasks without an assigned role: {unassigned}")

        agent_ids = [role.id for role in roles]
        edges: list[DependencyEdge] = []
        seen: set[tuple[str, str]] = set()
        title_of = {subtask.id: subtask.title for subtask in plan.subtasks}
        for subtask in plan.subtasks:
            target_agent = role_of[subtask.id]
            for dep in subtask.dependencies:
                source_agent = role_of[dep]
                if source_agent == target_agent or (source_agent, target_agent) in seen:
                    continue
                seen.add((source_agent, target_agent))
                edges.append(
                    DependencyEdge(
                        source=source_agent,
                        target=target_agent,
                        reason=f"{title_of[subtask.id]} depends on {title_of[dep]}",
                    )
                )

        graph = nx.DiGraph()
        graph.add_nodes_from(agent_ids)
        graph.add_edges_from((edge.source, edge.target) for edge in edges)
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("Agent dependency graph contains a cycle.")
        layers = compute_parallel_layers(graph)
        isolated = [agent_id for agent_id in agent_ids if graph.degree(agent_id) == 0]
        return DependencyAnalysis(
            agent_edges=edges,
            execution_layers=layers,
            topological_order=list(nx.topological_sort(graph)),
            isolated_agents=isolated,
        )

    @staticmethod
    def _validate_subtask_dependencies(plan: DynamicPlan) -> None:
        ids = [subtask.id for subtask in plan.subtasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Subtask ids must be unique.")
        id_set = set(ids)
        for subtask in plan.subtasks:
            if subtask.id in subtask.dependencies:
                raise ValueError(f"Subtask {subtask.id} depends on itself.")
            missing = [dep for dep in subtask.dependencies if dep not in id_set]
            if missing:
                raise ValueError(f"Subtask {subtask.id} has missing dependencies: {missing}")
        graph = nx.DiGraph()
        graph.add_nodes_from(ids)
        graph.add_edges_from(
            (dep, subtask.id) for subtask in plan.subtasks for dep in subtask.dependencies
        )
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("Subtask dependencies contain a cycle.")
