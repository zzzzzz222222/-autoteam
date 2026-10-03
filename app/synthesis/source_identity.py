"""Stable source identity for cross-agent provenance (v0.6.9, fixes F13).

Phase 6.8 showed that ``AgentRuntime._collect_evidence`` derived source ids from an
*artifact-local positional counter* (``source_001``, ``source_002`` ...) while
``evidence_filter.collect_evidence_records`` merges sources **by id** across
artifacts. Two different agents therefore produced the same ids for *different*
sources; the merge kept whichever record happened to be processed first, which

* made real web evidence look like an ``offline_mock`` stub (losing its URL), and
* in the opposite agent order would have made an offline stub look like a real
  web source with a URL.

This module makes a source's identity a deterministic function of *what the
source is*, never of execution order:

* a real retrieved source is identified by its **normalised URL**;
* a source with no URL (offline stub / local fixture) is identified by the
  **artifact that produced it plus its position in that artifact's result list**,
  so unrelated URL-less sources from different agents are never merged.

URL normalisation is deliberately conservative: only the scheme/host case and
default ports are normalised. Path, query string and fragment are preserved
verbatim because they can change which resource a URL points to, and the
original URL is always kept on the record for audit.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str) -> str:
    """Conservative URL normalisation used *only* to decide source identity.

    Lower-cases the scheme and host, drops a default port, and strips
    surrounding whitespace. Everything else (path, query, fragment, trailing
    slash) is preserved exactly — if two URLs differ in any of those, they stay
    different sources.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if not parts.scheme or not parts.netloc:
        return raw
    scheme = parts.scheme.lower()
    netloc = parts.netloc
    if "@" in netloc:  # keep userinfo as-is except for host case normalisation
        return raw
    host = netloc
    port = ""
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        if not port.isdigit():
            return raw
        if port == _DEFAULT_PORTS.get(scheme):
            port = ""
    host = host.lower()
    if host.startswith("www."):
        # "www." is a real subdomain in principle; keep it (conservative).
        pass
    normalized = urlunsplit(
        (scheme, f"{host}:{port}" if port else host, parts.path, parts.query, parts.fragment)
    )
    return normalized


def identity_basis(*, url: str, artifact_id: str, title: str, ordinal: int) -> str:
    """Return the identity key a source's id is derived from.

    URL-bearing sources: ``web:<normalised url>`` — the same page referenced by
    several agents shares one identity.
    URL-less sources: ``offline:<artifact id>:<ordinal>:<title>`` — never merged
    across artifacts, because there is no evidence they are the same source.
    """
    normalized = normalize_url(url)
    if normalized:
        return f"web:{normalized}"
    return f"offline:{artifact_id or 'unknown'}:{ordinal}:{(title or '').strip()}"


def source_id_for(basis: str) -> str:
    """Stable, collision-resistant id derived from the identity basis."""
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"src_{digest}"


def derive_source_identity(
    *,
    url: str,
    artifact_id: str,
    title: str,
    ordinal: int,
) -> tuple[str, str]:
    """Return ``(source_id, identity_basis)`` for one retrieved source record."""
    basis = identity_basis(url=url, artifact_id=artifact_id, title=title, ordinal=ordinal)
    return source_id_for(basis), basis


def url_conflicts(existing_url: str, incoming_url: str) -> bool:
    """True when two records claiming the same id point at different resources."""
    left, right = normalize_url(existing_url), normalize_url(incoming_url)
    if not left or not right:
        return False  # one side has no URL: not enough evidence to call a conflict
    return left != right


def is_conflict(
    *,
    existing_url: str,
    existing_type: str,
    incoming_url: str,
    incoming_type: str,
) -> list[str]:
    """Reasons why two records must *not* be merged despite sharing an id."""
    reasons: list[str] = []
    if url_conflicts(existing_url, incoming_url):
        reasons.append(f"different urls ({existing_url!r} vs {incoming_url!r})")
    if (existing_type or "") != (incoming_type or ""):
        reasons.append(
            f"conflicting source types ({existing_type or 'unknown'} vs "
            f"{incoming_type or 'unknown'})"
        )
    return reasons


def disambiguate(basis: str, taken: set[str], attempt: int = 1) -> str:
    """Deterministic alternative basis for a conflicting record (#1, #2, ...)."""
    candidate = f"{basis}#{attempt}"
    if candidate in taken:
        return disambiguate(basis, taken, attempt + 1)
    return candidate


def title_is_sane(title: str) -> bool:
    return bool((title or "").strip()) and not re.fullmatch(r"[\W_]*", (title or "").strip())
