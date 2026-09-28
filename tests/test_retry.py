import asyncio
import time

from app.models.agent import AgentRole, AgentSpec
from app.models.capability import CapabilityName
from app.models.task import Task
from app.models.topology import Topology, TopologyType
from app.scheduler.executor import MockAgentExecutor
from app.scheduler.models import ExecutionStatus
from app.scheduler.retry import RetryPolicy
from app.scheduler.scheduler import AsyncDAGScheduler


def run(executor: MockAgentExecutor, policy: RetryPolicy) -> object:
    agent = AgentSpec(
        id="A", role=AgentRole(name="A", capabilities=[CapabilityName.TASK_PLANNING], goal="test")
    )
    topology = Topology(type=TopologyType.CHAIN, agents=["A"], edges=[], root_agent="A")
    return asyncio.run(
        AsyncDAGScheduler(executor, retry_policy=policy).run(
            Task(description="test"), topology, [agent]
        )
    )["A"]


def test_no_retry_fails_once() -> None:
    executor = MockAgentExecutor(fail_agent_ids={"A"})
    result = run(executor, RetryPolicy())
    assert result.status is ExecutionStatus.FAILED and result.attempt == 1


def test_retry_success_tracks_attempts() -> None:
    result = run(MockAgentExecutor(failures_before_success={"A": 1}), RetryPolicy(max_retries=2))
    assert (
        result.status is ExecutionStatus.SUCCESS
        and result.attempt == 2
        and len(result.attempts) == 2
    )


def test_retry_exhaustion_and_delay() -> None:
    started = time.perf_counter()
    result = run(
        MockAgentExecutor(fail_agent_ids={"A"}), RetryPolicy(max_retries=2, retry_delay=0.01)
    )
    assert result.status is ExecutionStatus.FAILED and result.attempt == 3
    assert time.perf_counter() - started >= 0.015


def test_timeout_can_retry_to_success() -> None:
    class SlowOnceExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, agent: object, context: object) -> str:
            del agent, context
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.02)
            return "completed"

    agent = AgentSpec(
        id="A", role=AgentRole(name="A", capabilities=[CapabilityName.TASK_PLANNING], goal="test")
    )
    topology = Topology(type=TopologyType.CHAIN, agents=["A"], edges=[], root_agent="A")
    result = asyncio.run(
        AsyncDAGScheduler(
            SlowOnceExecutor(), timeout=0.001, retry_policy=RetryPolicy(max_retries=1)
        ).run(Task(description="test"), topology, [agent])
    )["A"]
    assert result.status is ExecutionStatus.SUCCESS and result.attempt == 2
