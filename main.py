import sys

from app.allocator.role_allocator import RoleAllocator
from app.analyzer.task_analyzer import TaskAnalyzer
from app.models.task import Task


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def format_result(description: str) -> str:
    analysis = TaskAnalyzer().analyze(Task(description=description))
    agents = RoleAllocator().allocate(analysis)
    lines = [
        "=" * 50,
        "AutoTeam — Day 1",
        "=" * 50,
        "",
        "Task:",
        description,
        "",
        "[Task Analysis]",
        "",
        f"Complexity: {analysis.complexity.value.upper()}",
        f"Confidence: {analysis.confidence:.2f}",
        "Reasoning:",
        analysis.reasoning,
        "",
        "Required Capabilities:",
    ]
    lines.extend(f"  - {capability.value}" for capability in analysis.required_capabilities)
    lines.extend(["", "[Allocated Team]", ""])
    for index, agent in enumerate(agents, start=1):
        lines.extend(
            [
                f"{index}. {agent.role.name}",
                "   Capabilities: " + ", ".join(item.value for item in agent.role.capabilities),
                f"   Goal: {agent.role.goal}",
                "   Tools: " + (", ".join(agent.tools) or "none"),
                "",
            ]
        )
    lines.extend([f"Total Agents: {len(agents)}", "", "=" * 50])
    return "\n".join(lines)


def main() -> None:
    configure_utf8_output()
    if len(sys.argv) < 2:
        print('Usage:\npython main.py "<task description>"')
        return
    print(format_result(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
