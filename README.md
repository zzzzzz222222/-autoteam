# AutoTeam

### Adaptive Multi-Agent Orchestration

> AutoTeam dynamically forms agent teams, generates validated collaboration topologies, executes them asynchronously, recovers from failures, and evaluates topology behavior.

**Status: v0.1.0 — engineering prototype.** AutoTeam is an offline deterministic demo built to make multi-agent orchestration structure visible and testable. It is not a production agent runtime, not a hosted service, and not a real-world LLM benchmark. See [Limitations](#limitations).

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
├── models/        Pydantic schemas: Task, Capability, AgentSpec, Topology
├── analyzer/      Task analysis — rules first, optional LLM
├── allocator/     Capability → Role → AgentSpec allocation
├── llm/           Optional OpenAI-compatible structured-output client
├── topology/      Templates, generator, DAG validator
├── scheduler/     Async DAG scheduler, retry, replan, mock executor
├── evaluation/    Metrics collector, policy, evaluator, benchmark
├── demo/          Presentation layer: tasks, service, render, Streamlit page
├── config.py
└── ui.py          Streamlit entry point

examples/
├── demo.py
├── topology_demo.py
├── scheduler_demo.py
├── recovery_demo.py
└── evaluation_demo.py

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
Tests: 60 passed
Ruff:  PASS
CI:    Python 3.11 / 3.12
```

- Day 1-5: 44 tests
- Day 6: 16 tests (`tests/test_ui.py` — service functions, offline mode, failure simulation, evaluation pipeline, SVG/timeline rendering)

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
- [ ] v0.1.0 Release
