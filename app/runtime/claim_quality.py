"""Deterministic claim-quality assessment (v0.6.1).

Agents occasionally emit non-claims as ``key_points``: Markdown table rows,
header separators, raw JSON fragments or sentences cut off mid-word. Those must
not be treated as facts, and must not be matched against retrieved snippets just
because they happen to contain a number.

The gate is deliberately *non-destructive*: a low-quality point is kept in the
evidence record (so nothing is silently lost) but is marked unverified and is
never bound to a source. It does **not** change any matching threshold — the
Phase 5 rule ("bind by content, or do not bind") still holds.
"""

from __future__ import annotations

import re

# Below this length a "claim" carries too little context to verify.
MIN_USABLE_CHARS = 6

# A Markdown table separator row: | --- | :---: | etc.
_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]*-{2,}[\s:|-]*\|?$")
# A balanced JSON object/array fragment.
_JSON_RE = re.compile(r"^[{\[].*[}\]]$", re.DOTALL)
# Markdown decoration that must not be the whole claim.
_DECORATION_RE = re.compile(r"^[\s*_`#>~\-|]+$")
# A claim that stops at these characters looks truncated.
_INCOMPLETE_ENDINGS = ("|", ",", ";", ":", "，", "：", "、")


def assess_claim(text: str) -> tuple[bool, str]:
    """Return ``(is_usable, reason)``. ``reason`` is empty when usable."""
    value = " ".join((text or "").split())
    if not value:
        return False, "empty"
    if len(value) < MIN_USABLE_CHARS:
        return False, "too_short"
    if _DECORATION_RE.match(value):
        return False, "markdown_decoration"
    if _SEPARATOR_RE.match(value):
        return False, "markdown_table_separator"
    pipes = value.count("|")
    if pipes >= 2 and (value.startswith("|") or value.endswith("|")):
        return False, "markdown_table_row"
    if pipes >= 4:
        return False, "table_like"
    if _JSON_RE.match(value):
        return False, "json_fragment"
    if value.endswith(_INCOMPLETE_ENDINGS):
        return False, "incomplete_text"
    if not any(char.isalnum() for char in value):
        return False, "no_words"
    return True, ""


def is_usable_claim(text: str) -> bool:
    """Convenience wrapper used by the runtime."""
    return assess_claim(text)[0]
