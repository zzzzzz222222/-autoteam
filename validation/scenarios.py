"""Real-scenario definitions for AutoTeam validation.

Each scenario is plain user language plus a *human* acceptance checklist. The
checklist exists for a reviewer to fill in by hand after reading the produced
report and its sources; it is never fed to an LLM to generate a score.

Deliberately absent: agent counts, role names, DAG topology, execution order.
Team formation must stay dynamic — those are outputs to be observed, not inputs
to be prescribed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """One validation scenario: a task plus a manual acceptance checklist."""

    scenario_id: str
    name: str
    task: str
    checklist: tuple[str, ...]


SCENARIO_A_TASK = (
    "分析 2026 年 AI Agent 在中小企业中的应用市场，研究市场需求、主要产品与竞品、"
    "技术发展趋势、实际落地难点和商业化机会，并设计一个适合小团队开发的 AI Agent "
    "产品方案。报告需说明证据来源、关键假设、风险和建议的落地步骤。"
)

SCENARIO_B_TASK = (
    "设计一个面向约 100 人企业的 AI 智能客服系统，覆盖知识库、权限隔离、工单流转、"
    "模型服务、系统架构、部署方式、运行监控及成本控制，输出可执行的技术方案。"
)

SCENARIO_C_TASK = (
    "为一个计划进入海外市场的中小型电商团队研究市场进入机会，覆盖目标市场、消费者需求、"
    "竞品、物流、售后、合规风险和实施计划，输出有证据来源和不确定性说明的决策支持报告。"
)

SCENARIOS: dict[str, Scenario] = {
    "A": Scenario(
        scenario_id="A",
        name="AI Agent 市场研究",
        task=SCENARIO_A_TASK,
        checklist=(
            "市场需求和典型应用场景",
            "主要竞品及产品能力",
            "技术发展趋势",
            "企业落地难点",
            "商业化机会",
            "产品定位及目标用户",
            "产品核心功能",
            "技术实现思路",
            "风险、假设及不确定性",
            "分阶段实施建议",
            "关键结论具有可核验的来源支持",
        ),
    ),
    "B": Scenario(
        scenario_id="B",
        name="企业 AI 客服技术方案",
        task=SCENARIO_B_TASK,
        checklist=(
            "需求和用户角色",
            "系统架构",
            "RAG 知识库设计",
            "权限和数据隔离",
            "工单流程",
            "模型和工具选型",
            "后端 API 设计",
            "部署与监控",
            "安全和异常处理",
            "成本估算依据及限制",
            "分阶段实施方案",
        ),
    ),
    "C": Scenario(
        scenario_id="C",
        name="跨境电商市场进入研究",
        task=SCENARIO_C_TASK,
        checklist=(
            "目标市场与需求",
            "消费者特点",
            "竞品与差异化机会",
            "物流与履约",
            "售后和运营成本因素",
            "合规风险",
            "市场进入策略",
            "执行计划",
            "关键假设及不确定性",
            "结论的证据支持",
        ),
    ),
}

# Scenario A is the first-round validation target (see validation/REPORT.md).
DEFAULT_SCENARIO_ID = "A"


def scenario_ids() -> list[str]:
    """Stable, sorted scenario ids (for CLI help and tests)."""
    return sorted(SCENARIOS)


def get_scenario(scenario_id: str) -> Scenario:
    """Resolve a scenario id case-insensitively; raise ``KeyError`` otherwise."""
    key = (scenario_id or "").strip().upper()
    if key not in SCENARIOS:
        raise KeyError(f"unknown scenario '{scenario_id}' (expected one of {scenario_ids()})")
    return SCENARIOS[key]
