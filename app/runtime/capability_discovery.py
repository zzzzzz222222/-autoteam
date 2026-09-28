"""Capability Discovery (v0.3.0).

Turns a raw task into a validated ``TaskUnderstanding``: domain, objective,
expected output and the capability set the task requires.

Offline (no real provider): deterministic keyword rules + per-domain capability
augmentation. A real LLM may refine the reading, but every proposed capability
is validated against the capability vocabulary — invalid proposals fall back to
the deterministic rules. The LLM never modifies the DAG and never executes code.
"""

from __future__ import annotations

from app.llm.provider import LLMProvider, OpenAILLMProvider
from app.models.capability import CapabilityName
from app.models.task import ComplexityLevel, Task
from app.runtime.understanding import TaskUnderstanding

# Ordered: the first matching domain wins. Software before strategy before
# market, so "设计一个 FastAPI 后端" is not read as market research.
_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "software_engineering",
        (
            "fastapi", "后端", "backend", "数据库", "database", "架构",
            "architecture", "api", "系统设计", "系统", "服务端",
        ),
    ),
    (
        "business_strategy",
        ("策略", "战略", "strategy", "进入", "go-to-market", "gtm"),
    ),
    (
        "market_research",
        ("市场", "行业", "竞争", "market", "industry", "competitor"),
    ),
)

_CAPABILITY_KEYWORDS: dict[CapabilityName, tuple[str, ...]] = {
    CapabilityName.MARKET_RESEARCH: ("市场", "行业", "market", "industry"),
    CapabilityName.COMPETITOR_ANALYSIS: ("竞争", "竞品", "对手", "competitor", "competitive"),
    CapabilityName.TECHNOLOGY_ANALYSIS: ("技术", "ai", "人工智能", "technology", "tech"),
    CapabilityName.DATA_ANALYSIS: ("数据", "分析", "data", "analysis", "analyze"),
    CapabilityName.REQUIREMENT_ANALYSIS: ("需求", "requirement", "设计", "design"),
    CapabilityName.SYSTEM_ARCHITECTURE: (
        "架构", "architecture", "系统", "system", "fastapi", "后端", "backend",
    ),
    CapabilityName.API_DESIGN: ("api", "接口", "fastapi", "rest"),
    CapabilityName.DATABASE_DESIGN: ("数据库", "database", "存储", "schema"),
    CapabilityName.BACKEND_DEVELOPMENT: (
        "后端", "开发", "实现", "backend", "implement", "development",
    ),
    CapabilityName.TEST_WRITING: ("测试", "test"),
    CapabilityName.CUSTOMER_RESEARCH: ("客户", "用户", "customer", "user"),
    CapabilityName.STRATEGY_PLANNING: ("策略", "战略", "进入", "strategy", "go-to-market", "gtm"),
    CapabilityName.FINANCIAL_ANALYSIS: (
        "财务", "收入", "成本", "估值", "financial", "pricing", "revenue",
    ),
    CapabilityName.PROPOSAL_WRITING: ("方案", "提案", "计划书", "proposal"),
}

# Deterministic domain augmentation: a task of this domain always needs these
# supporting capabilities, even when no keyword matches them directly.
_DOMAIN_AUGMENT: dict[str, tuple[CapabilityName, ...]] = {
    "software_engineering": (CapabilityName.DATABASE_DESIGN, CapabilityName.TEST_WRITING),
    "business_strategy": (
        CapabilityName.CUSTOMER_RESEARCH,
        CapabilityName.FINANCIAL_ANALYSIS,
        CapabilityName.PROPOSAL_WRITING,
    ),
    "market_research": (CapabilityName.REPORT_WRITING,),
}

_DOMAIN_PROFILE: dict[str, tuple[str, str]] = {
    "software_engineering": ("design_and_implement_backend", "technical_design"),
    "business_strategy": ("market_entry_strategy", "strategy_proposal"),
    "market_research": ("market_analysis", "research_report"),
    "general": ("complete_task", "structured_deliverable"),
}

_LLM_PROMPT = (
    "Read the task and return JSON matching TaskUnderstanding: domain, "
    "objective, constraints (list), expected_output, required_capabilities "
    "(only values from the capability vocabulary) and complexity "
    "(low/medium/high).\n\nTASK: {task}"
)


class CapabilityDiscovery:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    def discover(self, task: Task) -> TaskUnderstanding:
        baseline = self._rule_based(task)
        if not isinstance(self.provider, OpenAILLMProvider):
            return baseline
        try:
            refined = self.provider.structured_completion(
                _LLM_PROMPT.format(task=task.description), TaskUnderstanding
            )
        except Exception:
            return baseline
        if not refined.required_capabilities:
            return baseline
        # Code validates: keep the refined reading only when the LLM proposed
        # a non-empty capability set; the schema already rejected unknown values.
        return refined.model_copy(update={"task": task.description})

    def _rule_based(self, task: Task) -> TaskUnderstanding:
        text = " ".join(
            part for part in (task.description, task.context) if part
        ).lower()
        domain = next(
            (name for name, keywords in _DOMAIN_RULES if any(k in text for k in keywords)),
            "general",
        )
        capabilities = [
            capability
            for capability, keywords in _CAPABILITY_KEYWORDS.items()
            if any(keyword in text for keyword in keywords)
        ]
        for extra in _DOMAIN_AUGMENT.get(domain, ()):
            if extra not in capabilities:
                capabilities.append(extra)
        if not capabilities:
            capabilities = [CapabilityName.TASK_PLANNING]
        complexity = (
            ComplexityLevel.LOW
            if len(capabilities) <= 2
            else ComplexityLevel.MEDIUM
            if len(capabilities) <= 4
            else ComplexityLevel.HIGH
        )
        objective, expected_output = _DOMAIN_PROFILE[domain]
        return TaskUnderstanding(
            task=task.description,
            domain=domain,
            objective=objective,
            expected_output=expected_output,
            required_capabilities=capabilities,
            complexity=complexity,
        )
