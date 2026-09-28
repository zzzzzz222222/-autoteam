import logging

from app.models.agent import AgentSpec
from app.models.task import Task
from app.models.topology import Topology, TopologyProposal
from app.topology.templates import build_chain, build_hierarchical, build_star
from app.topology.validator import TopologyValidator, compute_parallel_layers

logger = logging.getLogger(__name__)


class TopologyGenerator:
    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client
        self.validator = TopologyValidator()

    def generate_candidates(self, task: Task, agents: list[AgentSpec]) -> list[Topology]:
        del task  # Reserved for optional template parameterization by an LLM.
        agent_ids = [agent.id for agent in agents]
        if any(agent_id is None for agent_id in agent_ids):
            raise ValueError("Every AgentSpec must have an identifier.")
        names = [agent_id for agent_id in agent_ids if agent_id is not None]
        proposals = [build_chain(names), build_star(names), build_hierarchical(names)]
        candidates: list[Topology] = []
        for proposal in proposals:
            try:
                candidates.append(self._validate_proposal(names, proposal))
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Discarding invalid %s topology: %s", proposal.topology_type.value, exc
                )
        return candidates

    def _validate_proposal(self, agents: list[str], proposal: TopologyProposal) -> Topology:
        topology = Topology(
            type=proposal.topology_type,
            agents=agents,
            edges=proposal.edges,
            root_agent=proposal.root_agent,
        )
        self.validator.validate(topology)
        topology.parallel_layers = compute_parallel_layers(self.validator.build_graph(topology))
        return topology
