"""Tolerant, *classified* structured-output parsing (v0.6.1).

The provider must never pretend malformed model output is valid JSON, and it
must never guess. This module:

* extracts a JSON payload only when the **whole** content is JSON, or when it is
  a single explicit fenced block (```json … ```). It never scrapes the first
  ``{`` … last ``}`` out of arbitrary prose;
* classifies every failure (empty / not_json / truncated / invalid_json /
  schema_mismatch / wrong_type) so callers can retry, degrade and audit;
* records only **safe diagnostics** — length, a short hash, delimiter balance,
  first/last character and the JSON error position. Never the raw content,
  which may contain user data or credentials.

The parser is deliberately conservative: a truncated payload is reported as
``truncated`` and is *not* repaired, because a repaired fragment cannot be
trusted as the model's intended answer.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, ValidationError

# Failure categories (stable strings; safe to persist in metrics/events).
CATEGORY_EMPTY = "empty"
CATEGORY_NOT_JSON = "not_json"
CATEGORY_TRUNCATED = "truncated"
CATEGORY_INVALID_JSON = "invalid_json"
CATEGORY_SCHEMA_MISMATCH = "schema_mismatch"
CATEGORY_WRONG_TYPE = "wrong_type"
# The endpoint told us the response stopped because it hit the length cap.
CATEGORY_LENGTH_LIMIT = "length_limit"

# Categories that a *re-ask* can plausibly fix (the model just formatted badly).
# Network/auth/budget failures are NOT in here and must not be retried blindly.
RETRYABLE_CATEGORIES = frozenset(
    {
        CATEGORY_EMPTY,
        CATEGORY_NOT_JSON,
        CATEGORY_TRUNCATED,
        CATEGORY_INVALID_JSON,
        CATEGORY_WRONG_TYPE,
        CATEGORY_SCHEMA_MISMATCH,
        CATEGORY_LENGTH_LIMIT,
    }
)

# A single fenced block, optionally tagged ```json / ```JSON.
_FENCE_RE = re.compile(r"```[ \t]*(?:json)?[ \t]*\r?\n?(.*?)```", re.IGNORECASE | re.DOTALL)


class StructuredParseError(ValueError):
    """Raised when model output cannot be safely parsed into the response model."""

    def __init__(self, category: str, message: str, *, diagnostics: str = "") -> None:
        super().__init__(message)
        self.category = category
        self.diagnostics = diagnostics
        self.retryable = category in RETRYABLE_CATEGORIES


def safe_diagnostics(text: str) -> str:
    """A short, non-reversible description of a payload (never its content)."""
    value = text or ""
    digest = hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()[:12]
    return (
        f"len={len(value)} sha={digest} "
        f"brace_delta={value.count('{') - value.count('}')} "
        f"bracket_delta={value.count('[') - value.count(']')} "
        f"starts={value[:1]!r} ends={value[-1:]!r}"
    )


def _looks_truncated(text: str, error: json.JSONDecodeError) -> bool:
    """True only when the failure is consistent with an incomplete payload.

    A trailing comma or a stray token is *invalid* JSON, not truncated JSON —
    the delimiters decide, so a balanced-but-untidy payload is never reported as
    "cut off" (and therefore never silently repaired).
    """
    balanced = (
        text.count("{") == text.count("}")
        and text.count("[") == text.count("]")
    )
    return (not balanced) or "Unterminated string" in error.msg


def extract_json_text(content: str | None) -> tuple[str, str]:
    """Return ``(json_text, strategy)`` or raise :class:`StructuredParseError`.

    Strategies: ``raw`` (whole content is JSON), ``fenced`` (whole content is a
    single fenced block), ``fenced_with_prose`` (a fenced block plus a short
    explanation around it).
    """
    text = (content or "").strip()
    if not text:
        raise StructuredParseError(
            CATEGORY_EMPTY, "model returned an empty response", diagnostics="len=0"
        )
    if text[0] in "{[":
        return text, "raw"
    fences = [block.strip() for block in _FENCE_RE.findall(text)]
    json_blocks = [block for block in fences if block[:1] in "{["]
    if len(json_blocks) == 1:
        outside = _FENCE_RE.sub("", text).strip()
        return json_blocks[0], ("fenced" if not outside else "fenced_with_prose")
    raise StructuredParseError(
        CATEGORY_NOT_JSON,
        "response is not a JSON object/array (no safe payload found)",
        diagnostics=safe_diagnostics(text),
    )


def parse_structured(content: str | None, response_model: type[BaseModel]) -> BaseModel:
    """Parse + validate model output. Raises :class:`StructuredParseError`."""
    text, strategy = extract_json_text(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        category = CATEGORY_TRUNCATED if _looks_truncated(text, exc) else CATEGORY_INVALID_JSON
        detail = f"{strategy} pos={exc.pos} msg={exc.msg[:60]!r}"
        raise StructuredParseError(
            category,
            f"JSON decode failed: {exc.msg}",
            diagnostics=f"{detail} {safe_diagnostics(text)}",
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredParseError(
            CATEGORY_WRONG_TYPE,
            f"expected a JSON object, got {type(payload).__name__}",
            diagnostics=f"{strategy} {safe_diagnostics(text)}",
        )
    try:
        return response_model.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
        raise StructuredParseError(
            CATEGORY_SCHEMA_MISMATCH,
            f"schema validation failed ({exc.error_count()} error(s)) at {location}",
            diagnostics=f"strategy={strategy} {safe_diagnostics(text)}",
        ) from exc
