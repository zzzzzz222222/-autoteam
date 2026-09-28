from app.models.topology import TopologyEdge, TopologyProposal, TopologyType


def build_chain(agents: list[str]) -> TopologyProposal:
    return TopologyProposal(
        topology_type=TopologyType.CHAIN,
        edges=[
            TopologyEdge(source=source, target=target) for source, target in zip(agents, agents[1:])
        ],
        root_agent=agents[0] if agents else None,
        reasoning="按输入 Agent 顺序串行协作。",
    )


def build_star(agents: list[str]) -> TopologyProposal:
    root = agents[0] if agents else None
    return TopologyProposal(
        topology_type=TopologyType.STAR,
        edges=[TopologyEdge(source=root, target=agent) for agent in agents[1:]] if root else [],
        root_agent=root,
        reasoning="首个 Agent 作为中心节点并分发工作。",
    )


def build_hierarchical(agents: list[str]) -> TopologyProposal:
    if not agents:
        return TopologyProposal(topology_type=TopologyType.HIERARCHICAL, edges=[])
    root = agents[0]
    second_level = agents[1:3]
    edges = [TopologyEdge(source=root, target=agent) for agent in second_level]
    for index, agent in enumerate(agents[3:]):
        parent = second_level[index % len(second_level)] if second_level else root
        edges.append(TopologyEdge(source=parent, target=agent))
    return TopologyProposal(
        topology_type=TopologyType.HIERARCHICAL,
        edges=edges,
        root_agent=root,
        reasoning="首个 Agent 为根，后续 Agent 按两层分支挂载。",
    )
