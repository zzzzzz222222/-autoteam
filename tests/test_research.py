"""Tests for the v0.2.0 research runtime (decomposition, agents, tools, report).

These exercise the new layer on top of the v0.1.0 engine. All run offline with
the deterministic ``MockLLMProvider`` and ``mock`` tool mode, so no API key or
network is required. The existing v0.1.0 tests must still pass alongside these.
"""

import asyncio

from app.llm.provider import MockLLMProvider, get_llm_provider
from app.models.task import Task
from app.models.topology import TopologyType
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.decomposer import TaskDecomposer, build_team, build_topology
from app.runtime.models import (
    CompetitorFindings,
    ReportDraft,
    ResearchFindings,
    TechnologyFindings,
)
from app.runtime.orchestrator import ResearchOrchestrator, build_report
from app.runtime.result_store import ResultStore
from app.scheduler.models import ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler
from app.tools.registry import ToolRegistry, mock_search


class RecordingProvider(MockLLMProvider):
    """Mock provider that remembers every prompt it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def structured_completion(self, prompt, response_model):
        self.prompts.append(prompt)
        return super().structured_completion(prompt, response_model)


def test_decomposer_returns_plan_offline():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="分析某市场"))
    assert plan.subtasks, "plan should contain subtasks"
    roles = {sub.target_role for sub in plan.subtasks}
    assert "Research Agent" in roles
    assert "Report Writer" in roles


def test_build_team_and_topology_is_valid_dag():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    topology = build_topology(agents, plan)
    assert topology.type is TopologyType.HIERARCHICAL
    assert topology.agents == [agent.id for agent in agents]
    # mock plan: 3 parallel analysts feeding 1 report writer
    assert len(topology.parallel_layers) == 2
    assert len(topology.parallel_layers[0]) == 3
    assert len(topology.parallel_layers[1]) == 1


def test_build_team_sanitizes_capabilities():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    for agent in agents:
        # AgentSpec validates capabilities against the enum; construction would fail otherwise
        assert all(c.value for c in agent.role.capabilities)


def test_agent_runtime_returns_structured_output():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    topology = build_topology(agents, plan)
    store = ResultStore()
    runtime = AgentRuntime(
        provider=MockLLMProvider(), tool_registry=ToolRegistry(mode="mock"), store=store
    )
    results = asyncio.run(
        AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=0)).run(
            Task(description="x"), topology, agents
        )
    )
    for agent_id, result in results.items():
        assert result.status is ExecutionStatus.SUCCESS
        assert isinstance(
            result.output,
            (ResearchFindings, CompetitorFindings, TechnologyFindings, ReportDraft),
        )


def test_result_passing_reaches_downstream_prompt():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    topology = build_topology(agents, plan)
    provider = RecordingProvider()
    runtime = AgentRuntime(
        provider=provider, tool_registry=ToolRegistry(mode="mock"), store=ResultStore()
    )
    asyncio.run(
        AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=0)).run(
            Task(description="x"), topology, agents
        )
    )
    # At least one downstream prompt must embed the upstream findings text.
    assert any("[mock] summary" in prompt for prompt in provider.prompts)


def test_agent_runtime_retries_then_succeeds():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    topology = build_topology(agents, plan)
    research_id = next(a.id for a in agents if a.role.name == "Research Agent")
    runtime = AgentRuntime(
        provider=MockLLMProvider(),
        tool_registry=ToolRegistry(mode="mock"),
        store=ResultStore(),
        failures_before_success={research_id: 1},
    )
    results = asyncio.run(
        AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=2)).run(
            Task(description="x"), topology, agents
        )
    )
    assert results[research_id].status is ExecutionStatus.SUCCESS
    assert len(results[research_id].attempts) == 2


def test_agent_failure_skips_downstream():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    topology = build_topology(agents, plan)
    research_id = next(a.id for a in agents if a.role.name == "Research Agent")
    report_id = next(a.id for a in agents if a.role.name == "Report Writer")
    runtime = AgentRuntime(
        provider=MockLLMProvider(),
        tool_registry=ToolRegistry(mode="mock"),
        store=ResultStore(),
        fail_agent_ids={research_id},
    )
    results = asyncio.run(
        AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=0)).run(
            Task(description="x"), topology, agents
        )
    )
    assert results[research_id].status is ExecutionStatus.FAILED
    assert results[report_id].status is ExecutionStatus.SKIPPED


def test_tool_registry_mock_is_offline():
    result = mock_search("跨境电商")
    assert result.offline is True
    assert len(result.results) == 3
    registry = ToolRegistry(mode="mock")
    assert registry.run("web_search", "q").offline is True


def test_provider_fallback_without_key_is_mock(monkeypatch):
    # Isolate from a local .env: "without key" must actually mean no key.
    monkeypatch.delenv("AUTOTEAM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("AUTOTEAM_LLM_PROVIDER", "mock")
    provider = get_llm_provider()
    assert isinstance(provider, MockLLMProvider)


def test_full_offline_run_produces_report():
    report = asyncio.run(
        ResearchOrchestrator(
            provider=MockLLMProvider(), tool_mode="mock", store=ResultStore()
        ).run("分析中国跨境电商 SaaS 市场")
    )
    assert report.task
    assert report.summary
    assert isinstance(report.market_overview, ResearchFindings)
    assert isinstance(report.competitors, CompetitorFindings)
    assert isinstance(report.technology, TechnologyFindings)
    assert report.sources, "report should aggregate sources from the findings"


def test_build_report_handles_missing_sections():
    plan = TaskDecomposer(MockLLMProvider()).decompose(Task(description="x"))
    agents = build_team(plan)
    topology = build_topology(agents, plan)
    research_id = next(a.id for a in agents if a.role.name == "Research Agent")
    runtime = AgentRuntime(
        provider=MockLLMProvider(),
        tool_registry=ToolRegistry(mode="mock"),
        store=ResultStore(),
        fail_agent_ids={research_id},
    )
    results = asyncio.run(
        AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=0)).run(
            Task(description="x"), topology, agents
        )
    )
    report = build_report(Task(description="x"), plan, agents, results)
    assert report.market_overview is None
    assert report.competitors is not None
    assert report.summary  # synthesized fallback, not empty
