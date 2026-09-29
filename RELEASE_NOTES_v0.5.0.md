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

## Real API Verification

A live **DeepSeek-compatible API request** was executed with a real API key during the final pre-publication smoke test (key kept only in a gitignored local `.env`, never committed). Verified end-to-end:

- Real LLM request — executed against the live endpoint, meaningful content returned
- Dynamic multi-agent execution — full session completed with `SUCCESS`
- Artifact generation — real intermediate artifacts for each agent
- Evidence / Sources — provenance collected and validated
- Downstream artifact consumption — downstream agent read upstream artifact context
- Final artifact generation — final deliverable assembled from real results

**Real LLM — Implemented + Actually Verified.** **Real Web Search — Implemented but not externally verified** (no vendor API credentials were available in the verification environment). The offline fallback for web search (structured `offline_mock` results, empty URLs, no fabricated data) is verified; it must not be mistaken for a real web-search verification.

## Known Limitations

- Offline mock results are not a substitute for real model quality.
- Session state is in-memory (no persistence / checkpointing).
- Completeness is judged by deterministic rules, not model scoring.
- Not a production-grade distributed execution platform.

## Breaking Changes

None.