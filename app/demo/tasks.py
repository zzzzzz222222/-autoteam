"""Ready-to-run demo tasks shown by the UI and the terminal demos."""

from typing import NamedTuple


class DemoTask(NamedTuple):
    """A preset task: a short label, a category, and the task description."""

    label: str
    category: str
    description: str


DEFAULT_TASK_DESCRIPTION = "Create a market research report for a new AI product."

DEMO_TASKS: tuple[DemoTask, ...] = (
    DemoTask("Market Research", "Research", DEFAULT_TASK_DESCRIPTION),
    DemoTask(
        "Deep Market Study",
        "Research",
        "Research the AI agent market, analyze competitors and pricing, "
        "and write a market report.",
    ),
    DemoTask(
        "Competitor Research",
        "Research",
        "Research the AI agent market and produce a competitor analysis.",
    ),
    DemoTask(
        "Document Search Service",
        "Coding",
        "Build a Python service that processes uploaded documents and exposes a search API.",
    ),
    DemoTask(
        "SaaS Launch Plan",
        "Planning",
        "Create a launch plan for a new AI SaaS product.",
    ),
)


def demo_task_labels() -> list[str]:
    return [task.label for task in DEMO_TASKS]


def find_demo_task(label: str) -> DemoTask | None:
    """Return the preset with this label, or ``None`` for the custom entry."""
    for task in DEMO_TASKS:
        if task.label == label:
            return task
    return None
