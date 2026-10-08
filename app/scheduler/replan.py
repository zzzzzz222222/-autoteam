from pydantic import BaseModel, Field

from app.models.topology import Topology
from app.scheduler.models import AgentResult


class ReplanResult(BaseModel):
    replanned: bool
    reason: str
    topology: Topology | None = None
    skipped_agents: list[str] = Field(default_factory=list)


def topology_signature(topology: Topology) -> str:
    """Stable one-line description of a plan, used to detect an effective change.

    Two plans with the same signature are the same plan: agents, root and edges
    all match. Comparing signatures is what separates "the Replanner ran" from
    "the Replanner actually changed something".
    """
    edges = ",".join(f"{edge.source}->{edge.target}" for edge in topology.edges)
    agents = ",".join(topology.agents)
    root = topology.root_agent or "-"
    return f"agents={agents};root={root};edges={edges or '-'}"


class ReplanEvent(BaseModel):
    failed_agent_id: str
    reason: str
    previous_topology: str | None = None
    new_topology: str | None = None
    # v0.6.2 (AT-AUDIT-003): the single source of truth for "a replan happened".
    #
    # ``False`` means the Replanner ran but no plan change reached the scheduler
    # (no-op, an equivalent candidate, an invalid candidate, or a change this
    # scheduler cannot safely apply). Callers must not report such an outcome as
    # a successful replan.
    applied: bool = False
    # Why a candidate was not applied. Empty when ``applied`` is True, so a
    # refusal is never silently dropped.
    detail: str = ""


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
