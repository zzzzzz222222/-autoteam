"""v0.6.0-final — R1 / R2 / R5 honesty fixes (offline-verifiable).

R1  : token usage is captured by the real provider and aggregated by the counting
      provider; cost is derived only from validation/pricing.py (never guessed).
R2  : a session with unmet source needs (source_gaps) can be at most PARTIAL_SUCCESS.
R5  : an explicitly partial deliverable is flagged so the session never counts it
      as a full success.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.llm.provider import MockLLMProvider
from app.models.agent import AgentRole
from app.models.capability import CapabilityName
from app.runtime.agent_factory import DynamicAgentSpec
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.artifacts import AgentDeliverable
from app.runtime.context import AgentExecutionContext
from app.runtime.session import CompletionCriteria, SessionStatus, execute_task
from app.tools.registry import ToolRegistry
from validation import pricing
from validation.counting_provider import CountingProvider


class _TrivialModel(BaseModel):
    pass


class FakeRealProvider:
    """Duck-typed *real* provider (not a MockLLMProvider) that reports usage."""

    def __init__(self, model: str = "deepseek-chat") -> None:
        self.model = model
        self.last_response_meta: dict = {}

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        # Pretend the endpoint returned a small, deterministic token count.
        self.last_response_meta = {
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "usage_available": True,
        }
        return response_model()


def _agent(tools):
    return DynamicAgentSpec(
        id="agent_x",
        role=AgentRole(name="Agent X", capabilities=[CapabilityName.MARKET_RESEARCH], goal="t"),
        tools=list(tools),
        system_prompt="t",
    )


# ---------------------------------------------------------------------------
# R1 — token usage capture + aggregation + honest cost
# ---------------------------------------------------------------------------


def test_counting_provider_aggregates_token_usage():
    inner = FakeRealProvider("deepseek-chat")
    counting = CountingProvider(inner, max_calls=5)
    for _ in range(3):
        counting.structured_completion("p", _TrivialModel)
    summary = counting.summary()
    assert summary["count"] == 3
    usage = summary["token_usage"]
    assert usage == {
        "prompt_tokens": 30,
        "completion_tokens": 60,
        "total_tokens": 90,
    }


def test_estimated_cost_only_from_pricing_and_known_model():
    usage = {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000}
    # deepseek-chat: prompt 0.014/1k, completion 0.028/1k
    assert pricing.compute_cost("deepseek-chat", usage) == round(
        (1000 / 1000) * 0.014 + (2000 / 1000) * 0.028, 6
    )
    # unknown model -> null, never a guess
    assert pricing.compute_cost("some-unknown-model", usage) is None
    # no usage -> null
    assert pricing.compute_cost("deepseek-chat", None) is None


def test_collect_metrics_cost_key_present_offline():
    """Offline runs carry no token usage, so cost is explicitly null."""
    session = execute_task(
        "分析 AI Agent 市场",
        provider=None,
        tool_mode="mock",
        timeout=None,
        max_tool_calls=2,
        max_iterations=2,
    )
    from validation.collect import collect_metrics

    metrics = collect_metrics(session, scenario_id="A", mode="offline", counting=None)
    assert metrics["provider"]["estimated_cost_usd"] is None
    assert metrics["provider"]["llm_calls"] is None
    assert metrics["truth"]["is_real_llm"] is False


# ---------------------------------------------------------------------------
# R5 — partial deliverable flag -> artifact metadata + session status
# ---------------------------------------------------------------------------


def test_build_artifact_marks_partial_metadata():
    runtime = AgentRuntime(provider=MockLLMProvider(), tool_registry=ToolRegistry(mode="mock"))
    deliverable = AgentDeliverable(
        title="partial deliverable",
        summary="x",
        key_points=["p"],
        structured_data={},
        sources=[],
    )
    ctx = AgentExecutionContext(
        agent_id="agent_x", role_name="Agent X", task="t", expected_output="market_overview"
    )
    full = runtime._build_artifact(_agent(["web_search"]), ctx, deliverable, ctx.task)
    assert full.metadata.get("partial") is False

    partial = runtime._build_artifact(
        _agent(["web_search"]), ctx, deliverable, ctx.task, is_partial=True
    )
    assert partial.metadata.get("partial") is True


def test_completion_criteria_downgrades_success_on_partial():
    criteria = CompletionCriteria(minimum_successful_agents=1, allow_partial=True)
    # all agents succeeded but one is partial -> not a clean SUCCESS
    assert (
        criteria.evaluate(2, 3, {"market_overview"}, partial_agents=1)
        is SessionStatus.PARTIAL_SUCCESS
    )
    # zero full success but a partial meets the minimum -> still PARTIAL (honest)
    assert (
        criteria.evaluate(0, 3, {"market_overview"}, partial_agents=2)
        is SessionStatus.PARTIAL_SUCCESS
    )
    # all full success, no partial -> SUCCESS
    assert (
        criteria.evaluate(3, 3, {"market_overview"}, partial_agents=0)
        is SessionStatus.SUCCESS
    )


# ---------------------------------------------------------------------------
# R2 — source gaps cap the verdict at PARTIAL_SUCCESS
# ---------------------------------------------------------------------------


def test_completion_criteria_downgrades_success_on_source_gaps():
    criteria = CompletionCriteria(minimum_successful_agents=1, allow_partial=True)
    # every agent fully succeeded, but declared source needs were unmet
    assert (
        criteria.evaluate(3, 3, {"market_overview"}, source_gaps_present=True)
        is SessionStatus.PARTIAL_SUCCESS
    )
    # no gaps, all full -> SUCCESS
    assert (
        criteria.evaluate(3, 3, {"market_overview"}, source_gaps_present=False)
        is SessionStatus.SUCCESS
    )
