"""v0.5.0 tests — Real-World Agent Execution.

Covers: provider errors + fallback, safe calculator, dual-mode web search
(structured results, no fabricated URLs, real adapter with timeout/exception
handling/response validation), local knowledge with path-traversal rejection,
structured tool calling (ToolCall schema, limits, unknown tool, bad arguments),
Source/Evidence models and validation, artifact validation, evidence flow into
the final deliverable, and the offline real_world_demo. All CI tests run fully
offline — no API key, no network. All pre-existing 138 tests keep passing.
"""

import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.llm.provider import MockLLMProvider, ProviderError, get_llm_provider
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.artifacts import (
    AgentArtifact,
    AgentDecision,
    ArtifactType,
    Evidence,
    Source,
    ToolCall,
)
from app.runtime.session import SessionStatus, execute_task
from app.runtime.validation import ArtifactValidationError, validate_artifact
from app.tools.calculator import safe_calculate
from app.tools.local_knowledge import search_knowledge
from app.tools.registry import (
    ToolExecutionError,
    ToolNotFound,
    ToolRegistry,
    ToolValidationError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_SOFTWARE = "设计一个 FastAPI 电商后端系统"


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def test_get_llm_provider_mock_by_default(monkeypatch):
    for name in (
        "AUTOTEAM_LLM_PROVIDER",
        "AUTOTEAM_API_KEY",
        "LLM_API_KEY",
        "AUTOTEAM_LLM_MODEL",
        "AUTOTEAM_LLM_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    assert isinstance(get_llm_provider(), MockLLMProvider)


def test_provider_error_message_never_contains_key():
    from app.llm.provider import OpenAILLMProvider

    real = OpenAILLMProvider.__new__(OpenAILLMProvider)
    real._client = None  # any internal failure becomes a ProviderError
    real.model = "m"
    with pytest.raises(ProviderError) as excinfo:
        real.structured_completion("p", BaseModel)
    assert "LLM provider call failed" in str(excinfo.value)
    assert "sk-" not in str(excinfo.value)


class FailingRealProvider:
    """Acts like a misconfigured real provider (auth failure)."""

    def structured_completion(self, prompt, response_model):
        raise ProviderError("LLM provider call failed: AuthenticationError")


def test_session_provider_fallback_reruns_with_mock():
    session = execute_task(TASK_SOFTWARE, provider=FailingRealProvider(), provider_fallback=True)
    assert session.status is SessionStatus.SUCCESS
    assert session.final_artifact.metadata.get("provider_fallback") is True
    assert any(
        event.type == "PROVIDER_FALLBACK" for event in session.trace.events
    )


def test_session_without_fallback_reports_provider_failure():
    session = execute_task(TASK_SOFTWARE, provider=FailingRealProvider())
    assert session.status is not SessionStatus.SUCCESS
    assert any(
        "LLM provider call failed" in (r.error or "") for r in session.agent_results.values()
    )


# ---------------------------------------------------------------------------
# Calculator (safe, no eval)
# ---------------------------------------------------------------------------


def test_calculator_basic_operations():
    assert safe_calculate("25 * 4").value == 100
    assert safe_calculate("(100 - 20) / 4").value == 20
    assert safe_calculate("10 % 3").value == 1
    assert safe_calculate("-5 + 2").value == -3


def test_calculator_rejects_non_arithmetic():
    assert safe_calculate("__import__('os').system('dir')").error
    assert safe_calculate("2 ** 64").error
    assert safe_calculate("some_name + 1").error
    assert safe_calculate("").error


def test_calculator_division_by_zero_is_structured():
    result = safe_calculate("1 / 0")
    assert result.value is None
    assert result.error == "division by zero"


def test_registry_execute_calculator_returns_value():
    registry = ToolRegistry(mode="auto")
    result = registry.execute("calculator", {"expression": "(100 - 20) / 4"})
    assert result.value == 20
    assert result.tool == "calculator"


def test_registry_validate_unknown_tool_raises():
    with pytest.raises(ToolNotFound):
        ToolRegistry().validate("does_not_exist")


def test_registry_execute_missing_arguments_raises():
    with pytest.raises(ToolValidationError):
        ToolRegistry().execute("calculator", {"wrong": "1"})
    with pytest.raises(ToolValidationError):
        ToolRegistry().execute("web_search", {})


def test_registry_execute_wraps_internal_failure(monkeypatch):
    registry = ToolRegistry(mode="auto")

    def broken(expression):  # pragma: no cover - monkeypatched
        raise RuntimeError("boom")

    monkeypatch.setitem(registry._tools, "calculator", broken)
    with pytest.raises(ToolExecutionError):
        registry.execute("calculator", {"expression": "1"})


def test_registry_run_never_raises_on_tool_failure(monkeypatch):
    registry = ToolRegistry(mode="auto")

    def broken(expression):
        raise RuntimeError("boom")

    monkeypatch.setitem(registry._tools, "calculator", broken)
    result = registry.run("calculator", "1")
    assert result.error  # structured, not an exception


# ---------------------------------------------------------------------------
# Web search: offline + real adapter
# ---------------------------------------------------------------------------


def test_web_search_offline_is_marked_and_has_no_fake_urls(monkeypatch):
    for name in ("AUTOTEAM_WEB_SEARCH_URL", "AUTOTEAM_WEB_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    registry = ToolRegistry(mode="auto")
    result = registry.run("web_search", "ai agent market")
    assert result.offline is True
    assert len(result.search_results) == 3
    for item in result.search_results:
        assert item.source == "offline_mock"
        assert item.url == ""  # real URLs are never fabricated


def test_web_search_real_adapter_success(monkeypatch):
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://search.example.com/api")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-test-key-123")
    payload = {
        "results": [
            {"title": "Report", "url": "https://example.com/report", "snippet": "market grows"},
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return str(payload).replace("'", '"').encode()

    def fake_urlopen(request, timeout):
        assert timeout == 10
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = ToolRegistry(mode="auto").run("web_search", "ai agent market")
    assert result.offline is False
    assert result.search_results[0].url == "https://example.com/report"
    assert result.search_results[0].source == "web"
    assert result.error is None


def test_web_search_real_timeout_degrades_to_offline(monkeypatch):
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://search.example.com/api")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-test-key-123")

    def slow_urlopen(request, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", slow_urlopen)
    result = ToolRegistry(mode="auto").run("web_search", "query")
    assert result.offline is True
    assert "web search failed" in result.error
    assert "sk-test-key-123" not in (result.error or "")


def test_web_search_real_response_validation(monkeypatch):
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://search.example.com/api")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-test-key-123")

    class BadResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"results": "not-a-list"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: BadResponse())
    result = ToolRegistry(mode="auto").run("web_search", "query")
    assert result.offline is True
    assert result.error  # structured degradation, no crash


# ---------------------------------------------------------------------------
# Local knowledge tool
# ---------------------------------------------------------------------------


@pytest.fixture()
def knowledge_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "knowledge"
    workspace.mkdir()
    (workspace / "market_notes.md").write_text(
        "# Market notes\nSMB buyers want affordable AI agent tooling.", encoding="utf-8"
    )
    monkeypatch.setenv("AUTOTEAM_WORKSPACE_DIR", str(workspace))
    return workspace


def test_local_knowledge_reads_workspace(knowledge_workspace):
    result = ToolRegistry(mode="auto").run("local_knowledge", "SMB agent")
    assert any("market_notes.md" in item for item in result.results)


def test_local_knowledge_rejects_path_traversal(knowledge_workspace):
    result = ToolRegistry(mode="auto").run("local_knowledge", "anything")
    # direct traversal attempt through the structured path-validation guard
    outcome = search_knowledge("x", relative_path="../../.env")
    assert outcome.error and "escapes" in outcome.error
    assert result is not None


def test_local_knowledge_rejects_disallowed_extension(knowledge_workspace):
    (knowledge_workspace / "script.py").write_text("print('hi')", encoding="utf-8")
    outcome = search_knowledge("x", relative_path="script.py")
    assert outcome.error and "not allowed" in outcome.error


def test_local_knowledge_rejects_secret_named_files(knowledge_workspace):
    (knowledge_workspace / "my_credentials.md").write_text("KEY=1", encoding="utf-8")
    outcome = search_knowledge("KEY", relative_path="my_credentials.md")
    assert outcome.error and "secret" in outcome.error


def test_local_knowledge_missing_workspace_is_structured(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOTEAM_WORKSPACE_DIR", str(tmp_path / "missing"))
    result = ToolRegistry(mode="auto").run("local_knowledge", "anything")
    assert result.error and "offline_mock" in result.error


# ---------------------------------------------------------------------------
# Tool calling loop (real-LLM mode, scripted provider)
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Duck-typed real provider returning pre-built decisions in order."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.prompts: list[str] = []

    def structured_completion(self, prompt, response_model):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.decisions) - 1)
        item = self.decisions[index]
        if isinstance(item, BaseModel):
            return item
        return response_model.model_validate(item)


def _decision(action, tool=None, args=None, deliverable=None):
    return AgentDecision(
        action=action,
        tool_call=ToolCall(tool_name=tool, arguments=args or {}) if tool else None,
        deliverable=deliverable,
    )


def _finish_deliverable():
    return {
        "title": "Backend plan",
        "summary": "[real] deliverable after tool use",
        "key_points": ["uses fastapi routers"],
        "structured_data": {"backend_plan": "fastapi_router_service_layout"},
        "sources": [],
    }


def test_tool_calling_loop_executes_and_finishes(monkeypatch):
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_API_KEY", raising=False)
    provider = ScriptedProvider(
        [
            _decision("call_tool", "web_search", {"query": "fastapi backend patterns"}),
            _decision("finish", deliverable=_finish_deliverable()),
        ]
    )
    runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry(mode="auto"))
    from app.runtime.context import AgentExecutionContext

    context = AgentExecutionContext(
        agent_id="system_architect",
        role_name="System Architect",
        task="设计一个 FastAPI 电商后端系统",
        expected_output="architecture_design",
    )
    deliverable, sources, evidence, used, _partial = runtime._real_execution(
        _fake_agent("System Architect"), context, _fake_task("设计一个 FastAPI 电商后端系统")
    )
    assert used == ["web_search"]
    assert deliverable.structured_data == {"backend_plan": "fastapi_router_service_layout"}
    assert len(sources) == 3  # offline stub search results became provenance
    assert all(source.source_type == "offline_mock" for source in sources)
    source_ids = {s.id for s in sources}
    assert evidence
    for ev in evidence:
        if ev.source_id:
            assert ev.source_id in source_ids  # no link to an unknown source
            assert ev.review_status != "verified"  # a link is not a verification
        else:
            assert ev.review_status == "unsupported"  # honest unbound claim


def _fake_agent(name: str):
    from app.models.agent import AgentRole
    from app.models.capability import CapabilityName
    from app.runtime.agent_factory import DynamicAgentSpec

    return DynamicAgentSpec(
        id=name.lower().replace(" ", "_"),
        role=AgentRole(
            name=name, capabilities=[CapabilityName.SYSTEM_ARCHITECTURE], goal="test"
        ),
        tools=["web_search"],
        system_prompt="test",
    )


def _fake_task(description: str):
    from app.models.task import Task

    return Task(description=description)


def test_tool_calling_respects_max_tool_calls(monkeypatch):
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_API_KEY", raising=False)
    call_forever = _decision("call_tool", "web_search", {"query": "q"})
    provider = ScriptedProvider([call_forever])
    runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry(mode="auto"),
                           max_tool_calls=2, max_iterations=5)
    from app.runtime.context import AgentExecutionContext

    context = AgentExecutionContext(
        agent_id="a", role_name="A", task="t", expected_output="market_overview"
    )
    deliverable, sources, _evidence, used, _partial = runtime._real_execution(
        _fake_agent("A"), context, _fake_task("t")
    )
    assert len(used) == 2  # budget enforced
    assert len(provider.prompts) <= 5  # iteration bound enforced
    assert "partial" in deliverable.summary.lower()


def test_tool_calling_unknown_tool_is_structured_error(monkeypatch):
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_API_KEY", raising=False)
    provider = ScriptedProvider(
        [
            _decision("call_tool", "no_such_tool", {"query": "q"}),
            _decision("finish", deliverable=_finish_deliverable()),
        ]
    )
    from app.runtime.events import ExecutionTrace

    runtime = AgentRuntime(
        provider=provider,
        tool_registry=ToolRegistry(mode="auto"),
        trace=ExecutionTrace("run_unknown_tool"),
    )
    from app.runtime.context import AgentExecutionContext

    context = AgentExecutionContext(
        agent_id="a", role_name="A", task="t", expected_output="market_overview"
    )
    deliverable, _sources, _evidence, used, _partial = runtime._real_execution(
        _fake_agent("A"), context, _fake_task("t")
    )
    # v0.6.11 (P610-2): an unknown tool is rejected before execution, so it is
    # never reported as "used" - it is audited as a denial instead.
    assert used == []
    assert deliverable.structured_data  # the run continues despite the bad call
    denials = [e for e in runtime.trace.events if e.type == "TOOL_DENIED"]
    assert denials and denials[0].metadata["denial_reason"] == "unknown_tool"


def test_tool_calling_invalid_arguments_become_structured_errors():
    registry = ToolRegistry(mode="auto")
    with pytest.raises(ToolValidationError):
        registry.execute("calculator", {"not_expression": "1"})


def test_finish_without_deliverable_fails_instead_of_faking_success(monkeypatch):
    """A model that finishes with no deliverable and no tool output must FAIL,
    not be recorded as a successful empty artifact."""
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_API_KEY", raising=False)
    provider = ScriptedProvider([_decision("finish")])  # no deliverable
    runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry(mode="auto"))
    from app.runtime.context import AgentExecutionContext

    context = AgentExecutionContext(
        agent_id="a", role_name="A", task="t", expected_output="market_overview"
    )
    with pytest.raises(ProviderError):
        runtime._real_execution(_fake_agent("A"), context, _fake_task("t"))


def test_finish_without_deliverable_but_with_tools_is_partial(monkeypatch):
    """If tools did produce material, degrade to an explicitly partial artifact."""
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("AUTOTEAM_WEB_SEARCH_API_KEY", raising=False)
    provider = ScriptedProvider(
        [
            _decision("call_tool", "web_search", {"query": "q"}),
            _decision("finish"),
        ]
    )
    runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry(mode="auto"))
    from app.runtime.context import AgentExecutionContext

    context = AgentExecutionContext(
        agent_id="a", role_name="A", task="t", expected_output="market_overview"
    )
    deliverable, _sources, _evidence, used, _partial = runtime._real_execution(
        _fake_agent("A"), context, _fake_task("t")
    )
    assert used == ["web_search"]
    assert "partial" in deliverable.summary.lower()


# ---------------------------------------------------------------------------
# Evidence / Source models and validation
# ---------------------------------------------------------------------------


def _artifact_with(evidence=None, source_records=None, content="body") -> AgentArtifact:
    return AgentArtifact(
        artifact_id="artifact_x",
        agent_id="x",
        output_type=ArtifactType.ANALYSIS,
        title="t",
        content=content,
        source_records=source_records or [],
        evidence=evidence or [],
    )


def test_evidence_reference_must_exist():
    source = Source(id="source_001", source_type="offline_mock")
    bad = Evidence(claim="c", evidence="e", source_id="source_999")
    with pytest.raises(ArtifactValidationError) as excinfo:
        validate_artifact(_artifact_with(evidence=[bad], source_records=[source]))
    assert "InvalidEvidenceReference" in str(excinfo.value)


def test_evidence_with_valid_reference_passes():
    source = Source(id="source_001", source_type="offline_mock")
    good = Evidence(claim="c", evidence="e", source_id="source_001")
    validate_artifact(_artifact_with(evidence=[good], source_records=[source]))  # no raise


def test_offline_source_without_url_is_valid():
    validate_artifact(
        _artifact_with(source_records=[Source(id="s1", source_type="offline_mock", url="")])
    )


def test_non_http_url_is_rejected():
    bad_source = Source(id="s1", source_type="web", url="javascript:alert(1)")
    with pytest.raises(ArtifactValidationError):
        validate_artifact(_artifact_with(source_records=[bad_source]))


def test_artifact_schema_validation_rejects_empty_content():
    with pytest.raises(ArtifactValidationError):
        validate_artifact(_artifact_with(content="   "))


# ---------------------------------------------------------------------------
# Session integration: evidence flow, rejection, mode
# ---------------------------------------------------------------------------


def test_evidence_flows_into_final_deliverable():
    session = execute_task("分析 AI Agent 市场竞争格局")
    assert session.status is SessionStatus.SUCCESS
    final = session.final_artifact
    assert final.source_records, "search-using agents contribute provenance"
    assert final.evidence
    markdown = final.to_markdown()
    assert "## Evidence" in markdown and "## Sources" in markdown
    assert "Data source: offline_mock" in markdown
    for source in final.source_records:
        assert source.url == "" or source.url.startswith("http")


def test_session_rejects_invalid_artifacts(monkeypatch):
    def broken_build(self, agent, agent_context, deliverable, task, **kwargs):
        return AgentArtifact(
            artifact_id=f"artifact_{agent.id}",
            agent_id=agent.id or "x",
            output_type=ArtifactType.ANALYSIS,
            content="",  # schema-invalid on purpose
        )

    monkeypatch.setattr(AgentRuntime, "_build_artifact", broken_build)
    session = execute_task(TASK_SOFTWARE)
    assert session.artifacts == []
    assert session.trace.of_type("ARTIFACT_REJECTED")


def test_execution_mode_recorded():
    session = execute_task(TASK_SOFTWARE)
    assert session.provider_name == "MockLLMProvider"


def test_api_key_never_leaks_into_trace_or_artifacts(monkeypatch):
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://search.example.com/api")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-super-secret-key-42")

    def failing_urlopen(request, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    session = execute_task("分析 AI Agent 市场竞争格局")
    dumped = session.final_artifact.to_markdown() + str(
        [event.model_dump() for event in session.trace.events]
    )
    assert "sk-super-secret-key-42" not in dumped


def test_web_search_tavily_post_protocol(monkeypatch):
    """The real adapter must speak Tavily's protocol: POST + Bearer header +
    JSON body {"query": ...} + content field in results (fallback to snippet)."""
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-test-key-123")
    payload = {
        "results": [
            {
                "title": "AI agent report",
                "url": "https://example.com/ai-agents",
                "content": "Tavily-style content field",
            },
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return str(payload).replace("'", '"').encode()

    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        # urllib normalizes header names (Content-Type -> Content-type)
        captured["content_type"] = request.get_header("Content-Type") or request.get_header(
            "Content-type"
        )
        captured["body"] = request.data.decode() if request.data else ""
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = ToolRegistry(mode="auto").run("web_search", "ai agents")
    assert result.offline is False
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer sk-test-key-123"
    assert captured["content_type"] == "application/json"
    assert "ai agents" in captured["body"]
    assert result.search_results[0].snippet == "Tavily-style content field"
    assert result.search_results[0].source == "web"

    # degrade path: missing results must still fall back offline, never crash
    def bad_urlopen(request, timeout):
        class Bad:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"results": "nope"}'

        return Bad()

    monkeypatch.setattr("urllib.request.urlopen", bad_urlopen)
    degraded = ToolRegistry(mode="auto").run("web_search", "ai agents")
    assert degraded.offline is True
    assert degraded.error


def test_flatten_json_coerces_numeric_scalars():
    """Real LLMs emit int/float tool args (e.g. max_results=10) that the
    ToolCall / AgentDeliverable validators must coerce into str deterministically."""
    tool_call = ToolCall(
        tool_name="web_search",
        arguments={"query": "ai agents", "max_results": 10},
    )
    assert tool_call.arguments == {"query": "ai agents", "max_results": "10"}

    from app.runtime.artifacts import AgentDeliverable

    deliverable = AgentDeliverable(
        title="t",
        structured_data={"count": 3, "score": 0.5, "nested": {"a": 1}},
    )
    assert deliverable.structured_data == {
        "count": "3",
        "score": "0.5",
        "nested": '{"a": 1}',
    }


# ---------------------------------------------------------------------------
# Demo (offline) + timeout plumbing
# ---------------------------------------------------------------------------


def test_real_world_demo_runs_offline():
    env = dict(os.environ)
    # Empty (not absent) so `load_dotenv()` cannot re-inject local .env keys.
    env["AUTOTEAM_API_KEY"] = ""
    env["LLM_API_KEY"] = ""
    env["AUTOTEAM_WEB_SEARCH_URL"] = ""
    env["AUTOTEAM_WEB_SEARCH_API_KEY"] = ""
    env["AUTOTEAM_LLM_PROVIDER"] = "mock"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "real_world_demo.py")],
        capture_output=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0
    stdout = completed.stdout.decode("utf-8", errors="replace")
    assert "OFFLINE MOCK" in stdout
    assert "SUCCESS" in stdout
    assert "Data source: offline_mock" in stdout


def test_session_accepts_timeout_and_tool_limits():
    session = execute_task(TASK_SOFTWARE, timeout=30, max_tool_calls=2, max_iterations=3)
    assert session.status is SessionStatus.SUCCESS



# ---------------------------------------------------------------------------
# v0.6.0 tool transparency + offline determinism
# ---------------------------------------------------------------------------


def test_tool_kind_distinguishes_local_mock_web_and_fallback(monkeypatch):
    registry = ToolRegistry(mode="auto")

    # deterministic local tools are NOT mocks
    assert registry.execute("calculator", {"expression": "1 + 1"}).kind == "local"

    # offline web search is an explicit offline_mock (no fake URLs)
    for name in ("AUTOTEAM_WEB_SEARCH_URL", "AUTOTEAM_WEB_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert registry.run("web_search", "q").kind == "offline_mock"

    # a failed real search is recorded as offline_fallback, never as "web"
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://search.example.com/api")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-test-key")

    def failing_urlopen(request, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    fallback = registry.run("web_search", "q")
    assert fallback.kind == "offline_fallback"
    assert fallback.error

    # a successful real call is the only thing marked "web"
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"results": [{"title": "t", "url": "https://x.test/a", "snippet": "s"}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    real = registry.run("web_search", "q")
    assert real.kind == "web"
    assert real.offline is False


def test_offline_session_never_calls_real_web_search(monkeypatch):
    """Offline mode must stay offline even when real search keys exist in .env."""
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_URL", "https://search.example.com/api")
    monkeypatch.setenv("AUTOTEAM_WEB_SEARCH_API_KEY", "sk-should-not-be-used")

    called = {"n": 0}

    def spy_urlopen(request, timeout):  # pragma: no cover - must never run
        called["n"] += 1
        raise AssertionError("offline session attempted a live web search")

    monkeypatch.setattr("urllib.request.urlopen", spy_urlopen)
    session = execute_task("分析 AI Agent 市场")
    assert called["n"] == 0
    for source in session.final_artifact.source_records:
        assert source.source_type == "offline_mock"


def test_tool_events_carry_accurate_kind(monkeypatch):
    for name in ("AUTOTEAM_WEB_SEARCH_URL", "AUTOTEAM_WEB_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    session = execute_task("设计一个 FastAPI 电商后端系统", max_tool_calls=4)
    tool_events = [e for e in session.trace.events if e.type == "TOOL_CALLED"]
    assert tool_events
    for event in tool_events:
        assert event.metadata.get("tool_kind") in {
            "web",
            "local",
            "offline_mock",
            "offline_fallback",
        }


def test_schema_validation_error_is_friendly_not_a_traceback():
    from pydantic import ValidationError

    class BadSchemaProvider:
        """Team formation works (mock fallback); agent decisions fail schema."""

        def structured_completion(self, prompt, response_model):
            if response_model.__name__ == "AgentDecision":
                raise ValidationError.from_exception_data(
                    "AgentDecision", [{"type": "missing", "loc": ("action",), "input": {}}]
                )
            return MockLLMProvider().structured_completion(prompt, response_model)

    session = execute_task(TASK_SOFTWARE, provider=BadSchemaProvider())
    assert session.status is not SessionStatus.SUCCESS
    # user-facing message stays short; the run does not crash / leak a traceback
    messages = [event.message for event in session.trace.events if event.type == "AGENT_FAILED"]
    assert messages
    assert all("Traceback" not in m for m in messages)
    assert any("invalid structured response" in m for m in messages)
