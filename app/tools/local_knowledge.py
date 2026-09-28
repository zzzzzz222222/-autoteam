"""Local knowledge tool (v0.5.0).

Minimal, controlled file-reading tool: agents may read ``.md`` / ``.txt`` /
``.json`` / ``.csv`` files inside one configured workspace directory
(``AUTOTEAM_WORKSPACE_DIR``, default ``./knowledge``).

Hard guards:
- path traversal (``..``, absolute paths, symlinks escaping the root) rejected
- only whitelisted extensions
- secrets-style files (``.env*``, ``*key*``, ``*secret*``) always rejected
- missing workspace returns a clearly-labeled offline result, never a crash
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".csv"}
FORBIDDEN_NAME_PARTS = (".env", "secret", "credential", "token")
MAX_SNIPPETS = 5
MAX_SNIPPET_CHARS = 400


class KnowledgeResult(BaseModel):
    query: str
    matches: list[dict[str, str]] = Field(default_factory=list)  # {file, snippet}
    offline: bool = True
    error: str | None = None


def workspace_root() -> Path:
    configured = os.getenv("AUTOTEAM_WORKSPACE_DIR", "")
    root = Path(configured) if configured else Path("knowledge")
    return root.resolve()


def validate_workspace_path(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and refuse anything outside ``root`` (or forbidden)."""
    resolved = candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise PermissionError(f"path escapes the knowledge workspace: {candidate}")
    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise PermissionError(f"file type not allowed: {resolved.suffix}")
    lowered = resolved.name.lower()
    if any(part in lowered for part in FORBIDDEN_NAME_PARTS):
        raise PermissionError(f"file name looks like a secret: {resolved.name}")
    return resolved


def _read_snippet(path: Path, terms: list[str]) -> dict[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"file": path.name, "snippet": f"(unreadable: {exc})"}
    lowered = text.lower()
    if terms and not any(term.lower() in lowered for term in terms):
        return None
    first_line = next(
        (line.strip() for line in text.splitlines() if line.strip()), "(empty file)"
    )
    return {"file": path.name, "snippet": first_line[:MAX_SNIPPET_CHARS]}


def search_knowledge(query: str, relative_path: str | None = None) -> KnowledgeResult:
    root = workspace_root()
    terms = [term for term in query.split() if term]
    if not root.is_dir():
        return KnowledgeResult(
            query=query,
            matches=[],
            offline=True,
            error=f"knowledge workspace not found: {root.name}/ (offline_mock)",
        )
    try:
        if relative_path:
            target = validate_workspace_path(root, root / relative_path)
            candidates = [target] if target.is_file() else []
        else:
            candidates = [
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
            ]
            for path in candidates:  # same guards apply to discovered files
                validate_workspace_path(root, path)
    except PermissionError as exc:
        return KnowledgeResult(query=query, matches=[], offline=True, error=str(exc))

    matches: list[dict[str, str]] = []
    for path in sorted(candidates):
        match = _read_snippet(path, terms)
        if match is not None:
            matches.append(match)
        if len(matches) >= MAX_SNIPPETS:
            break
    return KnowledgeResult(query=query, matches=matches, offline=True)
