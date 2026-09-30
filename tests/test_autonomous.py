"""v0.4.0 tests — Autonomous Task Completion.

Covers: TaskExecutionSession lifecycle, AgentArtifact, context assembly,
real upstream-result passing (the key collaboration test), artifact dependency
chains, ArtifactAssembler, CompletionCriteria, execution trace, retry/replan
integration, partial failure, three dynamic tasks and the upgraded Live View.
All offline and deterministic. The pre-existing 110 tests must keep passing.
"""

import sys
from pathlib import Path

import pytest

from app.llm.provider import MockLLMProvider
from app.models.task import Task
from app.runtime.artifacts import AgentArtifact, ArtifactType
from app.runtime.context import assemble_agent_context
from app.runtime.session import CompletionCriteria, SessionStatus, execute_task
from app.scheduler.models import ExecutionContext
from app.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TASK_SOFTWARE = "设计一个 FastAPI 电商后端系统"
TASK_COMPLEX = "分析 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案。"
TASK_STRATEGY = "制定 SaaS 产品进入某行业的市场策略"


class RecordingProvider(MockLLMProvider):
    """Mock provider that remembers every prompt it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def structured_completion(self, prompt, response_model):
        self.prompts.append(prompt)
        return super().structured_completion(prompt, response_model)


def prompt_for(provider: RecordingProvider, role_name: str) -> str:
    matches = [p for p in provider.prompts if f"ROLE: {role_name}" in p]
    assert matches, f"no prompt captured for {role_name}"
    return matches[0]


# ---------------------------------------------------------------------------
# Session lifecycle & artifacts
# ---------------------------------------------------------------------------


def test_session_lifecycle_and_ids():
    session = execute_task(TASK_SOFTWARE)
    assert session.run_id.startswith("run_")
    assert session.status is SessionStatus.SUCCESS
    assert session.started_at is not None and session.finished_at is not None
    assert session.finished_at >= session.started_at


def test_session_produces_artifact_per_agent():
    session = execute_task(TASK_SOFTWARE)
    assert len(session.artifacts) == len(session.plan.agents)
    for artifact in session.artifacts:
        assert isinstance(artifact, AgentArtifact)
        assert artifact.artifact_id == f"artifact_{artifact.agent_id}"
        assert artifact.content
        assert artifact.created_at


def test_artifact_types_follow_expected_outputs():
    session = execute_task(TASK_SOFTWARE)
    by_id = {artifact.agent_id: artifact for artifact in session.artifacts}
    assert by_id["system_architect"].output_type is ArtifactType.ARCHITECTURE
    assert by_id["test_engineer"].output_type is ArtifactType.TEST_REPORT
    assert by_id["database_engineer"].output_type is ArtifactType.DATABASE_DESIGN


def test_offline_artifacts_are_marked_offline_mock():
    session = execute_task(TASK_SOFTWARE)
    for artifact in session.artifacts:
        assert artifact.metadata["source_type"] == "offline_mock"
    assert session.final_artifact.metadata["source_type"] == "offline_mock"


# ---------------------------------------------------------------------------
# Context assembly & real collaboration
# ---------------------------------------------------------------------------


def test_context_assembly_gives_transitive_upstream_artifacts():
    session = execute_task(TASK_SOFTWARE)
    agent = next(a for a in session.plan.agents if a.id == "test_engineer")
    context = ExecutionContext(
        task=Task(description=session.task),
        topology=session.plan.topology,
        agents={a.id: a for a in session.plan.agents},
        results=session.agent_results,
    )
    agent_context = assemble_agent_context(agent, context)
    types = {artifact.output_type for artifact in agent_context.upstream_artifacts}
    assert {ArtifactType.ARCHITECTURE, ArtifactType.IMPLEMENTATION_PLAN} <= types
    assert agent_context.upstream_artifact_ids == [
        artifact.artifact_id for artifact in session.artifacts
        if artifact.agent_id != "test_engineer"
    ]


def test_context_excludes_unrelated_agents():
    session = execute_task(TASK_SOFTWARE)
    agent = next(a for a in session.plan.agents if a.id == "test_engineer")
    context = ExecutionContext(
        task=Task(description=session.task),
        topology=session.plan.topology,
        agents={a.id: a for a in session.plan.agents},
        results=session.agent_results,
    )
    agent_context = assemble_agent_context(agent, context)
    assert agent_context.expected_output == "test_plan"
    # A research artifact never exists in a software session — the dependency
    # graph itself prevents unrelated context from leaking in.
    assert ArtifactType.RESEARCH_FINDINGS not in {
        artifact.output_type for artifact in agent_context.upstream_artifacts
    }


def test_downstream_agent_receives_upstream_artifact():
    """THE collaboration proof: upstream structured data flows into the
    downstream prompt, and both survive into the final artifact."""
    provider = RecordingProvider()
    session = execute_task(TASK_SOFTWARE, provider=provider)

    architect_prompt = prompt_for(provider, "System Architect")
    backend_prompt = prompt_for(provider, "Backend Developer")
    test_prompt = prompt_for(provider, "Test Engineer")
    entry_prompt = prompt_for(provider, "Requirement Analyst")

    # The requirement analyst is the entry agent; the architect already reads it.
    assert "(none" in entry_prompt
    assert "requirements_scope" in architect_prompt
    assert "architecture_decision" in backend_prompt  # architect -> backend
    assert "architecture_decision" in test_prompt  # architect -> ... -> test
    assert "backend_plan" in test_prompt  # backend -> test

    markdown = session.final_artifact.to_markdown()
    assert "architecture_decision" in markdown
    assert "backend_plan" in markdown
    assert "test_strategy" in markdown


def test_artifact_dependency_chain_matches_graph():
    session = execute_task(TASK_SOFTWARE)
    by_id = {artifact.agent_id: artifact for artifact in session.artifacts}
    test_artifact = by_id["test_engineer"]
    for upstream in ("system_architect", "database_engineer", "backend_developer"):
        assert f"artifact_{upstream}" in test_artifact.dependencies
    assert by_id["requirement_analyst"].dependencies == []  # entry agent


# ---------------------------------------------------------------------------
# Final artifact assembly
# ---------------------------------------------------------------------------


def test_assembler_orders_sections_by_execution_layers():
    session = execute_task(TASK_SOFTWARE)
    # v0.6 inserts synthesis sections (agent_id="synthesis") before the agent
    # sections; the execution-layer order guarantee still applies to agents.
    flat_layers = [agent_id for layer in session.plan.execution_layers for agent_id in layer]
    order = [
        section.agent_id
        for section in session.final_artifact.sections
        if section.agent_id in flat_layers
    ]
    assert order == [aid for aid in flat_layers if aid in order]


def test_final_markdown_is_truly_readable():
    session = execute_task(TASK_STRATEGY)
    markdown = session.final_artifact.to_markdown()
    assert markdown.startswith("# Final Deliverable")
    assert "## Executive Summary" in markdown
    assert markdown.count("## ") >= 4  # summary + one section per artifact
    assert session.run_id in markdown
    assert len(markdown) > 1200
    assert "Contributing agents:" in markdown
    assert "offline mock" in markdown


def test_final_artifact_sections_are_dynamic_per_task():
    software = execute_task(TASK_SOFTWARE).final_artifact
    strategy = execute_task(TASK_STRATEGY).final_artifact
    software_types = {section.output_type for section in software.sections}
    strategy_types = {section.output_type for section in strategy.sections}
    assert "test_report" in software_types and "test_report" not in strategy_types
    assert "proposal" in strategy_types and "proposal" not in software_types


def test_save_markdown_writes_readable_file(tmp_path):
    session = execute_task(TASK_SOFTWARE)
    path = session.save_markdown(tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("# Final Deliverable")


# ---------------------------------------------------------------------------
# Completion criteria
# ---------------------------------------------------------------------------


def test_completion_criteria_success_requires_all_agents():
    session = execute_task(TASK_SOFTWARE)
    assert session.status is SessionStatus.SUCCESS
    criteria = CompletionCriteria(minimum_successful_agents=5, allow_partial=True)
    session2 = execute_task(TASK_SOFTWARE, criteria=criteria)
    assert session2.status is SessionStatus.SUCCESS


def test_completion_criteria_partial_on_failure():
    session = execute_task(TASK_SOFTWARE, fail_agent_ids={"database_engineer"})
    assert session.status is SessionStatus.PARTIAL_SUCCESS
    statuses = {aid: r.status.value for aid, r in session.agent_results.items()}
    assert statuses["database_engineer"] == "failed"
    assert statuses["backend_developer"] == "skipped"
    assert statuses["test_engineer"] == "skipped"


def test_completion_criteria_can_forbid_partial():
    criteria = CompletionCriteria(allow_partial=False)
    session = execute_task(
        TASK_SOFTWARE, criteria=criteria, fail_agent_ids={"database_engineer"}
    )
    assert session.status is SessionStatus.FAILED


def test_completion_criteria_required_artifact_types():
    criteria = CompletionCriteria(required_artifact_types=["architecture", "test_report"])
    ok = execute_task(TASK_SOFTWARE, criteria=criteria)
    assert ok.status is SessionStatus.SUCCESS  # both types produced

    strict = CompletionCriteria(
        required_artifact_types=["architecture", "test_report"], allow_partial=True
    )
    partial = execute_task(
        TASK_SOFTWARE, criteria=strict, fail_agent_ids={"database_engineer"}
    )
    assert partial.status is SessionStatus.PARTIAL_SUCCESS  # test_report missing
    assert "architecture" in {a.output_type.value for a in partial.artifacts}


def test_all_agents_failing_means_failed():
    session = execute_task(
        TASK_SOFTWARE,
        fail_agent_ids={
            "requirement_analyst",
            "system_architect",
            "database_engineer",
            "backend_developer",
            "test_engineer",
        },
    )
    assert session.status is SessionStatus.FAILED
    assert session.artifacts == []


# ---------------------------------------------------------------------------
# Execution trace
# ---------------------------------------------------------------------------


def test_event_trace_covers_full_lifecycle():
    session = execute_task(TASK_SOFTWARE)
    types = [event.type for event in session.trace.events]
    for expected in (
        "TASK_STARTED",
        "TEAM_FORMED",
        "AGENT_READY",
        "AGENT_STARTED",
        "TOOL_CALLED",
        "AGENT_OUTPUT",
        "ARTIFACT_CREATED",
        "TASK_COMPLETED",
    ):
        assert expected in types
    assert types[0] == "TASK_STARTED" and types[-1] == "TASK_COMPLETED"


def test_trace_events_are_structured_and_bounded():
    session = execute_task(TASK_SOFTWARE)
    for event in session.trace.events:
        assert event.event_id.startswith("evt_")
        assert event.run_id == session.run_id
        assert len(event.message) <= 300  # structured messages, never CoT


def test_tool_called_events_record_offline_marker():
    session = execute_task(TASK_SOFTWARE)
    tool_events = session.trace.of_type("TOOL_CALLED")
    assert tool_events, "schema_validator / code_analysis should have run"
    assert all(event.metadata["offline"] is True for event in tool_events)


# ---------------------------------------------------------------------------
# Retry / Replan integration (existing engine, unchanged)
# ---------------------------------------------------------------------------


def test_retry_integration_recovers_the_run():
    session = execute_task(
        TASK_SOFTWARE, failures_before_success={"database_engineer": 1}
    )
    assert session.status is SessionStatus.SUCCESS
    retries = session.trace.of_type("AGENT_RETRY")
    assert [event.agent_id for event in retries] == ["database_engineer"]
    result = session.agent_results["database_engineer"]
    assert len(result.attempts) == 2
    assert len(session.artifacts) == 5  # nothing lost


def test_replan_integration_skips_downstream():
    session = execute_task(TASK_SOFTWARE, fail_agent_ids={"database_engineer"})
    replanned = session.trace.of_type("AGENT_REPLANNED")
    assert [event.agent_id for event in replanned] == ["database_engineer"]
    assert session.agent_results["backend_developer"].status.value == "skipped"
    # partial artifacts still assemble into a readable final deliverable
    assert session.final_artifact is not None
    assert "System Architect" in session.final_artifact.to_markdown()


# ---------------------------------------------------------------------------
# Three dynamic tasks, end to end
# ---------------------------------------------------------------------------


def test_research_task_session():
    session = execute_task("分析 AI Agent 市场竞争格局")
    assert session.status is SessionStatus.SUCCESS
    types = {artifact.output_type for artifact in session.artifacts}
    assert ArtifactType.RESEARCH_FINDINGS in types
    assert ArtifactType.REPORT in types  # Report Writer exists for research tasks


def test_software_task_has_no_forced_writer():
    session = execute_task(TASK_SOFTWARE)
    roles = {agent.role.name for agent in session.plan.agents}
    assert "Report Writer" not in roles  # Writer is not a universal agent
    types = {artifact.output_type for artifact in session.artifacts}
    assert {
        ArtifactType.REQUIREMENTS,
        ArtifactType.ARCHITECTURE,
        ArtifactType.IMPLEMENTATION_PLAN,
        ArtifactType.TEST_REPORT,
    } <= types


def test_business_task_session_with_proposal():
    session = execute_task(TASK_STRATEGY)
    assert session.status is SessionStatus.SUCCESS
    types = {artifact.output_type for artifact in session.artifacts}
    assert ArtifactType.PROPOSAL in types  # Proposal Writer exists for strategy tasks


def test_offline_e2e_complex_task():
    session = execute_task(TASK_COMPLEX)
    assert session.status is SessionStatus.SUCCESS
    assert len(session.plan.agents) >= 5
    markdown = session.final_artifact.to_markdown()
    assert "Executive Summary" in markdown
    for artifact in session.artifacts:
        assert artifact.structured_data  # every agent contributed real data


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def test_ui_live_renders_initial_state():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(REPO_ROOT / "app" / "ui_live.py")).run(timeout=30)
    assert not at.exception
    assert any("AI Team Live View" in (item.value or "") for item in at.title)
    assert any("离线" in (item.value or "") for item in at.info)


def test_tool_registry_unchanged_for_v02():
    assert set(ToolRegistry(mode="auto").available()) >= {"web_search", "mock_search"}
