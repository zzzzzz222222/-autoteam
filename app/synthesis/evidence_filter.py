"""Deterministic evidence processing (v0.6.0).

Turns ``AgentArtifact[]`` into normalised ``EvidenceRecord[]`` + ``SourceRecord[]``
with complete provenance. IDs, deduplication, URL validation and producer
attribution are all computed here — never proposed by an LLM.

Rules:
- every evidence record keeps its source url / title / type
- ``producer_agent`` / ``artifact_id`` come from the owning artifact
- ``evidence_id`` is stable (hash of claim + source + artifact)
- exact-duplicate claims (same claim + source) are merged
- duplicate sources (same id, or same url when url is non-empty) are merged
- ``structured_data`` values that look like JSON are parsed for relevance, but
  the original text is always preserved when parsing fails
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from app.runtime.artifacts import AgentArtifact
from app.synthesis.models import EvidenceRecord, ReportBundle, SourceRecord
from app.synthesis.source_identity import (
    disambiguate,
    is_conflict,
    normalize_url,
    source_id_for,
)
from app.synthesis.source_policy import downgrade_unverified_claim

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# v0.6.6 (A10): an observed fetch failure is recorded, never hidden. Any
# non-empty status other than "ok" means the content could not be re-checked.
_ACCESS_OK = {"", "ok", "success", "200"}
# Source types that are, by design, not retrievable online.
_OFFLINE_SOURCE_TYPES = {"offline_mock", "offline_fallback"}


def access_failed(status: str) -> bool:
    return (status or "").strip().lower() not in _ACCESS_OK


def review_status_for(source_id: str, source: SourceRecord | None) -> str:
    """Bound -> ``not_checked``; bound but unfetchable -> ``source_unavailable``."""
    if not source_id:
        return "unsupported"
    if source is not None and access_failed(source.access_status):
        return "source_unavailable"
    return "not_checked"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("␟".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _try_parse_json(value: str) -> object | None:
    """Best-effort JSON parse for flattened structured_data values."""
    text = (value or "").strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _relevance_hint(artifact: AgentArtifact, claim: str) -> str:
    """Keep a short relation label from structured_data when one matches."""
    lowered = claim.lower()
    for key, value in artifact.structured_data.items():
        parsed = _try_parse_json(value)
        rendered = value if parsed is None else json.dumps(parsed, ensure_ascii=False)
        if key.lower() in lowered or any(
            token and token in lowered for token in re.findall(r"[a-zA-Z_]{4,}", key.lower())
        ):
            return f"{key}={rendered[:120]}"
    return artifact.output_type.value


def _basis_for(source: object, artifact_id: str) -> str:
    """Identity basis for one runtime ``Source`` record.

    Priority: explicit identity -> normalised URL -> artifact-scoped fallback.
    The artifact-scoped fallback is what keeps two agents' unrelated URL-less
    stubs apart (F13), while a shared URL unifies the same page across agents.
    """
    url = (getattr(source, "url", "") or "").strip()
    if url and not _URL_RE.match(url):
        url = ""  # non-http(s) urls are rejected defensively (never mutated)
    normalized = normalize_url(url)
    if normalized:
        return f"web:{normalized}"
    explicit = str(getattr(source, "identity", "") or "").strip()
    if explicit:
        return explicit
    local_id = str(getattr(source, "id", "") or "")
    return f"offline:{artifact_id or 'unknown'}:{local_id}"


@dataclass
class _SourceContribution:
    """One artifact's view of a source (never merged destructively)."""

    artifact_id: str
    producer: str
    local_id: str
    basis: str
    title: str
    url: str
    source_type: str
    retrieved_at: str
    access_status: str
    access_note: str
    identity: str

    @property
    def signature(self) -> tuple[str, str]:
        """What must agree for two records to be the *same* source."""
        return (normalize_url(self.url), self.source_type or "offline_mock")


def _pick_title(contributions: list[_SourceContribution]) -> tuple[str, list[str]]:
    titles = sorted({c.title.strip() for c in contributions if c.title.strip()})
    if not titles:
        return "", []
    return titles[0], titles[1:]


def _merge_access(contributions: list[_SourceContribution]) -> tuple[str, str]:
    """Any observed failure wins — an unreachable source is never silently 'ok'."""
    failures = sorted(
        {
            (c.access_status.strip(), (c.access_note or "").strip())
            for c in contributions
            if access_failed(c.access_status)
        }
    )
    if failures:
        return failures[0][0], failures[0][1]
    statuses = sorted({c.access_status.strip() for c in contributions if c.access_status.strip()})
    return (statuses[0] if statuses else ""), ""


def _build_source_record(
    canonical_id: str, basis: str, contributions: list[_SourceContribution]
) -> SourceRecord:
    """Deterministically merge one identity's contributions (order-independent)."""
    title, alt_titles = _pick_title(contributions)
    urls = sorted({c.url.strip() for c in contributions if c.url.strip()})
    access_status, access_note = _merge_access(contributions)
    retrieved = sorted({c.retrieved_at.strip() for c in contributions if c.retrieved_at.strip()})
    return SourceRecord(
        source_id=canonical_id,
        title=title,
        url=urls[0] if urls else "",
        source_type=contributions[0].source_type or "offline_mock",
        retrieved_at=retrieved[0] if retrieved else "",
        identity=basis,
        alt_titles=alt_titles,
        # Order-dependent, informational only: never used for identity or counts.
        first_seen_agent=contributions[0].producer,
        access_status=access_status,
        access_note=access_note,
        producer_agents=sorted({c.producer for c in contributions if c.producer}),
        artifact_ids=sorted({c.artifact_id for c in contributions if c.artifact_id}),
    )


def collect_evidence_records(
    artifacts: list[AgentArtifact], *, conflicts: list[dict] | None = None
) -> tuple[list[EvidenceRecord], list[SourceRecord]]:
    """Normalise all artifacts into deduplicated evidence + source records.

    v0.6.9 (F13): sources are identified by *content* (``source_identity``), not by
    an artifact-local counter. Contributions are grouped first and merged
    afterwards with deterministic rules, so the result never depends on the order
    in which agents finished. When one identity carries conflicting url/type
    claims the records are **split** (never overwritten) and the conflict is
    reported through the optional ``conflicts`` out-list.
    """
    evidence_index: dict[str, EvidenceRecord] = {}
    claim_seen: set[tuple[str, str]] = set()
    # artifact_id -> {local source id -> canonical source id}
    local_maps: dict[str, dict[str, str]] = {}
    contributions: dict[str, list[_SourceContribution]] = {}

    # --- pass 1: gather every artifact's source contributions -----------------
    for artifact in artifacts:
        artifact_id = artifact.artifact_id
        producer = str(artifact.metadata.get("role_name") or artifact.agent_id or "")
        local_maps.setdefault(artifact_id, {})
        for source in artifact.source_records:
            basis = _basis_for(source, artifact_id)
            raw_url = str(source.url or "").strip()
            if raw_url and not _URL_RE.match(raw_url):
                raw_url = ""  # defensive: never surface a non-http(s) URL (input is not mutated)
            contributions.setdefault(basis, []).append(
                _SourceContribution(
                    artifact_id=artifact_id,
                    producer=producer,
                    local_id=str(source.id),
                    basis=basis,
                    title=str(source.title or ""),
                    url=raw_url,
                    source_type=str(source.source_type or "offline_mock"),
                    retrieved_at=str(source.retrieved_at or ""),
                    access_status=str(getattr(source, "access_status", "") or ""),
                    access_note=str(getattr(source, "access_note", "") or ""),
                    identity=str(getattr(source, "identity", "") or ""),
                )
            )

    # --- pass 2: resolve identities deterministically -------------------------
    source_index: dict[str, SourceRecord] = {}
    taken_ids: set[str] = set()
    for basis in sorted(contributions):
        grouped: dict[tuple[str, str], list[_SourceContribution]] = {}
        for contribution in contributions[basis]:
            grouped.setdefault(contribution.signature, []).append(contribution)
        # Conflicting signatures for one basis are split in a fixed order, so the
        # same input set always yields the same ids regardless of arrival order.
        # Decision rule: the *real* (non-offline) claim keeps the base identity,
        # because an offline stub claiming a URL is the weaker provenance claim.
        def _order(signature: tuple[str, str]) -> tuple[int, tuple[str, str]]:
            return (1 if signature[1] in _OFFLINE_SOURCE_TYPES else 0, signature)

        for index, signature in enumerate(sorted(grouped, key=_order)):
            members = grouped[signature]
            canonical_basis = basis
            if index:
                canonical_basis = disambiguate(basis, taken_ids, index)
            canonical_id = source_id_for(canonical_basis)
            while canonical_id in taken_ids:  # hash collision safety
                canonical_basis = disambiguate(basis, taken_ids, len(taken_ids) + 1)
                canonical_id = source_id_for(canonical_basis)
            taken_ids.add(canonical_id)
            source_index[canonical_id] = _build_source_record(
                canonical_id, canonical_basis, members
            )
            for member in members:
                local_maps.setdefault(member.artifact_id, {})[member.local_id] = canonical_id
            if index and conflicts is not None:
                kept = grouped[sorted(grouped, key=_order)[0]][0]
                reasons = is_conflict(
                    existing_url=kept.url,
                    existing_type=kept.source_type,
                    incoming_url=members[0].url,
                    incoming_type=members[0].source_type,
                )
                conflicts.append(
                    {
                        "basis": basis,
                        "kept_source_id": source_id_for(basis),
                        "split_source_id": canonical_id,
                        "reason": "; ".join(reasons)
                        or "same identity basis carried conflicting claims",
                        "kept": {
                            "url": kept.url,
                            "source_type": kept.source_type,
                            "artifact_ids": sorted(
                                {c.artifact_id for c in grouped[sorted(grouped, key=_order)[0]]}
                            ),
                        },
                        "split": {
                            "url": members[0].url,
                            "source_type": members[0].source_type,
                            "artifact_ids": sorted({c.artifact_id for c in members}),
                        },
                    }
                )

    # --- pass 3: evidence records (mapped to canonical source ids) -----------
    for artifact in artifacts:
        artifact_id = artifact.artifact_id
        producer = str(artifact.metadata.get("role_name") or artifact.agent_id or "")
        local_map = local_maps.get(artifact_id, {})
        for item in artifact.evidence:
            source_id = item.source_id
            mapped = local_map.get(source_id) if source_id else None
            if mapped is not None:
                source_id = mapped
            claim_key = (item.claim.strip().lower(), source_id)
            if item.claim.strip() and claim_key in claim_seen:
                continue
            if item.claim.strip():
                claim_seen.add(claim_key)
            evidence_id = item.evidence_id or _stable_id(
                "ev", artifact_id, item.claim, source_id
            )
            source = source_index.get(source_id)
            snippet = (item.evidence or "").strip()
            record = EvidenceRecord(
                evidence_id=evidence_id,
                claim=item.claim,
                evidence=item.evidence,
                source_id=source_id,
                source_url=source.url if source else "",
                source_title=source.title if source else "",
                source_type=source.source_type if source else "",
                producer_agent=item.producer_agent or producer,
                artifact_id=item.artifact_id or artifact_id,
                relevance=_relevance_hint(artifact, item.claim),
                # v0.6.6 (A1/A3): a "source_fact" whose snippet was never
                # retrieved is downgraded — an agent's own text is not a source.
                claim_type=downgrade_unverified_claim(
                    getattr(item, "claim_type", "") or "", source_id, snippet
                ),
                match_score=float(getattr(item, "match_score", 0.0) or 0.0),
                match_method=str(getattr(item, "match_method", "") or ""),
                # A bound source is only "not checked"; it is never auto-verified.
                review_status=review_status_for(source_id, source),
                verified=False,
            )
            evidence_index[record.evidence_id] = record

        # --- deliverable key_points without evidence become weak records ---
        # Only when the artifact has source_records to point at, so provenance
        # is never fabricated. Skipped when matching claims already exist.
        if artifact.content and artifact.source_records and not artifact.evidence:
            # Lines become UNBOUND claims: we have no retrieved snippet proving
            # which source supports them, so no source is attached at all.
            for line in artifact.content.splitlines()[:20]:
                point = line.strip().lstrip("-* ").strip()
                if not point or point.startswith("**"):
                    continue
                claim_key = (point.lower(), "")
                if claim_key in claim_seen:
                    continue
                claim_seen.add(claim_key)
                evidence_id = _stable_id("ev", artifact_id, point, "unbound")
                if evidence_id in evidence_index:
                    continue
                evidence_index[evidence_id] = EvidenceRecord(
                    evidence_id=evidence_id,
                    claim=point[:300],
                    evidence="",
                    source_id="",
                    source_url="",
                    source_title="",
                    source_type="",
                    producer_agent=producer,
                    artifact_id=artifact_id,
                    relevance=_relevance_hint(artifact, point),
                    review_status="unsupported",
                    match_method="no_evidence_records",
                    verified=False,
                )

    return list(evidence_index.values()), [
        source_index[key] for key in sorted(source_index)
    ]


def validate_evidence_references(
    claimed_ids: list[str], known: set[str]
) -> tuple[list[str], list[str]]:
    """Split claimed evidence ids into (valid, invalid). No auto-repair."""
    valid: list[str] = []
    invalid: list[str] = []
    for raw in claimed_ids:
        item = (raw or "").strip()
        if item and item in known:
            if item not in valid:
                valid.append(item)
        elif item:
            invalid.append(item)
    return valid, invalid


def validate_report_references(bundle: ReportBundle) -> list[str]:
    """Deterministic cross-reference audit of a finished ``ReportBundle``.

    Pure code — no LLM judge, no scoring. Returns human-readable issues for
    dangling references so the caller can surface "reference missing" instead of
    fabricating a link. An empty list means every link in the report resolves.
    """
    issues: list[str] = []
    evidence_ids = [item.evidence_id for item in bundle.evidence]
    duplicates = sorted({eid for eid in evidence_ids if evidence_ids.count(eid) > 1})
    for eid in duplicates:
        issues.append(f"duplicate evidence id: {eid}")

    seen_ids = set(evidence_ids)
    source_ids = {item.source_id for item in bundle.sources}
    for item in bundle.evidence:
        if item.source_id and item.source_id not in source_ids:
            issues.append(f"evidence {item.evidence_id} references missing source {item.source_id}")

    synthesis = bundle.synthesis
    insight_ids = {item.insight_id for item in synthesis.cross_agent_insights}
    tradeoff_ids = {item.tradeoff_id for item in synthesis.tradeoffs}

    findings = (
        synthesis.key_findings
        + synthesis.supported_findings
        + synthesis.single_source_findings
    )
    # (item kind, item id, referenced ids, valid set, referenced kind)
    checks: list[tuple[str, str, list[str], set[str], str]] = []
    checks += [
        ("finding", item.finding_id or "?", item.evidence_ids, seen_ids, "evidence")
        for item in findings
    ]
    checks += [
        ("insight", item.insight_id, item.supporting_evidence_ids, seen_ids, "evidence")
        for item in synthesis.cross_agent_insights
    ]
    checks += [
        ("contradiction", item.contradiction_id, item.evidence_ids, seen_ids, "evidence")
        for item in synthesis.contradictions
    ]
    checks += [
        ("trade-off", item.tradeoff_id, item.evidence_ids, seen_ids, "evidence")
        for item in synthesis.tradeoffs
    ]
    for item in synthesis.recommendations:
        rec = item.recommendation_id
        checks += [
            ("recommendation", rec, item.supporting_evidence_ids, seen_ids, "evidence"),
            ("recommendation", rec, item.supporting_insight_ids, insight_ids, "insight"),
            ("recommendation", rec, item.supporting_tradeoff_ids, tradeoff_ids, "trade-off"),
        ]
    for kind, item_id, refs, valid, ref_kind in checks:
        for ref in refs:
            if ref not in valid:
                issues.append(f"{kind} {item_id} → missing {ref_kind} {ref}")
    for item in synthesis.cross_agent_insights:
        if not item.supporting_evidence_ids:
            issues.append(f"insight {item.insight_id} has no supporting evidence")
    return issues
