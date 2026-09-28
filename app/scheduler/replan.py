from pydantic import BaseModel, Field

from app.models.topology import Topology
from app.scheduler.models import AgentResult


class ReplanResult(BaseModel):
    replanned: bool
    reason: str
    topology: Topology | None = None
    skipped_agents: list[str] = Field(default_factory=list)


class ReplanEvent(BaseModel):
    failed_agent_id: str
    reason: str
    previous_topology: str | None = None
    new_topology: str | None = None


class Replanner:
    """Deterministic recovery: mark every descendant of a failed node unavailable."""

    def replan(
        self, topology: Topology, failed_agent_id: str, results: dict[str, AgentResult]
    ) -> ReplanResult:
        del results
        graph = {agent_id: [] for agent_id in topology.agents}
        for edge in topology.edges:
            graph[edge.source].append(edge.target)
        pending, skipped = list(graph[failed_agent_id]), set()
        while pending:
            node = pending.pop(0)
            if node not in skipped:
                skipped.add(node)
                pending.extend(graph[node])
        return ReplanResult(
            replanned=False,
            reason="no viable recovery plan",
            skipped_agents=[agent_id for agent_id in topology.agents if agent_id in skipped],
        )
