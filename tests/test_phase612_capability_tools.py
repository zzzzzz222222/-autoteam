"""Phase 6.12 — Capability → Tool mapping (L1 fix) and permission consistency.

All fixtures are offline and side-effect free: the AgentFactory only *describes*
agents, and the execution tests reuse the Phase 6.11 pattern (scripted non-mock
provider + counting fake tools). ``web_search`` is never executed.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models.capability import CapabilityName
from app.runtime.agent_factory import DynamicAgentFactory
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.artifacts import AgentDecision, AgentDeliverable, ToolCall
from app.runtime.context import AgentExecutionContext
from app.runtime.dynamic_models import (
    DynamicPlan,
    DynamicSubtask,
    RoleSpec,
)
from app.runtime.events import ExecutionTrace
from app.runtime.session import SessionStatus, execute_task
from app.runtime.tool_selector import (
    CAPABILITY_TOOL_RATIONALE,
    CAPABILITY_TOOLS,
    ToolSelector,
    audit_capability_tools,
)
from app.runtime.understanding import TaskUnderstanding
from app.tools.registry import (
    SearchResult,
    ToolNotAllowed,
    ToolNotFound,
    ToolRegistry,
    ToolResult,
)

# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Duck-typed *real* provider (not a MockLLMProvider) with scripted decisions."""

    def __init__(self, decisions: list) -> None:
        self.decisions = list(decisions)
        self.prompts: list[str] = []

    def structured_completion(self, prompt: str, response_model: type[BaseModel]):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.decisions) - 1)
        item = self.decisions[index]
        if isinstance(item, BaseModel):
            return item
        if callable(item):
            item = item()
        return response_model.model_validate(item)


class FakeRegistry(ToolRegistry):
    """Registry whose tool implementations are counting fakes (no I/O)."""

    def __init__(self, *, kind: str = "web", with_url: bool = True) -> None:
        super().__init__(mode="auto")
        self.calls: list[str] = []
        self._kind = kind
        self._with_url = with_url
        fake = self._make_fake()
        self._tools = {name: fake for name in self._tools}

    def _make_fake(self):
        registry = self

        def fake(query: str) -> ToolResult:
            registry.calls.append(query)
            url = "https://example.test/page" if registry._with_url else ""
            return ToolResult(
                query=query,
                offline=registry._kind != "web",
                kind=registry._kind,
                results=[f"result for {query}"],
                search_results=[
                    SearchResult(
                        title="page",
                        url=url,
                        snippet=f"snippet about {query} 42%",
                        source=registry._kind,
                    )
                ],
            )

        return fake


def _role(capabilities: list[CapabilityName], *, role_id: str = "r1") -> RoleSpec:
    return RoleSpec(id=role_id, name="Test Role", capabilities=list(capabilities))


def _plan(subtask_id: str = "st1") -> DynamicPlan:
    return DynamicPlan(
        objective="obj",
        domain="market_research",
        subtasks=[
            DynamicSubtask(
                id=subtask_id,
                title="Research",
                required_capabilities=[CapabilityName.MARKET_RESEARCH],
                expected_output="market_overview",
            )
        ],
    )


def _understanding() -> TaskUnderstanding:
    return TaskUnderstanding(task="t", domain="market_research", objective="o")


def _agent(*, tools: list[str], agent_id: str = "agent_x", caps=None):
    from app.models.agent import AgentRole
    from app.runtime.agent_factory import DynamicAgentSpec

    return DynamicAgentSpec(
        id=agent_id,
        role=AgentRole(
            name="Agent X",
            capabilities=list(caps or [CapabilityName.MARKET_RESEARCH]),
            goal="test",
        ),
        tools=list(tools),
        system_prompt="test",
        max_iterations=4,
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        agent_id="agent_x", role_name="Agent X", task="research", expected_output="market_overview"
    )


class _Task:
    description = "research the market"


def _call(tool: str, arguments: dict) -> AgentDecision:
    return AgentDecision(
        action="call_tool", tool_call=ToolCall(tool_name=tool, arguments=arguments)
    )


def _finish(claim: str = "claim 42%") -> AgentDecision:
    return AgentDecision(
        action="finish",
        deliverable=AgentDeliverable(title="t", summary="s", key_points=[claim], sources=[]),
    )


def _run(runtime: AgentRuntime, agent) -> tuple:
    result = runtime._real_execution(agent, _context(), _Task())
    deliverable, sources, evidence, used, _partial = result
    return deliverable, sources, evidence, used


def _denials(runtime: AgentRuntime) -> list:
    return [e for e in runtime.trace.events if e.type == "TOOL_DENIED"]


# ---------------------------------------------------------------------------
# 6.1 Capability mapping
# ---------------------------------------------------------------------------


def test_requirement_analysis_has_a_minimal_mapping() -> None:
    """1: the L1 gap is closed with the minimum tool."""
    assert CAPABILITY_TOOLS[CapabilityName.REQUIREMENT_ANALYSIS] == ("web_search",)
    assert ToolSelector().select([CapabilityName.REQUIREMENT_ANALYSIS]) == ["web_search"]


def test_proposal_writing_mapping_matches_its_responsibility() -> None:
    """2: aggregation-only -> deliberately tool-free (not an omission)."""
    assert CapabilityName.PROPOSAL_WRITING not in CAPABILITY_TOOLS
    assert "tool-free by design" in CAPABILITY_TOOL_RATIONALE[CapabilityName.PROPOSAL_WRITING]
    assert ToolSelector().select([CapabilityName.PROPOSAL_WRITING]) == []


def test_report_writing_gets_no_tools_by_default() -> None:
    """3: the report is assembled from upstream material."""
    assert CapabilityName.REPORT_WRITING not in CAPABILITY_TOOLS
    assert ToolSelector().select([CapabilityName.REPORT_WRITING]) == []


def test_every_mapped_tool_is_registered() -> None:
    """4: the shipped mapping has no unregistered tools."""
    errors = [i for i in audit_capability_tools() if i["severity"] == "error"]
    assert errors == []


def test_unknown_capability_grants_nothing() -> None:
    """5: an unknown capability must not fall back to any tool."""
    assert ToolSelector().select(["totally_unknown"]) == []  # type: ignore[list-item]
    assert ToolSelector().select([]) == []


def test_unregistered_tool_in_mapping_is_reported(monkeypatch) -> None:
    """6: a mapped-but-unregistered tool is diagnosed, never silently granted."""
    monkeypatch.setitem(
        CAPABILITY_TOOLS, CapabilityName.MARKET_RESEARCH, ("web_search", "no_such_tool")
    )
    issues = audit_capability_tools()
    assert any(
        i["issue"] == "unregistered_tool" and "no_such_tool" in i["detail"] for i in issues
    )
    # the selector still refuses to grant the unregistered tool
    assert ToolSelector().select([CapabilityName.MARKET_RESEARCH]) == ["web_search"]


def test_multi_capability_merge_is_correct() -> None:
    """7: capabilities union their tools."""
    merged = ToolSelector().select([CapabilityName.MARKET_RESEARCH, CapabilityName.DATA_ANALYSIS])
    assert merged == ["web_search", "data_analyzer", "calculator"]


def test_duplicate_tools_are_deduplicated() -> None:
    """8: two research capabilities sharing web_search yield it once."""
    merged = ToolSelector().select(
        [CapabilityName.MARKET_RESEARCH, CapabilityName.COMPETITOR_ANALYSIS]
    )
    assert merged == ["web_search"]


def test_tool_order_is_stable() -> None:
    """9: repeated selection returns the identical order."""
    caps = [CapabilityName.DATA_ANALYSIS, CapabilityName.MARKET_RESEARCH]
    first = ToolSelector().select(caps)
    second = ToolSelector().select(caps)
    assert first == second == ["data_analyzer", "calculator", "web_search"]


def test_mapping_is_deterministic() -> None:
    """10: select()/audit() are pure and reproducible."""
    selector = ToolSelector()
    for _ in range(3):
        assert selector.select([CapabilityName.REQUIREMENT_ANALYSIS]) == ["web_search"]
        assert audit_capability_tools() == audit_capability_tools()


# ---------------------------------------------------------------------------
# 6.2 Agent tool permission
# ---------------------------------------------------------------------------


def _factory_agent(capabilities: list[CapabilityName]):
    factory = DynamicAgentFactory(ToolSelector(ToolRegistry(mode="auto")))
    role = _role(capabilities)
    return factory.create(role, _plan(), _understanding())


def test_role_capabilities_produce_expected_agent_tools() -> None:
    """1: requirement_analysis now yields web_search on the generated AgentSpec."""
    agent = _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS])
    assert agent.tools == ["web_search"]


def test_agent_tools_equal_the_authorisation_mapping() -> None:
    """2: AgentSpec.tools is exactly the selector's authorisation result."""
    for caps in (
        [CapabilityName.MARKET_RESEARCH],
        [CapabilityName.DATA_ANALYSIS],
        [CapabilityName.REQUIREMENT_ANALYSIS],
        [CapabilityName.MARKET_RESEARCH, CapabilityName.DATA_ANALYSIS],
    ):
        agent = _factory_agent(caps)
        assert agent.tools == ToolSelector().select(caps)


def test_capability_without_tools_gets_none() -> None:
    """3: no capability -> no tools (never 'all tools')."""
    agent = _factory_agent([CapabilityName.REPORT_WRITING])
    assert agent.tools == []


def test_empty_tool_agent_cannot_call_anything() -> None:
    """4: tools=[] still denies everything (Phase 6.11 boundary intact)."""
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("web_search", {"query": "q"}), _finish()]),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
    )
    _d, sources, evidence, used = _run(runtime, _agent(tools=[]))
    assert registry.calls == [] and used == [] and sources == []
    assert _denials(runtime)[0].metadata["denial_reason"] == "tool_not_allowed"


def test_authorised_tool_still_executes() -> None:
    """5: the granted tool runs normally."""
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("web_search", {"query": "q"}), _finish()]),
        tool_registry=registry,
    )
    _d, sources, _e, used = _run(
        runtime, _agent(tools=["web_search"], caps=[CapabilityName.REQUIREMENT_ANALYSIS])
    )
    assert len(registry.calls) == 1 and used == ["web_search"]
    assert len(sources) == 1 and sources[0].source_type == "web"


def test_unauthorised_tool_still_denied() -> None:
    """6: a registered tool outside the agent's list is refused."""
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("calculator", {"expression": "1+1"}), _finish()]),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
    )
    _run(runtime, _agent(tools=["web_search"]))
    assert registry.calls == []
    assert _denials(runtime)[0].metadata["denial_reason"] == "tool_not_allowed"


def test_unknown_tool_is_still_unknown() -> None:
    """7: unknown_tool classification preserved."""
    registry = ToolRegistry(mode="auto")
    try:
        registry.validate_allowed("nope", ["nope"])
    except ToolNotFound:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ToolNotFound")


def test_not_allowed_is_distinct_from_unknown() -> None:
    """8: tool_not_allowed != unknown_tool."""
    registry = ToolRegistry(mode="auto")
    try:
        registry.validate_allowed("calculator", ["web_search"])
    except ToolNotAllowed:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ToolNotAllowed")


def test_dynamic_agent_cannot_bypass_the_dual_check() -> None:
    """9: an agent built by the factory still fails an undeclared tool call."""
    agent = _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS])  # tools == [web_search]
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("data_analyzer", {"query": "q"}), _finish()]),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
    )
    _d, _s, _e, used = _run(runtime, agent)
    assert registry.calls == [] and used == []
    assert _denials(runtime)[0].metadata["denial_reason"] == "tool_not_allowed"


def test_available_for_preserves_authorisation_order() -> None:
    """v0.6.12: the advertised schema must match AgentSpec.tools exactly."""
    registry = ToolRegistry(mode="auto")
    assert registry.available_for(["data_analyzer", "calculator"]) == [
        "data_analyzer",
        "calculator",
    ]
    assert registry.available_for(["calculator", "data_analyzer"]) == [
        "calculator",
        "data_analyzer",
    ]


def test_available_for_dedups_and_filters_unknown() -> None:
    """Only registered, authorised tools survive - deduplicated, order kept."""
    registry = ToolRegistry(mode="auto")
    assert registry.available_for(["web_search", "web_search", "nope"]) == ["web_search"]
    assert registry.available_for(None) == []
    assert registry.available_for([]) == []


def test_llm_visible_schema_equals_executable_set() -> None:
    """10: what the LLM is offered equals what it may execute."""
    agent = _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS])
    registry = ToolRegistry(mode="auto")
    advertised = registry.available_for(agent.tools)
    executable = [t for t in registry.available() if t in set(agent.tools)]
    assert advertised == executable == ["web_search"]
    provider = ScriptedProvider([_finish()])
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    _run(runtime, agent)
    advert = provider.prompts[0].split("Available tools:", 1)[1].split("\n", 1)[0]
    assert "web_search" in advert and "calculator" not in advert


# ---------------------------------------------------------------------------
# 6.3 offline execution-path simulation
# ---------------------------------------------------------------------------


def test_requirement_agent_uses_its_granted_tool() -> None:
    """1: the repaired capability can gather material again."""
    agent = _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS])
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("web_search", {"query": "requirements"}), _finish()]),
        tool_registry=registry,
    )
    _d, sources, evidence, used = _run(runtime, agent)
    assert registry.calls == ["requirements"] and used == ["web_search"]
    assert sources and any(e.source_id for e in evidence)


def test_denied_call_emits_audit_event() -> None:
    """2: denials remain auditable under the repaired mapping."""
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("code_analysis", {"query": "q"}), _finish()]),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
    )
    _run(runtime, _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS]))
    denial = _denials(runtime)[0]
    assert denial.metadata["tool"] == "code_analysis"
    assert denial.metadata["outcome"] == "denied"
    assert denial.metadata["attempt"] == 1


def test_llm_cannot_escalate_its_own_permissions() -> None:
    """3: repeatedly asking for an ungranted tool never yields execution."""
    decisions = [_call("calculator", {"expression": "1+1"})] * 3 + [_finish()]
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider(decisions),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
        max_iterations=3,
    )
    _d, sources, _e, used = _run(runtime, _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS]))
    assert registry.calls == [] and used == [] and sources == []
    assert len(_denials(runtime)) == 3


def test_tool_results_reach_collected_and_sources() -> None:
    """4/5: unified collection flow still applies after the mapping fix."""
    agent = _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS])
    registry = FakeRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("web_search", {"query": "market"}), _finish()]),
        tool_registry=registry,
    )
    _d, sources, evidence, _used = _run(runtime, agent)
    assert len(sources) == 1 and sources[0].url.startswith("https://example.test/")
    assert any(e.source_id == sources[0].id for e in evidence)


def test_source_identity_dedup_unchanged() -> None:
    """6: Phase 6.9 identity rules still collapse a shared URL."""
    from app.runtime.artifacts import AgentArtifact, ArtifactType
    from app.synthesis.evidence_filter import collect_evidence_records

    artifacts = []
    for agent_id in ("agent_a", "agent_b"):
        registry = FakeRegistry()
        runtime = AgentRuntime(
            provider=ScriptedProvider([_call("web_search", {"query": "q"}), _finish()]),
            tool_registry=registry,
        )
        agent = _factory_agent([CapabilityName.REQUIREMENT_ANALYSIS])
        agent.id = agent_id
        agent.role.name = agent_id
        _d, sources, evidence, _u = _run(runtime, agent)
        artifacts.append(
            AgentArtifact(
                artifact_id=f"artifact_{agent_id}",
                agent_id=agent_id,
                output_type=ArtifactType.ANALYSIS,
                title=agent_id,
                content="body",
                metadata={"role_name": agent_id},
                source_records=sources,
                evidence=evidence,
            )
        )
    _evidence, merged = collect_evidence_records(artifacts)
    assert len(merged) == 1
    assert merged[0].producer_agents == ["agent_a", "agent_b"]


def test_mock_results_are_not_labelled_as_web() -> None:
    """7: an offline tool result keeps offline_mock and no URL."""
    registry = FakeRegistry(kind="offline_mock", with_url=False)
    runtime = AgentRuntime(
        provider=ScriptedProvider([_call("data_analyzer", {"query": "q"}), _finish()]),
        tool_registry=registry,
    )
    agent = _factory_agent([CapabilityName.DATA_ANALYSIS])
    _d, sources, _e, _u = _run(runtime, agent)
    assert sources and all(s.source_type == "offline_mock" and s.url == "" for s in sources)


def test_tool_calls_results_and_sources_cross_check() -> None:
    """8: audit fields let the log be reconciled with the sources."""
    agent = _factory_agent([CapabilityName.MARKET_RESEARCH])
    registry = FakeRegistry()
    trace = ExecutionTrace("r")
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            [
                _call("web_search", {"query": "q1"}),
                _call("web_search", {"query": "q2"}),
                _finish(),
            ]
        ),
        tool_registry=registry,
        trace=trace,
    )
    _d, sources, _e, _u = _run(runtime, agent)
    calls = [e for e in trace.events if e.type == "TOOL_CALLED"]
    assert len(calls) == 2 == len(registry.calls)
    assert all(c.metadata["outcome"] == "ok" for c in calls)
    assert all(c.metadata["attempt"] == 1 for c in calls)
    assert sum(c.metadata["result_count"] for c in calls) >= len(sources)


def test_retry_does_not_pollute_sources() -> None:
    """9: a failed attempt's tool results never reach the artifact."""
    failing = ScriptedProvider([_call("web_search", {"query": "attempt1"}), _boom])
    registry = FakeRegistry()
    runtime = AgentRuntime(provider=failing, tool_registry=registry)
    try:
        _run(runtime, _factory_agent([CapabilityName.MARKET_RESEARCH]))
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected the first attempt to raise")
    assert len(registry.calls) == 1  # it did run...

    registry2 = FakeRegistry()
    runtime2 = AgentRuntime(provider=ScriptedProvider([_finish()]), tool_registry=registry2)
    _d, sources, evidence, used = _run(runtime2, _factory_agent([CapabilityName.MARKET_RESEARCH]))
    assert registry2.calls == [] and sources == [] and used == []
    assert all(e.source_id == "" for e in evidence)


def test_offline_scenario_a_runs_end_to_end() -> None:
    """10: the offline pipeline still completes (mock provider, no network)."""
    from validation.scenarios import get_scenario

    session = execute_task(
        get_scenario("A").task,
        provider=None,
        tool_mode="mock",
        timeout=None,
        max_tool_calls=6,
        max_iterations=4,
    )
    assert session.status in {SessionStatus.SUCCESS, SessionStatus.PARTIAL_SUCCESS}
    assert session.final_artifact is not None
    assert "## Executive Summary" in session.final_artifact.to_markdown()


def _boom():
    raise RuntimeError("provider failed mid-attempt")
