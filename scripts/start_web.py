#!/usr/bin/env python3
"""Start the AutoTeam Web UI in one command (backend + optional frontend build).

Usage:
    python scripts/start_web.py            # backend ONLY (serves built SPA if present)
    python scripts/start_web.py --dev      # also runs `npm run dev` for the frontend

The backend always runs the existing FastAPI app (`uvicorn app.api.main:app`).
The frontend, when built once (`cd frontend && npm run build`), is served by the
same workspace at http://localhost:8000 — no second process needed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    args = sys.argv[1:]
    dev_mode = "--dev" in args

    backend = [sys.executable, "-m", "uvicorn", "app.api.main:app", "--port", "8000"]
    print("Starting AutoTeam Web API at http://localhost:8000 …")
    if dev_mode:
        navigator = shutil.which("npm")
        if navigator is None:
            print("npm not found; starting backend only.", file=sys.stderr)
            return subprocess.call(backend)
        build = subprocess.call([navigator, "run", "build"], cwd="frontend")
        if build != 0:
            print("frontend build failed; starting backend anyway", file=sys.stderr)
        return subprocess.call(backend)
    return subprocess.call(backend)


if __name__ == "__main__":
    raise SystemExit(main())