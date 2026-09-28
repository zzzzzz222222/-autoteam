[English](README.md) | [简体中文](README.zh-CN.md)

# AutoTeam

### Adaptive Multi-Agent Orchestration

> AutoTeam dynamically forms agent teams, generates validated collaboration topologies, executes them asynchronously, recovers from failures, and evaluates topology behavior.

**Status: v0.1.0 released; v0.2.0 (AutoTeam Research) and v0.3.0 (Dynamic Team Intelligence) layered on top.** AutoTeam is an offline deterministic demo built to make multi-agent orchestration structure visible and testable. It is not a production agent runtime, not a hosted service, and not a real-world LLM benchmark. See [Limitations](#limitations).

### How it works in one paragraph

A task is analyzed into **capabilities** → capabilities are grouped into **roles** → roles become the **agent team** → three **candidate topologies** are generated → each is **validated as a DAG** → each is **executed** by an async scheduler with **retry / replan** → results are compared **per metric** → everything is rendered in a **Streamlit UI**.

---

## What is AutoTeam?

AutoTeam explores how an AI system can **dynamically construct and execute multi-agent teams** instead of relying on a fixed workflow.

You give it a task. It decides which capabilities the task needs, which roles cover those capabilities, how those roles should collaborate, whether that collaboration graph is actually valid, and which candidate topology behaved better once everything ran.

Key capabilities:

- **Dynamic Team Formation** — the agent team is allocated per task, not hard-coded
- **Dynamic Collaboration Topology** — Chain / Star / Hierarchical candidates are generated per team
- **DAG Validation** — every candidate is checked as a directed acyclic graph before scheduling
- **Async Execution** — an async DAG scheduler runs independent agents concurrently
- **Retry / Replan** — failures retry locally first, then fall back to validator-constrained recovery
- **Topology Evaluation** — candidates are executed independently and compared per metric
- **Streamlit Visualization** — the whole pipeline is visible in one screen

It runs fully offline. No API key, no database, no external service.

---

## Why AutoTeam?

Traditional multi-agent systems usually look like this:

```
Task → Fixed Agents → Fixed Workflow → Fixed Graph
```

The collaboration structure is an implementation detail decided once, up front, by a human.

AutoTeam treats it as part of the problem:

```
Task → Analyze Capabilities → Allocate Roles → Build Agent Team
     → Generate Candidate Topologies → Validate DAG → Execute → Recover → Evaluate
```

> **The collaboration structure is treated as part of the problem, not a fixed implementation detail.**

| | Traditional multi-agent demo | AutoTeam |
|---|---|---|
| Team | Hard-coded agent list | Allocated per task from required capabilities |
| Collaboration | Fixed chain / static graph | Three candidate topologies generated per team |
| Graph correctness | Assumed | Validated as a DAG (acyclic, reachable, no self-loops) |
| Execution | Sequential or framework-managed | Async DAG scheduler with concurrency limits and timeouts |
| Failure | Crash or silent retry | Retry → deterministic replan → downstream skip |
| Comparison | "It works" | Raw metrics per topology, reported per metric only |

---

## Architecture

```
User Task
   │
   ▼
Task Analyzer                 rule-based offline detection, optional LLM
   │
   ▼
Capabilities
   │
   ▼
Role Allocator                capability coverage → AgentSpec[]
   │
   ▼
Agent Team
   │
   ▼
Topology Generator
   ├── Chain
   ├── Star
   └── Hierarchical
   │
   ▼
DAG Validator                 acyclic / reachable / no self-loops → parallel layers
   │
   ▼
Async DAG Scheduler
   ├── Retry                  re-runs the failed agent only
   └── Replan                 records recovery state after retries are exhausted
   │
   ▼
Execution Results             PENDING / READY / RUNNING / SUCCESS / FAILED / SKIPPED
   │
   ▼
Topology Evaluation           metrics → per-metric leaders
   │
   ▼
Streamlit UI
```

---

## Core Design Principle

> **LLM proposes, Schema constrains, Code validates, Executor executes.**

| Layer | Responsibility |
|---|---|
| **LLM** | Proposes the analysis result or a structured suggestion |
| **Schema** | Constrains the data shape (Pydantic models) |
| **Code** | Validates topology, dependencies and execution conditions |
| **Executor** | Actually runs the agent |

The LLM is never trusted with graph edits. Any topology change still has to pass the same DAG validator.

**Offline mode works without an API key.** Without `LLM_API_KEY`, the analyzer stays fully rule-based and deterministic. The LLM is an optional capability, not a requirement.

---

## Capability → Role → Agent

These three are not the same thing, and the distinction is a deliberate design point:

- **Capability** — what the system needs to be able to do
- **Role** — a coherent grouping of related capabilities
- **Agent** — the executable unit that carries a role

```
Capabilities:
  competitor_analysis
  market_research
        ↓
Role:
  Competitor Analyst
        ↓
Agent:
  Competitor Analyst Agent
```

`Capability ≠ Role ≠ Agent.` The allocator covers required capabilities with role templates and falls back to a General Agent for anything uncovered — so the number of agents is a **result**, not a setting.

---

## Topology

A topology is a DAG over agent IDs. AutoTeam generates three candidates per team.

**Chain** — `A → B → C → D`

- Sequential
- Low structural parallelism
- Simple dependencies

**Star**

```
      B
      ↑
C  ←  A  →  D
```

- High potential parallelism
- Central root dependency

**Hierarchical**

```
      A
     / \
    B   C
    |
    D
```

- Multi-level dependencies
- Moderate parallelism

Different topologies expose different execution characteristics. AutoTeam does not assume one is universally better — it measures them.

---

## Execution & Recovery

The scheduler tracks six states: `PENDING`, `READY`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`.

**Day 4 recovery is split in two:**

- **Retry** — re-executes the current agent. *Retry does not change the DAG.*
- **Replan** — runs after retries are exhausted. *Replan is validator-constrained.*

When no viable recovery path exists, the replanner records that fact and every descendant of the failed node becomes `SKIPPED` with an explicit reason. Arbitrary graph rewrites are never performed.

---

## Evaluation

Each candidate is executed independently, then compared on raw metrics:

| Metric | Meaning |
|---|---|
| Duration | Wall-clock time of the whole run |
| Success Rate | Share of agents that finished successfully |
| Failure Rate | Share of agents that failed after all retries |
| Skipped | Agents skipped because an upstream dependency failed |
| Recovery | Agents that succeeded only after a retry |
| Max Concurrency | Highest number of agents observed running at once |
| Structural Parallelism | Widest parallel layer relative to team size |

AutoTeam does **not** use:

- Weighted synthetic score
- LLM judge
- Black-box ranking

It reports a **transparent per-metric comparison** — including deterministic ties, so a three-way tie on success rate is shown as a three-way tie.

---

## Demo

```bash
streamlit run app/ui.py
```

The UI walks the whole pipeline in one screen:

1. **Task** — pick a preset or type your own, then `Analyze & Build Team`
2. **Team Formation** — capabilities on the left, allocated agent cards on the right
3. **Candidate Topologies** — agents / edges / steps / structural parallelism per candidate
4. **Topology Graph** — layered SVG of the selected DAG
5. **Execution** — `Run All Topologies`, with optional failure simulation
6. **Execution Results** — per-agent status, attempt count, retry detail, skip reason, timeline
7. **Evaluation** — full metric table
8. **Comparison** — shortest duration, highest success rate, highest parallelism, most reliable

**Failure simulation** reuses Day 4 as-is. Two scenarios are selectable:

- *Retry then succeed* — `attempt 1: FAILED → attempt 2: SUCCESS`, counted as a recovered agent
- *Retry exhausted* — the agent ends `FAILED` and every descendant becomes `SKIPPED` with an explicit reason

---

## Demo Results

Task: *"Research the AI agent market, analyze competitors and pricing, and write a market report."*

Team formed: `Market Researcher`, `Competitor Analyst`, `Financial Analyst`, `Report Writer` — 4 agents from 5 detected capabilities. Mock executor, delay `0.05s`.

| Metric | Chain | Star | Hierarchical |
|---|---|---|---|
| Duration | ~0.251s | ~0.123s | ~0.187s |
| Max Concurrency | 1 | 3 | 2 |
| Structural Parallelism | 25% | 75% | 50% |

Per-metric leaders: shortest duration `star`, highest parallelism `star`, highest success rate and most reliable — a three-way tie.

> These numbers are produced by the deterministic local mock executor and demonstrate topology behavior only. They are not real-world LLM performance benchmarks.

Demo task results depend on the current capability vocabulary and the rule-based offline analyzer — different tasks produce different team sizes.

---

## AutoTeam Research (v0.2.0)

v0.2.0 is a **killer-demo layer on top of the stable v0.1.0 engine**. It does not rewrite the orchestration engine — it adds a real agent runtime, task decomposition, research tools, and result aggregation that sit *above* `AsyncDAGScheduler`.

The same core principle still holds: **the LLM proposes, the schema constrains, the code validates, and the scheduler executes.**

### What it does

Give it a research task. It:

1. **Decomposes** the task into a schema-constrained `SubtaskPlan` (a planner role)
2. **Forms a team** — one agent per subtask (Research Agent / Competitor Analyst / Technology Analyst / Report Writer), derived directly from the plan
3. **Builds a collaboration DAG** — edges follow each subtask's `depends_on`; the plan's fan-in structure becomes parallel layers
4. **Executes** it through the **unchanged** `AsyncDAGScheduler` with the new `AgentRuntime` executor (so retry / replan / evaluation apply automatically)
5. **Passes results between agents** — each agent reads its upstream siblings via `ExecutionContext.get_upstream_results`
6. **Aggregates** the structured outputs into a final `ResearchReport`

### Architecture overlay (v0.2.0)

```
User Task
   │
   ▼
Task Decomposer (LLMProvider)        SubtaskPlan  (schema-constrained proposal)
   │
   ▼
build_team / build_topology          AgentSpec[] + DAG  (derived from the plan)
   │
   ▼
Async DAG Scheduler  ◄────────────── AgentRuntime (AgentExecutor Protocol)
   │                                   ├── reads upstream results
   ├── Retry / Replan (unchanged)      ├── calls ToolRegistry (web_search / mock_search)
   │                                   └── returns a Pydantic model → AgentResult.output
   ▼
Aggregator (build_report)            ResearchReport  (code validates + combines)
   │
   ▼
Streamlit "AI Team Live View"        app/ui_live.py  (live agent status + report)
```

### Run the Live View

```bash
streamlit run app/ui_live.py
```

The page renders the decomposition, the team/topology, a **live per-agent status** panel (pending → running → success/failed/skipped) as the background pipeline runs, and the final report. It runs **fully offline** by default — no API key.

### Offline by default, real LLM optional

| Env var | Purpose | Default |
|---|---|---|
| `AUTOTEAM_LLM_PROVIDER` | `mock` (offline) or `openai` / `deepseek` | `mock` |
| `AUTOTEAM_API_KEY` | API key for a real provider | _none → falls back to mock_ |
| `AUTOTEAM_LLM_MODEL` | Model id (e.g. `deepseek-chat`) | provider default |
| `AUTOTEAM_LLM_BASE_URL` | OpenAI-compatible base URL | DeepSeek endpoint |
| `AUTOTEAM_WEB_SEARCH_URL` / `AUTOTEAM_WEB_SEARCH_API_KEY` | real web search backend | _none → offline mock search_ |

Without any key, the demo uses `MockLLMProvider` (deterministic structured stubs) and `mock_search`, so the entire research pipeline runs with no network.

### Offline example output

For a task like *"分析中国跨境电商 SaaS 市场的竞争格局与技术趋势"* the offline pipeline produces:

- **Team:** `research_agent`, `competitor_analyst`, `technology_analyst`, `report_writer`
- **Topology:** 2 parallel layers — `[research, competitor, technology]` → `[report_writer]`
- **Report:** aggregated `market_overview` / `competitors` / `technology` sections plus collected `sources`

> Numbers and text in offline mode are deterministic stubs. They prove the orchestration, result-passing and aggregation mechanics — not real research quality.

---

## Dynamic Team Intelligence (v0.3.0)

v0.3.0 proves the core claim: **AutoTeam does not run a fixed set of agents through a fixed flow.** A task is transformed dynamically into:

```
Task → Task Understanding → Capability Discovery → Task Decomposition
     → Role Allocation → Dynamic Agent Generation → Tool Selection
     → Dependency Analysis → Execution Plan → Existing Scheduler → Existing Runtime
```

Different tasks produce **visibly different teams** — different capabilities, roles, agents, tools, dependencies and execution layers. Nothing is hard-coded: the team is a *result* of the task, never a setting.

### New building blocks

| Module | Responsibility |
|---|---|
| `app/runtime/understanding.py` | `TaskUnderstanding` — domain, objective, expected output, capability set |
| `app/runtime/capability_discovery.py` | Deterministic keyword rules (+ optional LLM refinement, validated against the capability vocabulary) |
| `app/runtime/decomposer.py` → `DynamicDecomposer` | Stage-based decomposition into `DynamicSubtask`s with **structured ids and dependencies** (backward compatible with the v0.2.0 `TaskDecomposer`) |
| `app/runtime/role_allocation.py` | Groups subtasks into roles — one role may own several subtasks (e.g. Backend Developer = API design + implementation) |
| `app/runtime/agent_factory.py` | `DynamicAgentSpec` (extends `AgentSpec`) with system prompt, tools, input/output schemas and a structured reason |
| `app/runtime/tool_selector.py` | Capability → tool mapping, filtered against the `ToolRegistry` — tools can never be invented |
| `app/runtime/dependency.py` | Validates the dependency DAG (missing / self / cycle), lifts it onto agents, computes layers with the existing validator |
| `app/runtime/dynamic_team.py` | `build_dynamic_team(task)` → `ExecutionPlan` (+ `TeamFormationExplanation`); `run_dynamic_team(plan)` executes via the existing scheduler |

The explanation ("Why this team?") stores only structured, displayable reasons — never LLM chain-of-thought.

### Three offline demos, three different teams

| | Demo A · AI Agent market analysis | Demo B · FastAPI e-commerce backend | Demo C · SaaS market entry strategy |
|---|---|---|---|
| Domain | market_research | software_engineering | business_strategy |
| Capabilities | market, competitor, technology, data, report | requirement, architecture, api, database, backend, testing | market, strategy, customer, financial, proposal |
| Roles | Market Researcher · Competitor Analyst · Data Analyst · Technology Analyst · Report Writer | Requirement Analyst · System Architect · Backend Developer · Database Engineer · Test Engineer | Customer Researcher · Market Researcher · Strategy Planner · Financial Analyst · Proposal Writer |
| Tools | web_search · data_analyzer · calculator | schema_validator · code_analysis | web_search · data_analyzer · calculator |
| Layers | 3 | 5 | 4 |

Run the demo:

```bash
python examples/dynamic_team_demo.py
streamlit run app/ui_dynamic.py   # Dynamic Team view with "Why this team?"
```

Offline mode uses deterministic rule-based discovery and mock providers. Real LLM mode (set `AUTOTEAM_API_KEY`) lets the LLM propose the understanding and the plan — the code still validates capabilities, dependencies and the DAG, and falls back to the deterministic rules on any violation. No real research-quality benchmark is claimed anywhere.

---

## Quick Start

```bash
git clone <repository>
cd autoteam
```

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

```bash
pip install -e ".[ui,dev]"
streamlit run app/ui.py
```

---

## CLI / Offline Mode

No API key, no database, no Redis, no external service is required to run any demo.

```bash
python main.py "Create a market research report for a new AI product."
python examples/demo.py
python examples/topology_demo.py
python examples/scheduler_demo.py
python examples/recovery_demo.py
python examples/evaluation_demo.py
```

If you want a real LLM to drive task analysis, copy `.env.example` to `.env` and fill in `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`. It is strictly optional — without it the analyzer stays rule-based and offline.

---

## Project Structure

```
app/
├── models/        Pydantic schemas: Task, Capability, AgentSpec, Topology, ResearchReport
├── analyzer/      Task analysis — rules first, optional LLM
├── allocator/     Capability → Role → AgentSpec allocation
├── llm/           LLM provider abstraction (mock + OpenAI/DeepSeek compatible)
├── topology/      Templates, generator, DAG validator
├── scheduler/     Async DAG scheduler, retry, replan, mock executor
├── evaluation/    Metrics collector, policy, evaluator, benchmark
├── runtime/       v0.2.0 research runtime + v0.3.0 dynamic team pipeline
├── tools/         ToolRegistry: web_search, mock_search, calculator, data_analyzer, schema_validator, code_analysis
├── demo/          Presentation layer: tasks, service, render, Streamlit page
├── config.py
├── ui.py          Streamlit entry point (v0.1.0)
├── ui_live.py     Streamlit "AI Team Live View" (v0.2.0)
└── ui_dynamic.py  Streamlit "Dynamic Team" view (v0.3.0)

examples/
├── demo.py
├── topology_demo.py
├── scheduler_demo.py
├── recovery_demo.py
├── evaluation_demo.py
└── dynamic_team_demo.py

tests/
.github/
└── workflows/
    └── ci.yml
```

`app/demo/` is a pure adapter: `service.py` wires existing components together, `render.py` produces SVG/HTML, `app.py` renders. No scheduler, topology, retry or evaluation logic is duplicated there.

---

## Testing

```bash
pytest -q
ruff check .
```

```
Tests: 110 passed
Ruff:  PASS
CI:    Python 3.11 / 3.12
```

- Day 1-5: 44 tests
- Day 6: 27 tests (`tests/test_ui.py` — service functions, offline mode, failure simulation, evaluation pipeline, SVG/timeline rendering, language toggle, Live View)
- v0.2.0: 11 tests (`tests/test_research.py` — decomposition, runtime, providers, tools, result passing, report aggregation, failure/recovery, offline run)
- v0.3.0: 28 tests (`tests/test_dynamic_team.py` — understanding, capability discovery, dynamic decomposition, role allocation, agent factory, tool selection, dependency analysis incl. cycle/missing/self detection, execution plan, multi-task differentiation, offline E2E, UI)

`tests/test_ui.py` deliberately does not assert Streamlit HTML details. CI runs ruff, pytest, a UI import smoke test and the offline demos on Python 3.11 and 3.12 — no API key, no network, no external service.

---

## Limitations

This is an architectural exploration, not a production orchestration platform. Current boundaries:

- Offline task analysis is **rule-based** and intentionally lightweight
- Topology candidates currently use **predefined templates** (Chain / Star / Hierarchical)
- Agent execution uses **deterministic mock executors** for offline demos
- Evaluation focuses on **structural and execution metrics**, not output quality
- No production distributed execution layer
- No persistent workflow state
- No real-world LLM performance benchmark

---

## Future Work

Directions, not commitments:

- LLM-assisted capability discovery
- More topology templates
- Distributed execution
- Persistent workflow state
- Real-world benchmark suite
- Cost-aware topology selection
- Dynamic topology adaptation
- Production agent executors

---

## Roadmap

- [x] Day 1 — Dynamic Team Formation
- [x] Day 2 — Dynamic Topology Generation
- [x] Day 3 — Async DAG Scheduler
- [x] Day 4 — Retry & Replan
- [x] Day 5 — Topology Evaluation
- [x] Day 6 — Streamlit Visualization
- [x] Bilingual UI (English / 简体中文)
- [x] v0.1.0 Release
- [x] v0.2.0 — AutoTeam Research: real Agent Runtime on top of the engine (TaskDecomposer, LLM provider, ToolRegistry, ResultStore, ResearchReport, Live View)
- [x] v0.3.0 — Dynamic Team Intelligence: Task → Capability → Role → Agent → Tool → Dependency → Execution Plan (three differentiated offline demos)
