import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.allocator.role_allocator import RoleAllocator
from app.analyzer.task_analyzer import TaskAnalyzer
from app.models.task import Task
from app.topology.generator import TopologyGenerator
from app.topology.validator import calculate_metrics
from main import configure_utf8_output


def render_layers(layers: list[list[str]], labels: dict[str, str]) -> str:
    return "\n".join("  ↓  ".join(labels[agent_id] for agent_id in layer) for layer in layers)


def main() -> None:
    configure_utf8_output()
    task = Task(description="分析新能源汽车行业竞争格局并生成投资报告")
    analysis = TaskAnalyzer().analyze(task)
    agents = RoleAllocator().allocate(analysis)
    labels = {agent.id: agent.role.name for agent in agents if agent.id is not None}
    candidates = TopologyGenerator().generate_candidates(task, agents)
    print("=" * 50)
    print("AutoTeam — Day 2 Dynamic Topology Generation")
    print("=" * 50)
    print(f"Task: {task.description}\nAgents:")
    for agent in agents:
        print(f"- {agent.role.name}")
    for index, candidate in enumerate(candidates, start=1):
        metrics = calculate_metrics(candidate)
        print("-" * 50)
        print(f"Candidate {index}: {candidate.type.value.upper()}")
        print("-" * 50)
        print(render_layers(candidate.parallel_layers, labels))
        print(f"Agents: {metrics.agent_count}")
        print(f"Edges: {metrics.edge_count}")
        print(f"Steps: {metrics.step_count}")
        print(f"Parallelism: {metrics.parallelism:.2f}")
    print("=" * 50)


if __name__ == "__main__":
    main()
