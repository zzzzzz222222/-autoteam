from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import TaskAnalysis

ROLE_TEMPLATES = [
    {
        "name": "Market Researcher",
        "capabilities": [CapabilityName.MARKET_RESEARCH, CapabilityName.DATA_ANALYSIS],
        "goal": "收集并分析市场数据，输出行业洞察",
        "tools": ["web_search", "data_analyzer"],
    },
    {
        "name": "Competitor Analyst",
        "capabilities": [CapabilityName.COMPETITOR_ANALYSIS, CapabilityName.MARKET_RESEARCH],
        "goal": "分析竞争对手的策略、产品与市场表现",
        "tools": ["web_search"],
    },
    {
        "name": "Financial Analyst",
        "capabilities": [CapabilityName.FINANCIAL_ANALYSIS, CapabilityName.DATA_ANALYSIS],
        "goal": "进行财务数据分析与估值分析",
        "tools": ["code_interpreter"],
    },
    {
        "name": "Fact Checker",
        "capabilities": [CapabilityName.FACT_CHECKING],
        "goal": "验证事实性陈述并识别潜在错误",
        "tools": ["web_search"],
    },
    {
        "name": "Report Writer",
        "capabilities": [CapabilityName.REPORT_WRITING],
        "goal": "将分析结果整理为结构化报告",
        "tools": [],
    },
    {
        "name": "Software Planner",
        "capabilities": [CapabilityName.TASK_PLANNING, CapabilityName.PRODUCT_DESIGN],
        "goal": "分解软件开发任务并制定执行计划",
        "tools": [],
    },
    {
        "name": "Developer",
        "capabilities": [CapabilityName.CODE_GENERATION],
        "goal": "编写可运行的软件代码",
        "tools": ["code_interpreter"],
    },
    {
        "name": "Code Reviewer",
        "capabilities": [CapabilityName.CODE_REVIEW, CapabilityName.TEST_WRITING],
        "goal": "审查代码质量并编写测试",
        "tools": ["code_interpreter"],
    },
    {
        "name": "Risk Analyst",
        "capabilities": [CapabilityName.RISK_ANALYSIS],
        "goal": "识别潜在风险并分析影响",
        "tools": [],
    },
    {
        "name": "Data Analyst",
        "capabilities": [CapabilityName.DATA_ANALYSIS],
        "goal": "分析数据并提取关键规律",
        "tools": ["data_analyzer"],
    },
    {
        "name": "Product Designer",
        "capabilities": [CapabilityName.PRODUCT_DESIGN],
        "goal": "分析产品需求并设计产品方案",
        "tools": [],
    },
]


class RoleAllocator:
    def allocate(self, analysis: TaskAnalysis) -> list[AgentSpec]:
        remaining = set(analysis.required_capabilities)
        agents: list[AgentSpec] = []
        while remaining:
            candidates = [
                template
                for template in ROLE_TEMPLATES
                if remaining.intersection(template["capabilities"])
            ]
            if not candidates:
                capability = next(iter(remaining))
                agents.append(
                    AgentSpec(
                        role=AgentRole(
                            name="General Agent",
                            capabilities=[capability],
                            goal=f"完成与 {capability.value} 相关的任务",
                        )
                    )
                )
                remaining.remove(capability)
                continue
            template = max(
                candidates, key=lambda item: len(remaining.intersection(item["capabilities"]))
            )
            agents.append(
                AgentSpec(
                    role=AgentRole(
                        name=template["name"],
                        capabilities=template["capabilities"],
                        goal=template["goal"],
                    ),
                    tools=template["tools"],
                )
            )
            remaining.difference_update(template["capabilities"])
        return agents
