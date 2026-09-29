"""AutoTeam Web API (v0.5.0 UI refactor).

A thin FastAPI adapter over the existing AutoTeam Core. Nothing here
re-implements orchestration: it receives HTTP requests, runs the existing
``TaskExecutionSession.execute_task`` in a background thread exactly like the
v0.2 Live View did, and re-exposes the Core's own execution plan, trace,
artifacts and final deliverable as structured JSON / SSE.
"""