"""Bilingual UI strings for the AutoTeam Streamlit page (English / 简体中文).

Only presentation text lives here. Core domain values (capability enums,
ExecutionStatus values, topology types) stay in English because they are
identifiers used by the Day 1-5 code.
"""

from collections.abc import Mapping

EN = "en"
ZH = "zh"
DEFAULT_LOCALE = EN
LOCALES = (EN, ZH)
LOCALE_LABELS = {EN: "English", ZH: "中文"}

STRINGS: Mapping[str, Mapping[str, str]] = {
    "subtitle": {
        EN: "Adaptive Multi-Agent Orchestration — Task → Team → Topology → "
            "Execution → Recovery → Evaluation",
        ZH: "自适应多智能体编排 —— 任务 → 团队 → 拓扑 → 执行 → 恢复 → 评估",
    },
    "section.task": {EN: "1 · Task", ZH: "1 · 任务"},
    "section.team": {EN: "2 · Team Formation", ZH: "2 · 团队组建"},
    "section.topologies": {EN: "3 · Candidate Topologies", ZH: "3 · 候选拓扑"},
    "section.graph": {EN: "4 · Topology Graph", ZH: "4 · 拓扑图"},
    "section.execution": {EN: "5 · Execution", ZH: "5 · 执行"},
    "section.results": {EN: "6 · Execution Results", ZH: "6 · 执行结果"},
    "section.evaluation": {EN: "7 · Evaluation", ZH: "7 · 评估"},
    "section.comparison": {EN: "8 · Comparison", ZH: "8 · 对比"},
    "preset.label": {EN: "Preset", ZH: "预设任务"},
    "preset.custom": {EN: "Custom", ZH: "自定义"},
    "task.text_area": {EN: "Task description", ZH: "任务描述"},
    "task.analyze": {EN: "Analyze & Build Team", ZH: "分析并组建团队"},
    "analysis.caption": {EN: "Task analysis", ZH: "任务分析"},
    "analysis.complexity": {EN: "Complexity", ZH: "复杂度"},
    "analysis.confidence": {EN: "Confidence", ZH: "置信度"},
    "analysis.capabilities": {EN: "Capabilities", ZH: "所需能力"},
    "analysis.reasoning": {
        EN: "Rule-based offline detection matched: {caps}.",
        ZH: "基于离线规则匹配识别出：{caps}。",
    },
    "team.caption": {EN: "Agent team — {count}", ZH: "智能体团队 —— {count} 个"},
    "team.tools": {EN: "Tools: ", ZH: "工具："},
    "team.small_hint": {
        EN: "This task produced a small team, so the three topologies look similar. "
            "Richer descriptions allocate more capabilities — try the "
            "**Deep Market Study** preset.",
        ZH: "该任务只组建出较小的团队，三种拓扑看起来差别不大。"
            "描述越丰富，匹配到的能力越多 —— 可以试试 **Deep Market Study**（深度市场研究）预设。",
    },
    "metric.agents": {EN: "Agents", ZH: "智能体"},
    "metric.edges": {EN: "Edges", ZH: "边"},
    "metric.steps": {EN: "Steps", ZH: "层数"},
    "metric.parallelism": {EN: "Parall.", ZH: "并行度"},
    "graph.topology": {EN: "Topology", ZH: "拓扑"},
    "graph.edges": {EN: "Edges: ", ZH: "依赖边："},
    "graph.empty_edges": {EN: "none", ZH: "无"},
    "graph.no_candidate": {
        EN: "No valid topology was generated for this team.",
        ZH: "该团队没有生成任何合法拓扑。",
    },
    "run.config": {EN: "Run configuration", ZH: "运行配置"},
    "run.delay": {EN: "Mock agent delay (s)", ZH: "模拟智能体耗时（秒）"},
    "run.concurrency": {EN: "Max concurrency", ZH: "最大并发数"},
    "run.concurrency.unlimited": {EN: "unlimited", ZH: "不限"},
    "run.failure": {EN: "Enable failure simulation", ZH: "开启故障模拟"},
    "run.scenario": {EN: "Failure scenario", ZH: "故障场景"},
    "run.scenario.retry": {EN: "Retry then succeed", ZH: "重试后成功"},
    "run.scenario.exhausted": {EN: "Retry exhausted", ZH: "重试耗尽"},
    "run.failing_agent": {EN: "Failing agent", ZH: "故障智能体"},
    "run.button": {EN: "Run All Topologies", ZH: "运行全部拓扑"},
    "run.spinner": {EN: "Executing topologies...", ZH: "正在执行拓扑…"},
    "run.max_concurrency": {EN: "max concurrency", ZH: "最大并发"},
    "run.skipped_note": {
        EN: "SKIPPED — upstream dependency failed or was unavailable.",
        ZH: "已跳过 —— 上游依赖失败或不可用。",
    },
    "attempt.detail": {EN: "attempt {n}: {status}", ZH: "第 {n} 次尝试：{status}"},
    "table.agent": {EN: "Agent", ZH: "智能体"},
    "table.status": {EN: "Status", ZH: "状态"},
    "table.attempts": {EN: "Attempts", ZH: "尝试次数"},
    "table.duration": {EN: "Duration", ZH: "耗时"},
    "eval.metric": {EN: "Metric", ZH: "指标"},
    "eval.duration": {EN: "Duration (s)", ZH: "耗时（秒）"},
    "eval.success_rate": {EN: "Success Rate", ZH: "成功率"},
    "eval.failure_rate": {EN: "Failure Rate", ZH: "失败率"},
    "eval.skipped": {EN: "Skipped Agents", ZH: "跳过智能体数"},
    "eval.recovered": {EN: "Recovered Agents", ZH: "重试恢复数"},
    "eval.concurrency": {EN: "Max Concurrency", ZH: "最大并发数"},
    "eval.parallelism": {EN: "Parallelism", ZH: "并行度"},
    "eval.size": {EN: "Agents / Edges", ZH: "智能体 / 边"},
    "eval.observations": {EN: "Per-topology observations", ZH: "各拓扑观察结论"},
    "eval.strengths": {EN: "Strengths: ", ZH: "优势："},
    "eval.weaknesses": {EN: "Weaknesses: ", ZH: "劣势："},
    "eval.observed": {EN: "Observed: ", ZH: "观察到："},
    "cmp.shortest": {EN: "Shortest Duration", ZH: "耗时最短"},
    "cmp.success": {EN: "Highest Success Rate", ZH: "成功率最高"},
    "cmp.parallel": {EN: "Highest Parallelism", ZH: "并行度最高"},
    "cmp.reliable": {EN: "Most Reliable (lowest failure rate)", ZH: "最可靠（失败率最低）"},
    "cmp.note": {
        EN: "Metric-specific results only. AutoTeam does not compute a weighted score "
            "and does not declare a single overall winner.",
        ZH: "以上仅为按指标分别得出的结果。AutoTeam 不计算加权总分，也不宣布唯一总冠军。",
    },
    "value.na": {EN: "n/a", ZH: "无"},
}

COMPLEXITY: Mapping[str, Mapping[str, str]] = {
    "low": {EN: "low", ZH: "低"},
    "medium": {EN: "medium", ZH: "中"},
    "high": {EN: "high", ZH: "高"},
}

CAPABILITIES: Mapping[str, str] = {
    "market_research": "市场调研",
    "competitor_analysis": "竞品分析",
    "financial_analysis": "财务分析",
    "fact_checking": "事实核查",
    "report_writing": "报告撰写",
    "code_generation": "代码生成",
    "code_review": "代码审查",
    "test_writing": "测试编写",
    "task_planning": "任务规划",
    "risk_analysis": "风险分析",
    "data_analysis": "数据分析",
    "product_design": "产品设计",
}

ROLE_NAMES: Mapping[str, str] = {
    "Market Researcher": "市场研究员",
    "Competitor Analyst": "竞品分析师",
    "Financial Analyst": "财务分析师",
    "Fact Checker": "事实核查员",
    "Report Writer": "报告撰写员",
    "Software Planner": "软件规划师",
    "Developer": "开发工程师",
    "Code Reviewer": "代码审查员",
    "Risk Analyst": "风险分析师",
    "Data Analyst": "数据分析师",
    "Product Designer": "产品设计师",
    "General Agent": "通用智能体",
}

ROLE_GOALS: Mapping[str, str] = {
    "Market Researcher": "Collect and analyse market data, produce industry insights",
    "Competitor Analyst": "Analyse competitor strategy, product and market performance",
    "Financial Analyst": "Run financial data analysis and valuation",
    "Fact Checker": "Verify factual statements and surface potential errors",
    "Report Writer": "Turn analysis results into a structured report",
    "Software Planner": "Break down software tasks and build an execution plan",
    "Developer": "Write runnable software code",
    "Code Reviewer": "Review code quality and write tests",
    "Risk Analyst": "Identify risks and assess their impact",
    "Data Analyst": "Analyse data and extract key patterns",
    "Product Designer": "Analyse product requirements and design a solution",
    "General Agent": "Handle tasks for the assigned capability",
}

OBSERVATIONS: Mapping[str, str] = {
    "simple dependency structure": "依赖关系简单",
    "multiple agents depend directly on the root agent": "多个智能体直接依赖根节点",
    "balanced multi-level dependency structure": "多层依赖结构平衡",
    "limited parallel execution": "并行执行受限",
    "high potential parallelism": "潜在并行度高",
    "all agents completed successfully": "全部智能体执行成功",
    "one or more agents failed": "存在失败的智能体",
    "retry recovery occurred": "发生过重试恢复",
}


def is_supported(locale: str) -> bool:
    return locale in LOCALES


def translate(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Return the localized string for ``key``, falling back to English."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(locale) or entry[EN]


def complexity_label(value: str, locale: str = DEFAULT_LOCALE) -> str:
    entry = COMPLEXITY.get(value)
    if entry is None:
        return value
    return entry.get(locale) or entry[EN]


def capability_label(value: str, locale: str = DEFAULT_LOCALE) -> str:
    if locale != ZH:
        return value
    return CAPABILITIES.get(value, value)


def role_name(name: str, locale: str = DEFAULT_LOCALE) -> str:
    if locale != ZH:
        return name
    return ROLE_NAMES.get(name, name)


def role_goal(name: str, goal: str, locale: str = DEFAULT_LOCALE) -> str:
    """Roles ship with Chinese goals, so English needs an explicit translation."""
    if locale == EN:
        return ROLE_GOALS.get(name, goal)
    return goal


def observation_label(text: str, locale: str = DEFAULT_LOCALE) -> str:
    if locale != ZH:
        return text
    return OBSERVATIONS.get(text, text)
