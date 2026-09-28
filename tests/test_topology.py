import pytest
from pydantic import ValidationError

from app.models.topology import Topology, TopologyEdge, TopologyProposal, TopologyType
from app.topology.templates import build_chain, build_hierarchical, build_star
from app.topology.validator import TopologyValidator


def edge_pairs(proposal: TopologyProposal) -> list[tuple[str, str]]:
    return [(edge.source, edge.target) for edge in proposal.edges]


def as_topology(agents: list[str], proposal: TopologyProposal) -> Topology:
    return Topology(
        type=proposal.topology_type,
        agents=agents,
        edges=proposal.edges,
        root_agent=proposal.root_agent,
    )


def test_chain_edges_follow_input_order() -> None:
    assert edge_pairs(build_chain(["A", "B", "C", "D"])) == [("A", "B"), ("B", "C"), ("C", "D")]


def test_star_edges_start_at_root() -> None:
    assert edge_pairs(build_star(["A", "B", "C", "D"])) == [("A", "B"), ("A", "C"), ("A", "D")]


def test_hierarchical_is_acyclic() -> None:
    agents = ["A", "B", "C", "D", "E", "F"]
    TopologyValidator().validate(as_topology(agents, build_hierarchical(agents)))


@pytest.mark.parametrize("agents", [["A"], ["A", "B"]])
def test_templates_handle_small_teams(agents: list[str]) -> None:
    validator = TopologyValidator()
    for builder in (build_chain, build_star, build_hierarchical):
        validator.validate(as_topology(agents, builder(agents)))


def test_topology_rejects_duplicate_agents() -> None:
    with pytest.raises(ValidationError):
        Topology(type=TopologyType.CHAIN, agents=["A", "A"], edges=[])


def test_topology_rejects_unknown_edge_agent() -> None:
    with pytest.raises(ValidationError):
        Topology(
            type=TopologyType.CHAIN, agents=["A", "B"], edges=[TopologyEdge(source="A", target="X")]
        )
