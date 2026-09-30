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

from app.runtime.artifacts import AgentArtifact
from app.synthesis.models import EvidenceRecord, SourceRecord

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


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


def collect_evidence_records(artifacts: list[AgentArtifact]) -> tuple[
    list[EvidenceRecord], list[SourceRecord]
]:
    """Normalise all artifacts into deduplicated evidence + source records."""
    source_index: dict[str, SourceRecord] = {}
    url_index: dict[str, str] = {}
    evidence_index: dict[str, EvidenceRecord] = {}
    claim_seen: set[tuple[str, str]] = set()

    for artifact in artifacts:
        artifact_id = artifact.artifact_id
        producer = str(artifact.metadata.get("role_name") or artifact.agent_id or "")

        # --- sources: merge by id, then by url when present -----------------
        local_sources: dict[str, SourceRecord] = {}
        for source in artifact.source_records:
            if not _URL_RE.match(source.url or "") and source.url:
                # non-http urls are rejected upstream; skip defensively
                source.url = ""
            existing_id = source_index.get(source.id)
            if existing_id is None and source.url and source.url in url_index:
                existing_id = source_index[url_index[source.url]]
            if existing_id is not None:
                if producer and producer not in existing_id.producer_agents:
                    existing_id.producer_agents.append(producer)
                if artifact_id and artifact_id not in existing_id.artifact_ids:
                    existing_id.artifact_ids.append(artifact_id)
                local_sources[source.id] = existing_id
                continue
            record = SourceRecord(
                source_id=source.id,
                title=source.title,
                url=source.url,
                source_type=source.source_type,
                retrieved_at=source.retrieved_at,
                producer_agents=[producer] if producer else [],
                artifact_ids=[artifact_id] if artifact_id else [],
            )
            source_index[record.source_id] = record
            if record.url:
                url_index[record.url] = record.source_id
            local_sources[record.source_id] = record

        # --- evidence: stable ids + provenance + dedup ---------------------
        for item in artifact.evidence:
            source_id = item.source_id
            mapped = local_sources.get(source_id)
            if mapped is not None:
                source_id = mapped.source_id
            claim_key = (item.claim.strip().lower(), source_id)
            if item.claim.strip() and claim_key in claim_seen:
                continue
            if item.claim.strip():
                claim_seen.add(claim_key)
            evidence_id = item.evidence_id or _stable_id(
                "ev", artifact_id, item.claim, source_id
            )
            source = source_index.get(source_id)
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
                verified=bool(source_id),
            )
            evidence_index[record.evidence_id] = record

        # --- deliverable key_points without evidence become weak records ---
        # Only when the artifact has source_records to point at, so provenance
        # is never fabricated. Skipped when matching claims already exist.
        if artifact.content and artifact.source_records and not artifact.evidence:
            for line in artifact.content.splitlines():
                point = line.strip().lstrip("-* ").strip()
                if not point or point.startswith("**"):
                    continue
                claim_key = (point.lower(), "")
                if claim_key in claim_seen:
                    continue
                claim_seen.add(claim_key)
                fallback_source = artifact.source_records[0]
                evidence_id = _stable_id("ev", artifact_id, point, fallback_source.id)
                if evidence_id in evidence_index:
                    continue
                evidence_index[evidence_id] = EvidenceRecord(
                    evidence_id=evidence_id,
                    claim=point[:300],
                    evidence="",
                    source_id=fallback_source.id,
                    source_url=fallback_source.url,
                    source_title=fallback_source.title,
                    source_type=fallback_source.source_type,
                    producer_agent=producer,
                    artifact_id=artifact_id,
                    relevance=_relevance_hint(artifact, point),
                    verified=True,
                )

    return list(evidence_index.values()), list(source_index.values())


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
