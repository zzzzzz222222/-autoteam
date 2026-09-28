import pytest
from pydantic import ValidationError

from app.models.topology import Topology, TopologyEdge, TopologyType
from app.topology.validator import (
    TopologyValidationError,
    TopologyValidator,
    compute_parallel_layers,
)


def topology(agents: list[str], edges: list[tuple[str, str]], root: str | None = None) -> Topology:
    return Topology(
        type=TopologyType.CHAIN,
        agents=agents,
        edges=[TopologyEdge(source=source, target=target) for source, target in edges],
        root_agent=root,
    )


def test_valid_dag_passes() -> None:
    TopologyValidator().validate(topology(["A", "B", "C"], [("A", "B"), ("B", "C")], "A"))


def test_cycle_fails() -> None:
    candidate = topology(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
    with pytest.raises(TopologyValidationError, match="DAG"):
        TopologyValidator().validate(candidate)


def test_self_loop_fails() -> None:
    with pytest.raises(ValidationError, match="Self-loop"):
        topology(["A"], [("A", "A")])


def test_unknown_agent_fails() -> None:
    with pytest.raises(ValidationError, match="endpoint"):
        topology(["A"], [("A", "X")])


def test_missing_root_fails() -> None:
    with pytest.raises(ValidationError, match="root_agent"):
        topology(["A"], [], "X")


def test_parallel_layers_are_stable() -> None:
    candidate = topology(
        ["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")], "A"
    )
    assert compute_parallel_layers(TopologyValidator().build_graph(candidate)) == [
        ["A"],
        ["B", "C"],
        ["D"],
    ]
