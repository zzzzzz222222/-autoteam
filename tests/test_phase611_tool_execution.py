"""Phase 6.11 — tool-execution chain repair (P610-1) and agent tool permissions (P610-2).

All fixtures are offline: a scripted provider (duck-typed real provider, never a
``MockLLMProvider``) drives the LLM tool-calling loop, and the tool registry's
implementations are replaced with counting fakes. Nothing here touches the
network, and ``web_search`` is never executed (the repository ``.env`` configures
a live search endpoint, so a real call would leave the machine).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models.agent import AgentRole
from app.models.capability import CapabilityName
from app.runtime.agent_factory import DynamicAgentSpec
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.artifacts import AgentDecision, AgentDeliverable, ToolCall
from app.runtime.context import AgentExecutionContext
from app.runtime.events import ExecutionTrace
from app.runtime.session import SessionStatus, execute_task
from app.tools.registry import (
    SearchResult,
    ToolNotAllowed,
    ToolNotFound,
    ToolRegistry,
    ToolResult,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Duck-typed *real* provider (not a MockLLMProvider) with scripted decisions."""

    def __init__(self, decisions: list) -> None:
        self.decisions = list(decisions)
        self.prompts: list[str] = []
        self.calls = 0

    def structured_completion(self, prompt: str, response_model: type[BaseModel]):
        self.prompts.append(prompt)
        self.calls += 1
        index = min(len(self.prompts) - 1, len(self.decisions) - 1)
        item = self.decisions[index]
        if isinstance(item, BaseModel):
            return item
        if callable(item):  # e.g. a helper that raises, to simulate a failed attempt
            item = item()
        return response_model.model_validate(item)


class CountingRegistry(ToolRegistry):
    """ToolRegistry whose tool implementations are counting fakes."""

    def __init__(self, *, kind: str = "web", with_url: bool = True) -> None:
        super().__init__(mode="auto")
        self.calls: list[tuple[str, dict]] = []
        self._kind = kind
        self._with_url = with_url
        self._fake = self._build_fake()
        self._tools = {name: self._fake for name in self._tools}

    def _build_fake(self):
        registry = self

        def fake(query: str) -> ToolResult:
            registry.calls.append(("call", {"query": query}))
            url = f"https://example.test/{abs(hash(query)) % 10_000}" if registry._with_url else ""
            return ToolResult(
                query=query,
                offline=registry._kind == "offline_mock",
                kind=registry._kind,
                results=[f"result for {query}"],
                search_results=[
                    SearchResult(
                        title=f"title {query[:20]}",
                        url=url,
                        snippet=f"snippet about {query} with 42% coverage",
                        source=registry._kind,
                    )
                ]
                if registry._with_url or registry._kind == "offline_mock"
                else [],
            )

        return fake


def _agent(tools: list[str], agent_id: str = "agent_x") -> DynamicAgentSpec:
    return DynamicAgentSpec(
        id=agent_id,
        role=AgentRole(
            name="Agent X", capabilities=[CapabilityName.MARKET_RESEARCH], goal="test"
        ),
        tools=list(tools),
        system_prompt="test",
        max_iterations=4,
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        agent_id="agent_x", role_name="Agent X", task="research the market",
        expected_output="market_overview",
    )


class _Task:
    description = "research the market"


def _tools_of(runtime: AgentRuntime) -> list[tuple[str, dict]]:
    return runtime.tool_registry.calls


def _events(runtime: AgentRuntime, event_type: str) -> list:
    return [e for e in runtime.trace.events if e.type == event_type]


def _deliverable(claim: str) -> dict:
    return {
        "title": "deliverable",
        "summary": "after tools",
        "key_points": [claim],
        "structured_data": {},
        "sources": [],
    }


def _run(runtime: AgentRuntime, agent: DynamicAgentSpec):
    result = runtime._real_execution(agent, _context(), _Task())
    deliverable, sources, evidence, used, _partial = result
    return deliverable, sources, evidence, used


# ---------------------------------------------------------------------------
# A. P610-1 — no pre-fetch, results reach the collection chain
# ---------------------------------------------------------------------------


def test_real_mode_does_not_prefetch_declared_tools() -> None:
    """A1/A11: no unconditional tool execution before the LLM decides."""
    provider = ScriptedProvider([_decision_finish()])
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    deliverable, sources, evidence, used = _run(runtime, _agent(["web_search"]))
    assert _tools_of(runtime) == []  # nothing ran without an LLM decision
    assert used == [] and sources == []
    # every claim is still kept as an *unbound* evidence record (never dropped)
    assert all(e.source_id == "" for e in evidence)
    assert deliverable.summary == "after tools"


def test_llm_not_calling_a_tool_executes_nothing() -> None:
    """A2: finish immediately -> zero tool executions."""
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=ScriptedProvider([_decision_finish()]), tool_registry=registry)
    _run(runtime, _agent(["web_search"]))
    assert len(registry.calls) == 0


def test_llm_calling_one_tool_executes_exactly_once() -> None:
    """A3: one LLM tool call -> exactly one execution."""
    provider = ScriptedProvider(
        [_decision_call("web_search", {"query": "sme market"}), _decision_finish()]
    )
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    _deliverable_out, sources, evidence, used = _run(runtime, _agent(["web_search"]))
    assert len(registry.calls) == 1
    assert used == ["web_search"]
    assert len(sources) == 1 and sources[0].url.startswith("https://example.test/")


def test_tool_results_reach_sources_and_evidence() -> None:
    """A4/A5: collected -> _collect_evidence produces Source + bound Evidence."""
    provider = ScriptedProvider(
        [_decision_call("web_search", {"query": "market"}), _decision_finish("market 42% coverage")]
    )
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    _d, sources, evidence, _used = _run(runtime, _agent(["web_search"]))
    assert len(sources) == 1
    assert sources[0].source_type == "web" and sources[0].url
    bound = [e for e in evidence if e.source_id]
    assert bound, "a matching claim must be bound to the retrieved source"
    assert bound[0].source_id == sources[0].id  # runtime Source uses .id
    assert sources[0].source_type == "web"


def test_tool_log_matches_execution_count() -> None:
    """A6: trace events correspond 1:1 with real executions."""
    provider = ScriptedProvider(
        [
            _decision_call("web_search", {"query": "q1"}),
            _decision_call("web_search", {"query": "q2"}),
            _decision_finish(),
        ]
    )
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=provider, tool_registry=registry, trace=ExecutionTrace("r"))
    _run(runtime, _agent(["web_search"]))
    called = _events(runtime, "TOOL_CALLED")
    assert len(registry.calls) == 2
    assert len(called) == 2
    assert [e.metadata["attempt"] for e in called] == [1, 1]
    assert all(e.metadata["outcome"] == "ok" for e in called)
    assert all(e.metadata["result_count"] == 1 for e in called)


def test_failed_tool_does_not_produce_a_source() -> None:
    """A7: an errored tool result must never become a source."""

    class FailingRegistry(CountingRegistry):
        def _build_fake(self):
            def boom(query: str) -> ToolResult:
                self.calls.append(("call", {"query": query}))
                raise RuntimeError("tool exploded")

            return boom

    provider = ScriptedProvider(
        [_decision_call("web_search", {"query": "q"}), _decision_finish("claim")]
    )
    registry = FailingRegistry()
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    _d, sources, evidence, _used = _run(runtime, _agent(["web_search"]))
    assert sources == []
    assert all(e.source_id == "" for e in evidence)
    assert all(e.review_status != "verified" for e in evidence)


def test_retry_attempts_are_isolated() -> None:
    """A8: results from a failed attempt never leak into the successful one."""
    # attempt 1: call a tool, then the provider fails -> whole attempt abandoned
    failing = ScriptedProvider([_decision_call("web_search", {"query": "attempt1"}), _raise])
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=failing, tool_registry=registry)
    try:
        _run(runtime, _agent(["web_search"]))
    except RuntimeError:
        pass
    else:  # pragma: no cover - the scripted provider must raise
        raise AssertionError("expected the first attempt to fail")
    assert len(registry.calls) == 1  # the tool did run...

    # attempt 2: a fresh provider/registry; nothing from attempt 1 is carried over
    registry2 = CountingRegistry()
    runtime2 = AgentRuntime(
        provider=ScriptedProvider([_decision_finish("no tools this time")]),
        tool_registry=registry2,
    )
    _d, sources, evidence, used = _run(runtime2, _agent(["web_search"]))
    assert registry2.calls == []
    assert sources == [] and used == []
    assert all(e.source_id == "" for e in evidence)


def test_same_url_across_agents_keeps_one_identity() -> None:
    """A9: Phase 6.9 identity rules still deduplicate shared URLs."""
    from app.synthesis.evidence_filter import collect_evidence_records

    class FixedRegistry(CountingRegistry):
        def _build_fake(self):
            def fixed(query: str) -> ToolResult:
                self.calls.append(("call", {"query": query}))
                return ToolResult(
                    query=query,
                    offline=False,
                    kind="web",
                    results=["shared snippet"],
                    search_results=[
                        SearchResult(
                            title="shared page",
                            url="https://shared.example/page",
                            snippet="shared snippet 42%",
                            source="web",
                        )
                    ],
                )

            return fixed

    artifacts = []
    for agent_id in ("agent_a", "agent_b"):
        registry = FixedRegistry()
        runtime = AgentRuntime(
            provider=ScriptedProvider(
                [_decision_call("web_search", {"query": "q"}), _decision_finish("42%")]
            ),
            tool_registry=registry,
        )
        agent = _agent(["web_search"], agent_id=agent_id)
        _d, sources, evidence, _used = _run(runtime, agent)
        from app.runtime.artifacts import AgentArtifact, ArtifactType

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


def test_mock_results_never_become_web_sources() -> None:
    """A10: an offline tool result stays offline_mock with no URL."""
    provider = ScriptedProvider(
        [_decision_call("mock_search", {"query": "q"}), _decision_finish("claim")]
    )
    registry = CountingRegistry(kind="offline_mock", with_url=False)
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    _d, sources, _evidence, _used = _run(runtime, _agent(["mock_search"]))
    assert len(sources) == 1
    assert sources[0].source_type == "offline_mock"
    assert sources[0].url == ""


def test_unbound_tool_result_reports_a_reason() -> None:
    """A12: when a tool result cannot support a claim, the reason is recorded."""
    provider = ScriptedProvider(
        [
            _decision_call("web_search", {"query": "q"}),
            _decision_finish("completely unrelated claim"),
        ]
    )
    registry = CountingRegistry()
    runtime = AgentRuntime(provider=provider, tool_registry=registry)
    _d, sources, evidence, _used = _run(runtime, _agent(["web_search"]))
    assert len(sources) == 1
    assert evidence and all(e.source_id == "" for e in evidence)
    reasons = ("no_snippet_above_threshold", "low_quality")
    assert all(e.match_method.startswith(reasons) for e in evidence)


# ---------------------------------------------------------------------------
# B. P610-2 — agent tool permission boundary
# ---------------------------------------------------------------------------


def test_authorised_tool_executes() -> None:
    """B1: a declared tool runs normally."""
    registry = CountingRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            [_decision_call("web_search", {"query": "q"}), _decision_finish()]
        ),
        tool_registry=registry,
    )
    _d, _s, _e, used = _run(runtime, _agent(["web_search"]))
    assert len(registry.calls) == 1 and used == ["web_search"]


def test_unauthorised_tool_is_denied_before_execution() -> None:
    """B2/B4/B6: registered but undeclared -> refused, executor never runs."""
    registry = CountingRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            [
                _decision_call("calculator", {"expression": "1+1"}),
                _decision_finish(),
            ]
        ),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
    )
    _d, _s, _e, used = _run(runtime, _agent(["web_search"]))  # calculator NOT declared
    assert registry.calls == []  # no side effect at all
    assert used == []
    denials = _events(runtime, "TOOL_DENIED")
    assert len(denials) == 1
    assert denials[0].metadata["denial_reason"] == "tool_not_allowed"
    assert denials[0].metadata["tool"] == "calculator"
    assert _events(runtime, "TOOL_CALLED") == []


def test_empty_tool_list_denies_everything() -> None:
    """B3: tools=[] means no tool may run."""
    registry = CountingRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            [_decision_call("web_search", {"query": "q"}), _decision_finish()]
        ),
        tool_registry=registry,
        trace=ExecutionTrace("r"),
    )
    _d, sources, evidence, used = _run(runtime, _agent([]))
    assert registry.calls == [] and used == [] and sources == []
    assert all(e.source_id == "" for e in evidence)
    denials = _events(runtime, "TOOL_DENIED")
    assert denials and denials[0].metadata["denial_reason"] == "tool_not_allowed"


def test_unknown_and_unauthorised_are_distinct() -> None:
    """B5: unknown_tool != tool_not_allowed."""
    registry = ToolRegistry(mode="auto")
    try:
        registry.validate_allowed("no_such_tool", ["no_such_tool"])
    except ToolNotFound:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ToolNotFound")
    try:
        registry.validate_allowed("calculator", ["web_search"])
    except ToolNotAllowed as exc:
        assert "denied" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ToolNotAllowed")


def test_permission_denial_does_not_bypass_budget() -> None:
    """B8: repeated denials still consume the iteration/LLM-call budget."""
    decisions = [_decision_call("calculator", {"expression": "1+1"}) for _ in range(10)]
    decisions.append(_decision_finish())
    provider = ScriptedProvider(decisions)
    runtime = AgentRuntime(
        provider=provider,
        tool_registry=CountingRegistry(),
        trace=ExecutionTrace("r"),
        max_iterations=3,
    )
    _run(runtime, _agent(["web_search"]))
    assert provider.calls == 3  # iteration cap respected
    assert len(_events(runtime, "TOOL_DENIED")) == 3


def test_authorised_tool_argument_validation_still_applies() -> None:
    """B9: the existing argument schema still rejects bad calls."""
    registry = ToolRegistry(mode="auto")
    with_registry = CountingRegistry()
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            [_decision_call("calculator", {"not_expression": "1+1"}), _decision_finish()]
        ),
        tool_registry=with_registry,
        trace=ExecutionTrace("r"),
    )
    _d, _s, evidence, used = _run(runtime, _agent(["calculator"]))
    # the tool is authorised, so it reaches the executor, which validates args
    assert with_registry.calls == []
    assert used == ["calculator"] or used == []
    assert all(e.source_id == "" for e in evidence)
    assert registry.validate  # sanity: registry object still usable


def test_advertised_tools_are_only_the_authorised_ones() -> None:
    """B10: the LLM prompt advertises only the agent's authorised tools."""
    provider = ScriptedProvider([_decision_finish()])
    runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry(mode="auto"))
    _run(runtime, _agent(["web_search"]))
    prompt = provider.prompts[0]
    advert = prompt.split("Available tools:", 1)[1].split("\n", 1)[0]
    assert "web_search" in advert
    assert "calculator" not in advert and "mock_search" not in advert


def test_empty_tool_list_prompt_says_no_permission() -> None:
    provider = ScriptedProvider([_decision_finish()])
    runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry(mode="auto"))
    _run(runtime, _agent([]))
    assert "no tool permission" in provider.prompts[0]


def test_denial_event_is_structured() -> None:
    """B7: the refusal carries agent, tool, reason and attempt."""
    runtime = AgentRuntime(
        provider=ScriptedProvider(
            [_decision_call("calculator", {"expression": "1+1"}), _decision_finish()]
        ),
        tool_registry=CountingRegistry(),
        trace=ExecutionTrace("r"),
    )
    _run(runtime, _agent(["web_search"], agent_id="agent_x"))
    event = _events(runtime, "TOOL_DENIED")[0]
    assert event.agent_id == "agent_x"
    assert event.metadata["tool"] == "calculator"
    assert event.metadata["denial_reason"] == "tool_not_allowed"
    assert event.metadata["attempt"] == 1
    assert event.metadata["outcome"] == "denied"


def test_budget_exhaustion_yields_explicit_partial_deliverable() -> None:
    """A/E: hitting max_tool_calls without a finish must produce an explicit
    partial deliverable built from real tool output — never a fabricated success."""
    decisions = [_decision_call("web_search", {"query": f"q{i}"}) for i in range(4)]
    provider = ScriptedProvider(decisions)
    registry = CountingRegistry()
    runtime = AgentRuntime(
        provider=provider,
        tool_registry=registry,
        max_tool_calls=2,
        max_iterations=4,
        trace=ExecutionTrace("r"),
    )
    deliverable, _sources, _evidence, used, partial = runtime._real_execution(
        _agent(["web_search"]), _context(), _Task()
    )
    # exactly the budget's worth of tool calls executed; no denial (all authorised)
    assert len(registry.calls) == 2
    assert used == ["web_search", "web_search"]
    assert _events(runtime, "TOOL_DENIED") == []
    # explicit partial, not a fake success
    assert "partial" in deliverable.title.lower()
    assert "budget" in deliverable.summary.lower()
    # the partial is grounded in the real tool output, not invented prose
    assert deliverable.key_points
    assert any("result for q" in kp for kp in deliverable.key_points)
    # R5: the partial flag is raised so the session can mark it honestly
    assert partial is True


# ---------------------------------------------------------------------------
# C. regression: mock mode unchanged + end-to-end offline scenario
# ---------------------------------------------------------------------------


def test_mock_mode_still_invokes_declared_tools(tmp_path) -> None:
    """C: offline runs keep the pre-fetch behaviour (unchanged by P610-1)."""
    session = execute_task(
        "分析某市场并设计产品方案",
        provider=None,
        tool_mode="mock",
        timeout=None,
        max_tool_calls=3,
        max_iterations=2,
    )
    assert session.status in {SessionStatus.SUCCESS, SessionStatus.PARTIAL_SUCCESS}
    tool_events = [e for e in session.trace.events if e.type == "TOOL_CALLED"]
    assert tool_events, "offline runs must still call their declared tools"
    assert all((e.metadata or {}).get("outcome") in {"ok", "error"} for e in tool_events)


def test_offline_scenario_a_produces_sources_without_network(tmp_path) -> None:
    """C: end-to-end offline Scenario A still yields artifacts/report (no network)."""
    from validation.scenarios import get_scenario

    scenario = get_scenario("A")
    session = execute_task(
        scenario.task,
        provider=None,
        tool_mode="mock",
        timeout=None,
        max_tool_calls=6,
        max_iterations=4,
    )
    assert session.final_artifact is not None
    markdown = session.final_artifact.to_markdown()
    assert "## Executive Summary" in markdown
    assert session.status in {SessionStatus.SUCCESS, SessionStatus.PARTIAL_SUCCESS}


# ---------------------------------------------------------------------------
# helpers used above
# ---------------------------------------------------------------------------


def _decision_call(tool: str, arguments: dict) -> AgentDecision:
    return AgentDecision(
        action="call_tool", tool_call=ToolCall(tool_name=tool, arguments=arguments)
    )


def _decision_finish(claim: str = "a claim") -> AgentDecision:
    return AgentDecision(
        action="finish",
        deliverable=AgentDeliverable(
            title="t", summary="after tools", key_points=[claim], sources=[]
        ),
    )


def _raise():
    raise RuntimeError("provider blew up mid-attempt")

