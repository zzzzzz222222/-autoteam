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
    # v0.3.0 vocabulary additions (additive; existing values untouched).
    TECHNOLOGY_ANALYSIS = "technology_analysis"
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    SYSTEM_ARCHITECTURE = "system_architecture"
    API_DESIGN = "api_design"
    DATABASE_DESIGN = "database_design"
    BACKEND_DEVELOPMENT = "backend_development"
    CUSTOMER_RESEARCH = "customer_research"
    STRATEGY_PLANNING = "strategy_planning"
    PROPOSAL_WRITING = "proposal_writing"


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
    # v0.3.0 capability pool additions.
    CapabilityName.TECHNOLOGY_ANALYSIS: Capability(
        name=CapabilityName.TECHNOLOGY_ANALYSIS,
        description="分析技术路线、技术趋势与技术选型",
        typical_tools=["web_search"],
    ),
    CapabilityName.REQUIREMENT_ANALYSIS: Capability(
        name=CapabilityName.REQUIREMENT_ANALYSIS,
        description="梳理业务需求并形成结构化需求说明",
        typical_tools=[],
    ),
    CapabilityName.SYSTEM_ARCHITECTURE: Capability(
        name=CapabilityName.SYSTEM_ARCHITECTURE,
        description="设计系统架构、模块划分与技术选型",
        typical_tools=[],
    ),
    CapabilityName.API_DESIGN: Capability(
        name=CapabilityName.API_DESIGN,
        description="设计服务接口契约与数据交互协议",
        typical_tools=["code_analysis"],
    ),
    CapabilityName.DATABASE_DESIGN: Capability(
        name=CapabilityName.DATABASE_DESIGN,
        description="设计数据模型、表结构与存储方案",
        typical_tools=["schema_validator"],
    ),
    CapabilityName.BACKEND_DEVELOPMENT: Capability(
        name=CapabilityName.BACKEND_DEVELOPMENT,
        description="实现服务端业务逻辑与接口",
        typical_tools=["code_analysis"],
    ),
    CapabilityName.CUSTOMER_RESEARCH: Capability(
        name=CapabilityName.CUSTOMER_RESEARCH,
        description="研究目标客户画像、需求与购买动机",
        typical_tools=["web_search"],
    ),
    CapabilityName.STRATEGY_PLANNING: Capability(
        name=CapabilityName.STRATEGY_PLANNING,
        description="制定市场进入与增长策略",
        typical_tools=["web_search"],
    ),
    CapabilityName.PROPOSAL_WRITING: Capability(
        name=CapabilityName.PROPOSAL_WRITING,
        description="撰写结构化方案与提案文档",
        typical_tools=[],
    ),
}
