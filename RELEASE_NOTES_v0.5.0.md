# AutoTeam v0.5.0 — Release Notes

**Real-World Agent Execution**

## Highlights

| Capability | Status |
|---|---|
| Dynamic Team Formation | implemented & tested |
| Real Agent Runtime | implemented & tested |
| LLM Provider abstraction (mock + OpenAI/DeepSeek compatible) | implemented |
| Executable ToolRegistry | implemented & tested |
| Web Search adapter (offline / real) | implemented |
| Calculator (safe AST, no `eval`) | implemented & tested |
| Local Knowledge tool (workspace-scoped, path-traversal protected) | implemented & tested |
| Sources + Evidence provenance | implemented & tested |
| Artifact Validation (schema + deterministic rules) | implemented & tested |
| Agent Collaboration (artifacts flow downstream) | implemented & tested |
| Retry / Replan | implemented & tested (inherited) |
| Final Deliverable with Sources/Evidence | implemented & tested |

## Architecture

A task flows through: Understanding → Capability Discovery → Role Allocation → Agent Factory → Tool Selection → Dependency Analysis → DAG → Async Scheduler → Real/Mock Agent Runtime → Tool Execution → Artifact → Validation → Collaboration → Final Deliverable. The core principle remains **"LLM proposes, Schema constrains, Code validates, Executor executes."**

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module-by-module design.

## Demo

```bash
python examples/real_world_demo.py
```

Runs the task _"分析 AI Agent 市场，并设计一个面向中小企业的 Agent 产品方案。"_ offline end-to-end (no API key) and writes a final Markdown deliverable with **Evidence** and **Sources** sections to `autoteam_output/<run_id>.md`.

## Verification

- `pytest -q` — **174 passed**
- `ruff check .` — clean
- v0.1.0 / v0.2.0 / v0.3.0 / v0.4.0 regression — **pass**
- v0.5.0 tests (36) — **pass**
- Offline killer demo — **runs in CI without an API key** (in this release environment: run locally)

## Real API Status

Real LLM and Real Web Search adapters are **implemented**, but this release environment had **no real API credentials**, so **no live external API calls were verified**. The real adapters are not exercised by CI or tests; search failures degrade to structured offline results; with no key, the provider automatically falls back to the deterministic mock.

## Known Limitations

- Offline mock results are not a substitute for real model quality.
- Session state is in-memory (no persistence / checkpointing).
- Completeness is judged by deterministic rules, not model scoring.
- Not a production-grade distributed execution platform.

## Breaking Changes

None.