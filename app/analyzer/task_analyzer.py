from collections.abc import Mapping

from app.models.capability import CapabilityName
from app.models.task import ComplexityLevel, Task, TaskAnalysis

KEYWORDS: Mapping[CapabilityName, tuple[str, ...]] = {
    CapabilityName.MARKET_RESEARCH: (
        "行业",
        "市场",
        "趋势",
        "市场规模",
        "行业分析",
        "market",
        "industry",
        "trend",
    ),
    CapabilityName.COMPETITOR_ANALYSIS: (
        "竞争",
        "竞争对手",
        "对手",
        "竞品",
        "竞品分析",
        "competitor",
        "competitive",
    ),
    CapabilityName.FINANCIAL_ANALYSIS: (
        "财务",
        "财报",
        "估值",
        "收入",
        "利润",
        "成本",
        "financial",
        "revenue",
        "valuation",
        "pricing",
    ),
    CapabilityName.FACT_CHECKING: (
        "事实",
        "核实",
        "验证",
        "事实核查",
        "fact check",
        "fact-check",
        "verify",
    ),
    CapabilityName.REPORT_WRITING: (
        "报告",
        "研究报告",
        "总结",
        "写作",
        "report",
        "writing",
        "write",
    ),
    CapabilityName.CODE_GENERATION: (
        "代码",
        "开发",
        "实现",
        "编程",
        "接口",
        "fastapi",
        "python",
        "code",
        "coding",
        "implement",
        "build",
        "service",
    ),
    CapabilityName.CODE_REVIEW: ("审查", "代码审查", "review", "代码质量", "code review"),
    CapabilityName.TEST_WRITING: (
        "测试",
        "单元测试",
        "集成测试",
        "pytest",
        "tests",
        "unit test",
        "test writing",
    ),
    CapabilityName.TASK_PLANNING: (
        "计划",
        "规划",
        "执行计划",
        "任务拆解",
        "plan",
        "planning",
        "roadmap",
    ),
    CapabilityName.RISK_ANALYSIS: ("风险", "风险分析", "风险评估", "risk"),
    CapabilityName.DATA_ANALYSIS: (
        "数据",
        "数据分析",
        "统计",
        "data",
        "analysis",
        "analytics",
        "analyze",
    ),
    CapabilityName.PRODUCT_DESIGN: (
        "产品",
        "产品设计",
        "需求",
        "功能设计",
        "product",
        "design",
        "requirement",
    ),
}


class TaskAnalyzer:
    def __init__(self, llm_client: object | None = None) -> None:
        self.llm_client = llm_client

    def analyze(self, task: Task) -> TaskAnalysis:
        if self.llm_client is not None:
            try:
                prompt = (
                    "Analyze this task and return JSON matching TaskAnalysis. "
                    f"Task: {task.description}\nContext: {task.context or ''}"
                )
                result = self.llm_client.structured_completion(prompt, TaskAnalysis)
                return TaskAnalysis.model_validate(result)
            except Exception:
                pass
        return self._rule_based_analyze(task)

    def _rule_based_analyze(self, task: Task) -> TaskAnalysis:
        text = " ".join(part for part in (task.description, task.context) if part).lower()
        matches = [
            capability
            for capability, keywords in KEYWORDS.items()
            if any(keyword.lower() in text for keyword in keywords)
        ]
        if not matches:
            return TaskAnalysis(
                complexity=ComplexityLevel.LOW,
                required_capabilities=[CapabilityName.TASK_PLANNING],
                reasoning="未识别到明确领域能力，使用通用任务规划能力作为兜底。",
                confidence=0.5,
            )
        complexity = (
            ComplexityLevel.LOW
            if len(matches) <= 2
            else ComplexityLevel.MEDIUM
            if len(matches) <= 4
            else ComplexityLevel.HIGH
        )
        names = "、".join(capability.value for capability in matches)
        return TaskAnalysis(
            complexity=complexity,
            required_capabilities=matches,
            reasoning=f"基于规则匹配识别出以下能力：{names}。",
            confidence=0.5,
        )
