from enum import Enum

from pydantic import BaseModel, Field


class CapabilityName(str, Enum):
    MARKET_RESEARCH = "market_research"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    FINANCIAL_ANALYSIS = "financial_analysis"
    FACT_CHECKING = "fact_checking"
    REPORT_WRITING = "report_writing"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    TEST_WRITING = "test_writing"
    TASK_PLANNING = "task_planning"
    RISK_ANALYSIS = "risk_analysis"
    DATA_ANALYSIS = "data_analysis"
    PRODUCT_DESIGN = "product_design"


class Capability(BaseModel):
    name: CapabilityName
    description: str
    typical_tools: list[str] = Field(default_factory=list)


CAPABILITY_POOL: dict[CapabilityName, Capability] = {
    CapabilityName.MARKET_RESEARCH: Capability(
        name=CapabilityName.MARKET_RESEARCH,
        description="收集、分析和总结市场、行业以及趋势相关信息",
        typical_tools=["web_search", "data_analyzer"],
    ),
    CapabilityName.COMPETITOR_ANALYSIS: Capability(
        name=CapabilityName.COMPETITOR_ANALYSIS,
        description="分析竞争对手的产品、策略与市场表现",
        typical_tools=["web_search"],
    ),
    CapabilityName.FINANCIAL_ANALYSIS: Capability(
        name=CapabilityName.FINANCIAL_ANALYSIS,
        description="分析财务数据、估值、收入、成本与利润",
        typical_tools=["code_interpreter", "data_analyzer"],
    ),
    CapabilityName.FACT_CHECKING: Capability(
        name=CapabilityName.FACT_CHECKING,
        description="核实事实性陈述并识别信息错误",
        typical_tools=["web_search"],
    ),
    CapabilityName.REPORT_WRITING: Capability(
        name=CapabilityName.REPORT_WRITING,
        description="将研究和分析结果整理为清晰的结构化报告",
        typical_tools=[],
    ),
    CapabilityName.CODE_GENERATION: Capability(
        name=CapabilityName.CODE_GENERATION,
        description="设计并实现可运行的软件代码",
        typical_tools=["code_interpreter"],
    ),
    CapabilityName.CODE_REVIEW: Capability(
        name=CapabilityName.CODE_REVIEW,
        description="审查代码质量、可维护性与潜在缺陷",
        typical_tools=["code_interpreter"],
    ),
    CapabilityName.TEST_WRITING: Capability(
        name=CapabilityName.TEST_WRITING,
        description="编写和维护单元测试及集成测试",
        typical_tools=["code_interpreter"],
    ),
    CapabilityName.TASK_PLANNING: Capability(
        name=CapabilityName.TASK_PLANNING,
        description="拆解任务并制定可执行的工作计划",
        typical_tools=[],
    ),
    CapabilityName.RISK_ANALYSIS: Capability(
        name=CapabilityName.RISK_ANALYSIS,
        description="识别风险、评估影响并提出缓解建议",
        typical_tools=[],
    ),
    CapabilityName.DATA_ANALYSIS: Capability(
        name=CapabilityName.DATA_ANALYSIS,
        description="处理数据并提取统计规律和业务洞察",
        typical_tools=["data_analyzer"],
    ),
    CapabilityName.PRODUCT_DESIGN: Capability(
        name=CapabilityName.PRODUCT_DESIGN,
        description="分析产品需求并设计功能方案",
        typical_tools=[],
    ),
}
