import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from app.models.agent import AgentSpec
from app.scheduler.models import ExecutionContext


class AgentExecutor(Protocol):
    async def execute(self, agent: AgentSpec, context: ExecutionContext) -> Any: ...


class MockAgentExecutor:
    """In-memory executor for tests and demos; it never calls an external service."""

    def __init__(
        self,
        delay: float = 0.0,
        fail_agent_ids: set[str] | None = None,
        raise_agent_ids: set[str] | None = None,
        failures_before_success: dict[str, int] | None = None,
        on_start: Callable[[str], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> None:
        self.delay = delay
        self.fail_agent_ids = fail_agent_ids or set()
        self.raise_agent_ids = raise_agent_ids or set()
        self.failures_before_success = failures_before_success or {}
        self.call_counts: dict[str, int] = {}
        self.on_start = on_start
        self.on_done = on_done
        self.execution_order: list[str] = []
        self.active_count = 0
        self.max_concurrent = 0

    async def execute(self, agent: AgentSpec, context: ExecutionContext) -> Any:
        del context
        agent_id = agent.id or "unknown"
        self.call_counts[agent_id] = self.call_counts.get(agent_id, 0) + 1
        self.execution_order.append(agent_id)
        self.active_count += 1
        self.max_concurrent = max(self.max_concurrent, self.active_count)
        if self.on_start:
            self.on_start(agent_id)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if agent_id in self.raise_agent_ids:
                raise RuntimeError(f"Mock executor exception for {agent_id}")
            if agent_id in self.fail_agent_ids or self.call_counts[
                agent_id
            ] <= self.failures_before_success.get(agent_id, 0):
                raise RuntimeError(f"Mock executor failure for {agent_id}")
            return {"agent_id": agent_id, "message": f"{agent.role.name} completed"}
        finally:
            self.active_count -= 1
            if self.on_done:
                self.on_done(agent_id)
