# AutoTeam — UI & Screenshots Guide

This page documents the current product UI (Vue) and the legacy Streamlit demos,
and suggests what to capture for the README / a GitHub Release. Screenshots are
intentionally **not** pre-generated here so the images always reflect the current UI.

## Current product UI (Vue 3 + FastAPI)

```bash
# 1. build the frontend once
cd frontend && npm install && npm run build && cd ..

# 2. run the backend (serves the built SPA too)
uvicorn app.api.main:app --port 8000
```

Open <http://localhost:8000>. Enter a task and choose **Offline** or **Real LLM**,
then **Build Team & Run**. For live development use `npm run dev` (Vite on
:5173, proxying `/api` to :8000).

| Page | What it shows |
|---|---|
| **Workspace** | task input, execution mode, example tasks, recent runs |
| **Execution** | SSE-driven live timeline; per-agent status, tool calls (with honest `web` / `local` / `offline mock` / `offline fallback` chips), evidence/sources counters |
| **Team** | the dynamic DAG actually built for the task (roles, layers, edges) |
| **Artifacts** | one card per real artifact, dependency flow, evidence/sources |
| **Result** | the assembled deliverable: Executive Summary, Key Findings, Cross-Agent Insights, Contradictions & Uncertainties, Trade-offs, Recommendations, original agent sections, Evidence and Sources |

## Recommended screenshots

| File | View | How to capture |
|---|---|---|
| `01-workspace.png` | Workspace — task + mode + examples | open `/`, capture the hero + input |
| `02-execution.png` | Running team timeline | run a task, capture the Execution page mid/after run (tool chips visible) |
| `03-team.png` | Dynamic team / DAG | open the Team tab |
| `04-artifacts.png` | Artifact collaboration + evidence/sources | open the Artifacts tab, select a card |
| `05-result.png` | Result reader with structured synthesis blocks | open the Result tab |
| `06-provenance.png` | Recommendation trace chain (`Recommendation → Insight → Evidence → Source`) | expand **Traceability** on a recommendation in the Result page |

## Real vs Offline in screenshots

- **Offline** runs show `offline_mock` sources with **no URL** — this is expected
  and must not be presented as real data.
- **Real** runs may still contain `offline mock` and `local` tools alongside
  `web`; that is the accurate per-tool status, not a bug.
- If a screenshot includes a real URL, make sure it comes from a real run with a
  configured search adapter.

## Alternative: a static offline artifact

A verified offline run already produces a human-readable deliverable:

```bash
python examples/real_world_demo.py
```

The report is written to `autoteam_output/<run_id>.md`; its **Key Findings**,
**Insights**, **Trade-offs**, **Recommendations**, **Evidence** and **Sources**
sections mirror what the Result page shows, and can be linked as a demonstrable
output without any screenshot tool.

## Legacy Streamlit demos (historical)

The three Streamlit pages are kept as legacy demos and remain covered by tests
— they are no longer the product entry point:

```bash
pip install -e ".[ui]"
streamlit run app/ui.py          # v0.1–0.3 demo
streamlit run app/ui_dynamic.py  # dynamic team formation
streamlit run app/ui_live.py     # v0.4 live view
```
