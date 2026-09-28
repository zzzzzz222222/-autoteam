from enum import Enum

from pydantic import BaseModel, Field, model_validator


class TopologyType(str, Enum):
    CHAIN = "chain"
    STAR = "star"
    HIERARCHICAL = "hierarchical"


class TopologyEdge(BaseModel):
    source: str
    target: str


class TopologyProposal(BaseModel):
    topology_type: TopologyType
    edges: list[TopologyEdge]
    root_agent: str | None = None
    reasoning: str = ""


class Topology(BaseModel):
    type: TopologyType
    agents: list[str]
    edges: list[TopologyEdge]
    root_agent: str | None = None
    parallel_layers: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "Topology":
        if len(self.agents) != len(set(self.agents)):
            raise ValueError("Topology agents must be unique.")
        agent_set = set(self.agents)
        if self.root_agent is not None and self.root_agent not in agent_set:
            raise ValueError("root_agent must be included in agents.")
        for edge in self.edges:
            if edge.source not in agent_set or edge.target not in agent_set:
                raise ValueError("Every edge endpoint must be included in agents.")
            if edge.source == edge.target:
                raise ValueError("Self-loop edges are not allowed.")
        return self


class TopologyMetrics(BaseModel):
    agent_count: int
    edge_count: int
    step_count: int
    parallelism: float
