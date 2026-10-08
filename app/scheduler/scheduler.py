import asyncio
import time

from app.models.agent import AgentSpec
from app.models.task import Task
from app.models.topology import Topology
from app.scheduler.executor import AgentExecutor
from app.scheduler.models import AgentResult, ExecutionAttempt, ExecutionContext, ExecutionStatus
from app.scheduler.replan import ReplanEvent, Replanner, ReplanResult, topology_signature
from app.scheduler.retry import RetryPolicy
from app.topology.validator import TopologyValidator


class AsyncDAGScheduler:
    def __init__(
        self,
        executor: AgentExecutor,
        max_concurrency: int | None = None,
        timeout: float | None = None,
        retry_policy: RetryPolicy | None = None,
        replanner: Replanner | None = None,
    ) -> None:
        # AT-AUDIT-001: the cap is only meaningful as a positive integer. A float
        # such as 1.5 silently broke it in the past — ``asyncio.Semaphore`` only
        # blocks while its internal value compares equal to 0, so a fractional
        # value decrements past zero forever and never gates anything.
        if max_concurrency is not None:
            if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
                raise TypeError(
                    f"max_concurrency must be a positive integer or None, got {max_concurrency!r}."
                )
            if max_concurrency < 1:
                raise ValueError("max_concurrency must be at least 1.")
        self.executor = executor
        self.max_concurrency = max_concurrency
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self.replanner = replanner or Replanner()
        self.replan_events: list[ReplanEvent] = []

    async def run(
        self, task: Task, topology: Topology, agents: list[AgentSpec]
    ) -> dict[str, AgentResult]:
        TopologyValidator().validate(topology)
        agent_map = self._validate_agents(topology, agents)
        predecessors = {
            agent_id: {edge.source for edge in topology.edges if edge.target == agent_id}
            for agent_id in topology.agents
        }
        statuses = {agent_id: ExecutionStatus.PENDING for agent_id in topology.agents}
        results: dict[str, AgentResult] = {}
        context = ExecutionContext(task, topology, agent_map, results)
        semaphore = (
            asyncio.Semaphore(self.max_concurrency) if self.max_concurrency is not None else None
        )

        while any(status is ExecutionStatus.PENDING for status in statuses.values()):
            for agent_id, status in list(statuses.items()):
                if status is ExecutionStatus.PENDING and any(
                    statuses[parent] in {ExecutionStatus.FAILED, ExecutionStatus.SKIPPED}
                    for parent in predecessors[agent_id]
                ):
                    statuses[agent_id] = ExecutionStatus.SKIPPED
                    results[agent_id] = AgentResult(
                        agent_id=agent_id,
                        status=ExecutionStatus.SKIPPED,
                        error="upstream dependency failed",
                    )
            ready = [
                agent_id
                for agent_id, status in statuses.items()
                if status is ExecutionStatus.PENDING
                and all(
                    statuses[parent] is ExecutionStatus.SUCCESS for parent in predecessors[agent_id]
                )
            ]
            if not ready:
                if any(status is ExecutionStatus.PENDING for status in statuses.values()):
                    raise RuntimeError("No runnable agents remain in a validated DAG.")
                break
            for agent_id in ready:
                statuses[agent_id] = ExecutionStatus.READY
            completed = await asyncio.gather(
                *(
                    self._execute_one(agent_id, agent_map[agent_id], context, semaphore)
                    for agent_id in ready
                )
            )
            for result in completed:
                statuses[result.agent_id] = result.status
                results[result.agent_id] = result
                if result.status is ExecutionStatus.FAILED:
                    recovery = self.replanner.replan(topology, result.agent_id, results)
                    previous = topology_signature(topology)
                    applied, new, detail = self._apply_replan(topology, recovery)
                    if applied and recovery.topology is not None:
                        # AT-AUDIT-005: hand the candidate to the structures the
                        # loop actually schedules from. This point is only reached
                        # after ``asyncio.gather`` settled the whole wave, so no
                        # agent is in flight and no execution context is disturbed.
                        # ``statuses`` is deliberately left alone: finished agents
                        # are never rerun and pending agents simply get re-decided
                        # against the new edges on the next pass.
                        topology = recovery.topology
                        predecessors = {
                            agent_id: {
                                edge.source
                                for edge in topology.edges
                                if edge.target == agent_id
                            }
                            for agent_id in topology.agents
                        }
                        context.topology = topology
                    self.replan_events.append(
                        ReplanEvent(
                            failed_agent_id=result.agent_id,
                            reason=recovery.reason,
                            previous_topology=previous if applied else None,
                            new_topology=new if applied else None,
                            applied=applied,
                            detail=detail,
                        )
                    )
        return results

    def _apply_replan(
        self, topology: Topology, recovery: ReplanResult
    ) -> tuple[bool, str | None, str]:
        """Decide whether ``recovery`` can become the plan the loop executes.

        Returns ``(applied, new_signature, detail)``. ``detail`` carries the
        reason for a refusal so an unsupported candidate is never silently
        dropped. Validation reuses the project's own validator — no second,
        parallel set of rules.
        """
        if not recovery.replanned or recovery.topology is None:
            return False, None, "replanner produced no candidate plan"
        candidate = recovery.topology
        # Existing gate: schema + DAG validation. An invalid candidate still
        # raises here, which is the behaviour this project already had.
        TopologyValidator().validate(candidate)
        new = topology_signature(candidate)
        if new == topology_signature(topology):
            return False, None, "candidate is identical to the running plan"
        # One AgentSpec exists per planned node. A candidate that adds or removes
        # nodes cannot be executed (no spec for a new node, and a removed node
        # would stay PENDING forever), so it is refused rather than half-applied.
        if set(candidate.agents) != set(topology.agents):
            return False, None, (
                "candidate changes the agent set, which this scheduler cannot execute"
            )
        return True, new, ""

    @staticmethod
    def _validate_agents(topology: Topology, agents: list[AgentSpec]) -> dict[str, AgentSpec]:
        agent_map = {agent.id: agent for agent in agents if agent.id is not None}
        if len(agent_map) != len(agents) or set(agent_map) != set(topology.agents):
            raise ValueError("AgentSpec IDs must uniquely match topology agents.")
        return agent_map

    async def _execute_one(
        self,
        agent_id: str,
        agent: AgentSpec,
        context: ExecutionContext,
        semaphore: asyncio.Semaphore | None,
    ) -> AgentResult:
        attempts: list[ExecutionAttempt] = []
        for attempt_number in range(1, self.retry_policy.max_retries + 2):
            started = time.perf_counter()
            try:

                async def invoke() -> object:
                    return await self.executor.execute(agent, context)

                if semaphore is None:
                    output = await self._with_timeout(invoke())
                else:
                    async with semaphore:
                        output = await self._with_timeout(invoke())
                finished = time.perf_counter()
                attempts.append(
                    ExecutionAttempt(
                        agent_id=agent_id,
                        attempt=attempt_number,
                        status=ExecutionStatus.SUCCESS,
                        started_at=started,
                        finished_at=finished,
                    )
                )
                return AgentResult(
                    agent_id=agent_id,
                    status=ExecutionStatus.SUCCESS,
                    output=output,
                    started_at=attempts[0].started_at,
                    finished_at=finished,
                    attempt=attempt_number,
                    attempts=attempts,
                )
            except TimeoutError:
                error = "execution timeout"
            except Exception as exc:
                error = str(exc)
            finished = time.perf_counter()
            attempts.append(
                ExecutionAttempt(
                    agent_id=agent_id,
                    attempt=attempt_number,
                    status=ExecutionStatus.FAILED,
                    error=error,
                    started_at=started,
                    finished_at=finished,
                )
            )
            if attempt_number <= self.retry_policy.max_retries and self.retry_policy.retry_delay:
                await asyncio.sleep(self.retry_policy.retry_delay)
        return AgentResult(
            agent_id=agent_id,
            status=ExecutionStatus.FAILED,
            error=attempts[-1].error,
            started_at=attempts[0].started_at,
            finished_at=attempts[-1].finished_at,
            attempt=len(attempts),
            attempts=attempts,
        )

    async def _with_timeout(self, awaitable: object) -> object:
        if self.timeout is None:
            return await awaitable  # type: ignore[misc]
        return await asyncio.wait_for(awaitable, timeout=self.timeout)  # type: ignore[arg-type]
