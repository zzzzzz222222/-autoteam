# AutoTeam — Screenshots Guide

This page documents the Streamlit views worth capturing for the GitHub README and where to take them. Screenshots are intentionally **not** pre-generated here so the images always reflect the current UI.

## How to run the UI

```bash
pip install -e ".[ui]"
streamlit run app/ui.py
```

The UI runs fully offline. A browser tab opens at `http://localhost:8501`.

## Recommended screenshots

| File | View | How to capture |
|---|---|---|
| `01-overview.png` | `app/ui.py` homepage — task input + overall pipeline | Run `app/ui.py`, screen-capture the landing view |
| `02-dynamic-team.png` | Dynamic team formation (`app/ui_dynamic.py`) | `streamlit run app/ui_dynamic.py`, capture the team/topology panel |
| `03-execution.png` | Live execution + timeline (`app/ui_live.py`) | `streamlit run app/ui_live.py`, capture the timeline / run info |
| `04-artifacts.png` | Artifact collaboration + evidence | From the Live View, pluck an agent artifact card showing `Sources` / `Evidence` |
| `05-final-deliverable.png` | Final Markdown deliverable | From the Live View, the "Final Markdown" section (with `## Sources` / `## Evidence`) |

## Alternative: a static offline artifact

If screenshots are inconvenient, a verified offline run already produces a human-readable deliverable:

```bash
python examples/real_world_demo.py
```

The final report is written to `autoteam_output/<run_id>.md`. Its **Evidence** and **Sources** sections mirror what the UI shows, and can be linked as a demonstrable output without any screenshot tool.