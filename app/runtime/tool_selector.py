"""Deterministic tool selection (v0.3.0; capability mapping fixed in v0.6.12).

Maps capabilities to tools. Tools must already exist in the ``ToolRegistry`` —
the selector filters against it, so neither the LLM nor an agent can invent or
register tools. Core chain: Task → Capability → Role → Agent → Tool.

``CAPABILITY_TOOLS`` is the **single authorisation source**: the AgentFactory
derives ``AgentSpec.tools`` from it, the LLM only ever sees those tools, and
``AgentRuntime`` re-checks them in code before execution (v0.6.11). Anything a
capability is not explicitly granted is denied — a missing entry means
"no tools", never "all tools".

Phase 6.12 (L1): ``requirement_analysis`` had no entry, so the Requirement
Analyst received ``tools=[]`` and — once v0.6.11 enforced the boundary — could no
longer gather any sourced evidence. Its responsibility is market-grounded
requirement research, so it now gets the *minimum* tool that restores sourcing
(``web_search``), matching the sibling research capabilities. Aggregation-only
capabilities (proposal/report writing) intentionally stay tool-free.
"""

from __future__ import annotations

from app.models.capability import CapabilityName
from app.tools.registry import ToolRegistry

CAPABILITY_TOOLS: dict[CapabilityName, tuple[str, ...]] = {
    # --- research capabilities: they must gather external, citable material ---
    CapabilityName.MARKET_RESEARCH: ("web_search",),
    CapabilityName.COMPETITOR_ANALYSIS: ("web_search",),
    CapabilityName.TECHNOLOGY_ANALYSIS: ("web_search",),
    CapabilityName.CUSTOMER_RESEARCH: ("web_search",),
    CapabilityName.FACT_CHECKING: ("web_search",),
    CapabilityName.STRATEGY_PLANNING: ("web_search",),
    # v0.6.12 (L1): requirement analysis produces the sourced requirements
    # document, so it needs the same single research tool as its siblings.
    CapabilityName.REQUIREMENT_ANALYSIS: ("web_search",),
    # --- quantitative work: offline deterministic analyzers only -------------
    CapabilityName.DATA_ANALYSIS: ("data_analyzer", "calculator"),
    CapabilityName.FINANCIAL_ANALYSIS: ("data_analyzer", "calculator"),
    # --- engineering capabilities: static analysis only ----------------------
    CapabilityName.DATABASE_DESIGN: ("schema_validator",),
    CapabilityName.API_DESIGN: ("code_analysis",),
    CapabilityName.BACKEND_DEVELOPMENT: ("code_analysis",),
    CapabilityName.CODE_GENERATION: ("code_analysis",),
    CapabilityName.TEST_WRITING: ("code_analysis",),
}

# Why each capability has exactly this tool set. A capability absent from
# ``CAPABILITY_TOOLS`` MUST say here why it is deliberately tool-free, so an
# omission can never be mistaken for an oversight.
CAPABILITY_TOOL_RATIONALE: dict[CapabilityName, str] = {
    CapabilityName.MARKET_RESEARCH: "gathers citable market facts -> web_search",
    CapabilityName.COMPETITOR_ANALYSIS: "gathers citable competitor facts -> web_search",
    CapabilityName.TECHNOLOGY_ANALYSIS: "gathers citable technology facts -> web_search",
    CapabilityName.CUSTOMER_RESEARCH: "gathers citable customer facts -> web_search",
    CapabilityName.FACT_CHECKING: "verifies claims against sources -> web_search",
    CapabilityName.STRATEGY_PLANNING: "grounds strategy options in sources -> web_search",
    CapabilityName.REQUIREMENT_ANALYSIS: (
        "produces the sourced requirements document (v0.6.12 L1 fix) -> web_search"
    ),
    CapabilityName.DATA_ANALYSIS: (
        "computes/aggregates metrics offline -> data_analyzer, calculator"
    ),
    CapabilityName.FINANCIAL_ANALYSIS: (
        "computes/aggregates figures offline -> data_analyzer, calculator"
    ),
    CapabilityName.DATABASE_DESIGN: "validates schemas locally -> schema_validator",
    CapabilityName.API_DESIGN: "inspects interfaces/modules -> code_analysis",
    CapabilityName.BACKEND_DEVELOPMENT: "inspects interfaces/modules -> code_analysis",
    CapabilityName.CODE_GENERATION: "inspects interfaces/modules -> code_analysis",
    CapabilityName.TEST_WRITING: "inspects interfaces/modules -> code_analysis",
    # --- intentionally tool-free (aggregation / design / planning) -----------
    CapabilityName.PROPOSAL_WRITING: (
        "tool-free by design: builds the proposal from upstream artifacts/evidence; "
        "no independent retrieval"
    ),
    CapabilityName.REPORT_WRITING: (
        "tool-free by design: the final report is assembled from upstream artifacts, "
        "evidence, findings and synthesis"
    ),
    CapabilityName.TASK_PLANNING: (
        "tool-free by design: planning uses the task + upstream context"
    ),
    CapabilityName.PRODUCT_DESIGN: (
        "tool-free by design: design decisions derive from requirement/research inputs"
    ),
    CapabilityName.SYSTEM_ARCHITECTURE: (
        "tool-free by design: architecture derives from requirement inputs"
    ),
    CapabilityName.RISK_ANALYSIS: (
        "tool-free by design: risks are analysed from the provided research context"
    ),
    CapabilityName.CODE_REVIEW: (
        "tool-free by design: no current role requires a code-review tool; code_analysis "
        "could apply if such a role is ever allocated"
    ),
}


def audit_capability_tools(registry: ToolRegistry | None = None) -> list[dict]:
    """Consistency diagnostics for the Capability -> Tool mapping (v0.6.12).

    Read-only and side-effect free. Returns one entry per problem so a
    misconfiguration is *reported* instead of being silently filtered away:

    * ``unregistered_tool``   - a mapped tool does not exist in the registry
    * ``unknown_capability``  - a mapping key is not a ``CapabilityName``
    * ``missing_rationale``   - a capability has no documented reason
    * ``unmapped_capability`` - a capability is tool-free (informational)
    """
    active = registry or ToolRegistry(mode="auto")
    available = set(active.available())
    issues: list[dict] = []
    for capability, tools in CAPABILITY_TOOLS.items():
        if not isinstance(capability, CapabilityName):
            issues.append(
                {
                    "severity": "error",
                    "issue": "unknown_capability",
                    "capability": str(capability),
                    "detail": "mapping key is not a CapabilityName",
                }
            )
            continue
        for tool in tools:
            if tool not in available:
                issues.append(
                    {
                        "severity": "error",
                        "issue": "unregistered_tool",
                        "capability": capability.value,
                        "detail": f"tool '{tool}' is mapped but not registered",
                    }
                )
    for capability in CapabilityName:
        if capability not in CAPABILITY_TOOL_RATIONALE:
            issues.append(
                {
                    "severity": "error",
                    "issue": "missing_rationale",
                    "capability": capability.value,
                    "detail": "capability has no documented tool rationale",
                }
            )
        elif capability not in CAPABILITY_TOOLS:
            issues.append(
                {
                    "severity": "info",
                    "issue": "unmapped_capability",
                    "capability": capability.value,
                    "detail": CAPABILITY_TOOL_RATIONALE[capability],
                }
            )
    return issues


class ToolSelector:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry(mode="auto")

    def select(self, capabilities: list[CapabilityName]) -> list[str]:
        """Authorised tools for a capability set (deterministic, deduplicated).

        Unknown capabilities and unregistered tools never grant anything: they
        are filtered here and surfaced by :func:`audit_capability_tools`.
        """
        selected: list[str] = []
        for capability in capabilities:
            for tool in CAPABILITY_TOOLS.get(capability, ()):
                if tool not in selected and tool in self.registry.available():
                    selected.append(tool)
        return selected
