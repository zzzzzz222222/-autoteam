"""Ready-to-run demo tasks shown by the UI and the terminal demos.

Each preset carries an English and a Chinese description. Both variants are
verified to allocate the same number of agents and the same topology metrics,
so switching the UI language never changes the demo outcome.
"""

from typing import NamedTuple

CUSTOM = "custom"

DEFAULT_TASK_DESCRIPTION = "Create a market research report for a new AI product."
DEFAULT_TASK_DESCRIPTION_ZH = "为一款新的 AI 产品撰写市场研究报告。"


class DemoTask(NamedTuple):
    """A preset task: a stable key, bilingual labels and bilingual descriptions."""

    label: str
    label_zh: str
    category: str
    description: str
    description_zh: str


DEMO_TASKS: tuple[DemoTask, ...] = (
    DemoTask(
        "Market Research",
        "市场研究",
        "Research",
        DEFAULT_TASK_DESCRIPTION,
        DEFAULT_TASK_DESCRIPTION_ZH,
    ),
    DemoTask(
        "Deep Market Study",
        "深度市场研究",
        "Research",
        "Research the AI agent market, analyze competitors and pricing, "
        "and write a market report.",
        "研究 AI Agent 市场，分析竞争对手与财务数据，并撰写市场报告。",
    ),
    DemoTask(
        "Competitor Research",
        "竞品研究",
        "Research",
        "Research the AI agent market, analyze competitors, and write a competitor report.",
        "研究 AI Agent 市场，进行数据分析，并产出竞争对手分析报告。",
    ),
    DemoTask(
        "Document Search Service",
        "文档检索服务",
        "Coding",
        "Build a Python service that processes uploaded documents and exposes a search API.",
        "构建一个 Python 服务，处理上传的文档并对外提供搜索接口。",
    ),
    DemoTask(
        "SaaS Launch Plan",
        "SaaS 上线计划",
        "Planning",
        "Create a launch plan for a new AI SaaS product.",
        "为一款新的 AI SaaS 产品制定上线计划。",
    ),
)


def find_demo_task(label: str) -> DemoTask | None:
    """Look a preset up by its English key or its Chinese label."""
    for task in DEMO_TASKS:
        if label in (task.label, task.label_zh):
            return task
    return None


def localized_labels(locale: str) -> list[str]:
    """Preset labels in the given language, used directly as radio options."""
    return [task.label_zh if locale == "zh" else task.label for task in DEMO_TASKS]


def localized_label(task: DemoTask, locale: str) -> str:
    return task.label_zh if locale == "zh" else task.label


def localized_description(task: DemoTask, locale: str) -> str:
    return task.description_zh if locale == "zh" else task.description


def default_task_description(locale: str) -> str:
    return DEFAULT_TASK_DESCRIPTION_ZH if locale == "zh" else DEFAULT_TASK_DESCRIPTION
