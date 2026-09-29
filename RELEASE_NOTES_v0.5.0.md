# AutoTeam v0.5.0 — Release Notes

**Real-World Agent Execution**

## Highlights

| Capability | Status |
|---|---|
| Dynamic Team Formation | implemented & tested |
| Real Agent Runtime | implemented & tested |
| LLM Provider abstraction (mock + OpenAI/DeepSeek compatible) | implemented |
| Executable ToolRegistry | implemented & tested |
| Web Search adapter (offline / **Tavily** real) | implemented & tested |
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

- `pytest -q` — **186 passed**
- `ruff check .` — clean
- v0.1.0 / v0.2.0 / v0.3.0 / v0.4.0 regression — **pass**
- v0.5.0 tests (36) — **pass**
- Offline killer demo — **runs in CI without an API key** (in this release environment: run locally)

## Real API Verification

Live API calls were executed during the final pre-publication smoke test with real keys (kept only in a gitignored local `.env`, never committed). Verified end-to-end:

**Real LLM (DeepSeek-compatible)** — Implemented + Actually Verified:
- Real LLM request — executed against the live endpoint, meaningful content returned
- Dynamic multi-agent execution — full session completed with `SUCCESS`
- Artifact generation — real intermediate artifacts for each agent
- Evidence / Sources — provenance collected and validated
- Downstream artifact consumption — downstream agent read upstream artifact context
- Final artifact generation — final deliverable assembled from real results

**Real Web Search (Tavily)** — Implemented + Actually Verified:
- Adapter speaks Tavily's protocol (POST + Bearer + JSON `{"query": ...}`, `content` field, response validation)
- Live request returned real results with real URLs
- Agent called `web_search` via `ToolRegistry` and consumed the results into Sources/Evidence
- Offline fallback re-verified separately: removal of the config degrades to structured `offline_mock` results (empty URLs, no fabricated data) without crashing

API keys are configured by the user in a gitignored local `.env` and are never committed; CI stays fully offline.

## Web UI (finalization)

The three historical Streamlit pages (`app/ui.py` / `ui_dynamic.py` / `ui_live.py`) are kept as legacy demos and remain covered by tests. The new product entry is a single **Vue 3 + TypeScript + Vite + Tailwind** frontend over a thin **FastAPI API/SSE** layer:

- `frontend/` — Workspace (task + mode → Build Team & Run), Execution (live SSE timeline, team sidebar, tool calls, evidence/sources), Team (real dynamic DAG), Artifacts, Result (final Markdown + sources + evidence, copy/save).
- `app/api/` — `GET /api/health`, `POST /api/tasks`, `GET /api/tasks/{id}`, `/team`, `/events`, `/artifacts`, `/result`, and `GET /api/tasks/{id}/stream` (SSE replaying the Core's real `ExecutionTrace`).
- The API layer is a pass-through around the untouched `app.runtime.session.execute_task` (background thread, same pattern as the v0.2 Live View). No orchestration was re-implemented; no Core module was modified.
- Backend serves the built SPA too, so `uvicorn app.api.main:app --port 8000` alone exposes the whole product.
- Real LLM (DeepSeek) and Real Web Search (Tavily) remain Actually Verified and are both exposed through the UI's *Real LLM* mode; Offline mode still works with zero configuration.

## Known Limitations

- Offline mock results are not a substitute for real model quality.
- Session state is in-memory (no persistence / checkpointing).
- The API run registry is in-memory (restart loses run history — acceptable for a demo UI).
- Completeness is judged by deterministic rules, not model scoring.
- Not a production-grade distributed execution platform.

## Breaking Changes

None.