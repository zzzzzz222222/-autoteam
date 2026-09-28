"""Deterministic tool selection (v0.3.0).

Maps capabilities to tools. Tools must already exist in the ``ToolRegistry`` —
the selector filters against it, so neither the LLM nor an agent can invent or
register tools. Core chain: Task → Capability → Role → Agent → Tool.
"""

from __future__ import annotations

from app.models.capability import CapabilityName
from app.tools.registry import ToolRegistry

CAPABILITY_TOOLS: dict[CapabilityName, tuple[str, ...]] = {
    CapabilityName.MARKET_RESEARCH: ("web_search",),
    CapabilityName.COMPETITOR_ANALYSIS: ("web_search",),
    CapabilityName.TECHNOLOGY_ANALYSIS: ("web_search",),
    CapabilityName.CUSTOMER_RESEARCH: ("web_search",),
    CapabilityName.FACT_CHECKING: ("web_search",),
    CapabilityName.STRATEGY_PLANNING: ("web_search",),
    CapabilityName.DATA_ANALYSIS: ("data_analyzer", "calculator"),
    CapabilityName.FINANCIAL_ANALYSIS: ("data_analyzer", "calculator"),
    CapabilityName.DATABASE_DESIGN: ("schema_validator",),
    CapabilityName.API_DESIGN: ("code_analysis",),
    CapabilityName.BACKEND_DEVELOPMENT: ("code_analysis",),
    CapabilityName.CODE_GENERATION: ("code_analysis",),
    CapabilityName.TEST_WRITING: ("code_analysis",),
}


class ToolSelector:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry(mode="auto")

    def select(self, capabilities: list[CapabilityName]) -> list[str]:
        selected: list[str] = []
        for capability in capabilities:
            for tool in CAPABILITY_TOOLS.get(capability, ()):
                if tool not in selected and tool in self.registry.available():
                    selected.append(tool)
        return selected
