# AutoTeam Architecture

> This document explains the system design at the module level — responsibilities, inputs, outputs, and how modules relate. It is not a line-by-line source walkthrough.

## Core Principle

```
LLM proposes  →  Schema constrains  →  Code validates  →  Executor executes
```

Every decision follows this single pipeline. The LLM (or the deterministic mock) proposes an object; a Pydantic schema constrains its shape; code validates it deterministically; the scheduler/runtime executes it.

## Overall Architecture

```mermaid
flowchart LR
    T[Task] --> U[Understanding]
    U --> CD[Capability Discovery]
    CD --> RA[Role Allocation]
    RA --> AF[Agent Factory]
    AF --> TS[Tool Selection]
    TS --> DA[Dependency Analysis]
    DA --> G[DAG]
    G --> S[Async Scheduler]
    S --> RT[Agent Runtime]
    RT --> TE[Tool Execution]
    TE --> AR[Artifact]
    AR --> V[Validation]
    V --> CO[Collaboration]
    CO --> A[Assembler]
    A --> FD[Final Deliverable]
```

## Task Understanding

- **Module(s):** `app/runtime/understanding.py`, `app/runtime/decomposer.py`
- **Responsibility:** Turn a free-form task into one or more concrete subtasks.
- **Input:** task description.
- **Output:** subtask plan.
- **Relations:** feeds capability discovery.

## Dynamic Team Formation

```mermaid
flowchart TD
    COM[Understanding] --> CD[Capability Discovery]
    CD --> RA[Role Allocation]
    RA --> AF[Agent Factory]
    AF --> TS[Tool Selection]
    TS --> DA[Dependency Analysis]
    DA --> PLAN[Execution Plan + DAG]
```

### Capability Discovery

- **Module:** `app/runtime/capability_discovery.py`
- **Responsibility:** Map each subtask to the capabilities required to complete it.
- **Input:** subtask plan.
- **Output:** per-subtask capability set.
- **Relations:** the first step where **Capability ≠ Role ≠ Agent** matters.

### Role Allocation

- **Module:** `app/runtime/role_allocation.py`
- **Responsibility:** Group capabilities into personas (roles). A role may own several capabilities.
- **Input:** capabilities.
- **Output:** roles.
- **Relations:** feeds the agent factory.

### Agent Factory

- **Module:** `app/runtime/agent_factory.py`
- **Responsibility:** Instantiate a runtime agent from a role — attach a name, an output schema, and a tool set.
- **Input:** role (+ provider and tool config).
- **Output:** `AgentSpec`.
- **Relations:** the concrete executable unit scheduled by the DAG.

## Tool Selection

- **Module:** `app/runtime/tool_selector.py`, `app/tools/registry.py`
- **Responsibility:** Decide which tools an agent may call and resolve them to executable implementations.
- **Input:** agent capability / role.
- **Output:** a set of tool names.
- **Relations:** the registry performs actual execution.

## Dependency Analysis

- **Module:** `app/runtime/dependency.py`
- **Responsibility:** Determine which subtasks must run before others; detect cycles, missing, and self-dependencies.
- **Input:** subtasks.
- **Output:** dependency edges.
- **Relations:** produces the graph the DAG validator checks.

## DAG & Validation

- **Module:** `app/topology/*`
- **Responsibility:** Build and validate the execution topology as a directed acyclic graph.
- **Input:** dependency edges.
- **Output:** a valid DAG.
- **Relations:** the scheduler consumes this DAG directly.

## Async Scheduler

- **Module:** `app/scheduler/scheduler.py`
- **Responsibility:** Run agents in dependency order, in parallel where possible.
- **Input:** DAG + agent list.
- **Output:** per-agent execution results.
- **Relations:** drives the agent runtime; owns retry and replan.

## Agent Runtime

- **Module:** `app/runtime/agent_runtime.py`
- **Responsibility:** Execute one agent: assemble context, call the LLM provider (or mock), run tool-calling, build a validated artifact.
- **Input:** `AgentSpec` + execution context (upstream artifacts).
- **Output:** `AgentArtifact`.
- **Relations:** sits between the scheduler and the LLM/tool layers.

## Tool Execution

- **Module:** `app/tools/registry.py`, `app/tools/calculator.py`, `app/tools/local_knowledge.py`
- **Responsibility:** Execute a structured `ToolCall` safely, returning typed `ToolResult`s and `Source`s.
- **Input:** `ToolCall {tool_name, arguments}`.
- **Output:** `ToolResult` (+ provenance for `web_search`).
- **Errors:** `ToolNotFound`, `ToolValidationError`, `ToolExecutionError`.

## Artifact System

- **Module:** `app/runtime/artifacts.py`
- **Responsibility:** Represent every agent's structured, addressable result.
- **Input:** agent deliverable + tool results.
- **Output:** `AgentArtifact` with `structured_data`, `sources`, `evidence`.
- **Relations:** the currency passed between collaborating agents.

## Artifact Validation

- **Module:** `app/runtime/validation.py`
- **Responsibility:** Deterministically reject malformed artifacts before they propagate: empty schema, evidence referencing an unknown source, non-http urls.
- **Input:** `AgentArtifact`.
- **Output:** validation pass or `ArtifactValidationError`.
- **Relations:** runs at artifact creation and again before assembly.

## Agent Collaboration

- **Module:** `app/runtime/context.py`
- **Responsibility:** Give each agent only its transitive upstream artifacts plus its own subtask info — never global state.
- **Input:** agent + scheduler context.
- **Output:** an `AgentExecutionContext`.
- **Relations:** lets a backend agent read its architect's artifact.

## Evidence / Source

- **Module:** `app/runtime/artifacts.py`, `app/runtime/validation.py`
- **Responsibility:** Attach provenance to claims. Every `Evidence.source_id` must reference a `Source` in the artifact.
- **Input:** tool results → `Source`s; deliverable key points → `Evidence`.
- **Output:** verified evidence lists.
- **Relations:** offline sources are explicitly `offline_mock` with empty urls.

## Retry / Replan

- **Module:** `app/scheduler/retry.py`, `app/scheduler/replan.py`
- **Responsibility:** Recover from agent failure. **Retry** reruns the agent without changing the DAG; **Replan** triggers after retries are exhausted, skipping the failed agent and its downstream dependents.
- **Input:** scheduler failure signals.
- **Output:** retried / replanned execution → `SUCCESS` or `PARTIAL_SUCCESS`.

## Final Deliverable

- **Module:** `app/runtime/assembler.py`
- **Responsibility:** Consume the validated artifact graph and produce a readable final report.
- **Input:** artifacts + agent order.
- **Output:** `FinalArtifact.to_markdown()` — findings, key data, **Evidence**, **Sources**.
- **Relations:** the top-level result returned to the user and saved to Markdown.

## Module Layout

```
app/
├── models/        Pydantic schemas: Task, Capability, AgentSpec, Topology, etc.
├── analyzer/      rule-based task analysis (offline first)
├── allocator/     Capability → Role → AgentSpec allocation
├── llm/           LLM provider abstraction (mock + OpenAI/DeepSeek compatible)
├── topology/      templates, DAG generator, DAG validator
├── scheduler/     async DAG scheduler, retry, replan
├── evaluation/    metrics, policy, evaluator
├── runtime/       understanding, capability, role, factory, tools, dependency,
│                  artifacts, context, session, assembler, validation, events
└── tools/         ToolRegistry: web_search, calculator, local_knowledge, + stubs
```