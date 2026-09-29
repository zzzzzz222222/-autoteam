"""FastAPI application entry for the AutoTeam Web API.

Run: uvicorn app.api.main:app --reload --port 8000
Also serves the built Vue frontend (``frontend/dist``) when present so the
product opens at http://localhost:8000 with a single process in production.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

app = FastAPI(title="AutoTeam Web API", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev: Vite on :5173; tighten before any deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# ---- serve the built frontend (frontend/dist) if present ----------------
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _serve_spa(path: str) -> FileResponse:
    index = _DIST / "index.html"
    return FileResponse(index)


if _DIST.is_dir() and (index := _DIST / "index.html").exists():

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(_DIST / "favicon.ico") if (_DIST / "favicon.ico").exists() else index

    if (_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:  # noqa: ARG001
        return _serve_spa(path)


__all__ = ["app"]