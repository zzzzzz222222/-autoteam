"""Redaction helpers for validation records.

Validation artefacts are meant to be auditable, which means they are meant to
be readable — but never at the cost of leaking credentials or user data. Every
value that leaves a run (URLs, error strings, provider diagnostics) passes
through this module first.

Rules
-----
* URLs keep ``scheme://host/path``; query strings and fragments are dropped
  (they routinely carry API keys, tokens or PII).
* Free text is scanned for common credential shapes and replaced by
  ``[redacted]``.
* Nothing here ever *reads* secret values from the environment; it only scrubs
  text that is about to be persisted.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[redacted]"

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\btvly-[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    # JWT-ish triplets (e.g. Supabase / Google service tokens).
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{4,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|apikey|authorization|access[_-]?token|secret)\b\s*[:=]\s*['\"]?[^\s'\",]{6,}"),
)


def redact_text(value: object, *, limit: int = 300) -> str:
    """Return ``value`` as a scrubbed, length-limited string.

    ``limit`` bounds the stored text so a stack trace or HTTP body cannot blow
    up the metrics file; ``0`` means "no truncation".
    """
    text = "" if value is None else str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = text.replace("\r\n", " ").replace("\n", " ").strip()
    if limit and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def sanitize_url(url: str | None, *, limit: int = 200) -> str:
    """Keep only ``scheme://host/path``; drop query, fragment and credentials.

    Returns ``""`` for empty input and ``"[invalid-url]"`` when the value is not
    parseable — never echoes the raw string back.
    """
    if not url or not str(url).strip():
        return ""
    raw = str(url).strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "[invalid-url]"
    if not parts.scheme or not parts.netloc:
        # Not an absolute URL (offline stubs use ""), keep it opaque.
        return "[relative-url]" if parts.path else ""
    # Strip userinfo (user:pass@host) if present.
    host = parts.netloc.rsplit("@", 1)[-1]
    clean = urlunsplit((parts.scheme, host, parts.path or "/", "", ""))
    return clean[:limit]


def domain_of(url: str | None) -> str:
    """Hostname of a URL (for compact reporting); ``""`` when unavailable."""
    if not url:
        return ""
    try:
        return urlsplit(str(url).strip()).netloc.rsplit("@", 1)[-1].lower()
    except ValueError:
        return ""


def is_external_url(url: str | None) -> bool:
    """True for http(s) URLs — the only scheme treated as a real web source."""
    if not url:
        return False
    try:
        return urlsplit(str(url).strip()).scheme in {"http", "https"}
    except ValueError:
        return False
