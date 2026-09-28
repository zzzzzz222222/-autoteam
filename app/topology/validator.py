import networkx as nx

from app.models.topology import Topology, TopologyMetrics


class TopologyValidationError(ValueError):
    """Raised when a candidate collaboration graph is invalid."""


class TopologyValidator:
    def build_graph(self, topology: Topology) -> nx.DiGraph:
        graph = nx.DiGraph()
        graph.add_nodes_from(topology.agents)
        graph.add_edges_from((edge.source, edge.target) for edge in topology.edges)
        return graph

    def validate(self, topology: Topology) -> None:
        if len(topology.agents) != len(set(topology.agents)):
            raise TopologyValidationError("Topology agents must be unique.")
        agent_set = set(topology.agents)
        for edge in topology.edges:
            if edge.source not in agent_set or edge.target not in agent_set:
                raise TopologyValidationError("Every edge endpoint must be included in agents.")
            if edge.source == edge.target:
                raise TopologyValidationError("Self-loop edges are not allowed.")
        if topology.root_agent is not None and topology.root_agent not in agent_set:
            raise TopologyValidationError("root_agent must be included in agents.")
        graph = self.build_graph(topology)
        if not nx.is_directed_acyclic_graph(graph):
            raise TopologyValidationError("Topology must be a directed acyclic graph (DAG).")
        if topology.root_agent is not None:
            reachable = nx.descendants(graph, topology.root_agent) | {topology.root_agent}
            if reachable != agent_set:
                raise TopologyValidationError("All agents must be reachable from root_agent.")


def compute_parallel_layers(graph: nx.DiGraph) -> list[list[str]]:
    if not nx.is_directed_acyclic_graph(graph):
        raise TopologyValidationError("Parallel layers can only be computed for a DAG.")
    layers: list[list[str]] = []
    remaining = set(graph.nodes)
    completed: set[str] = set()
    order = list(graph.nodes)
    while remaining:
        layer = [
            node
            for node in order
            if node in remaining and set(graph.predecessors(node)) <= completed
        ]
        if not layer:
            raise TopologyValidationError("Could not derive parallel layers from graph.")
        layers.append(layer)
        completed.update(layer)
        remaining.difference_update(layer)
    return layers


def calculate_metrics(topology: Topology) -> TopologyMetrics:
    layers = topology.parallel_layers
    if not layers:
        layers = compute_parallel_layers(TopologyValidator().build_graph(topology))
    agent_count = len(topology.agents)
    max_parallel = max((len(layer) for layer in layers), default=0)
    return TopologyMetrics(
        agent_count=agent_count,
        edge_count=len(topology.edges),
        step_count=len(layers),
        parallelism=max_parallel / agent_count if agent_count else 0.0,
    )
