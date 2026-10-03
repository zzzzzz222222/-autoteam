"""Deterministic artifact validation (v0.5.0).

Schema + code rules only — no LLM judge, no scores. An artifact is rejected
before it can reach downstream agents or the final deliverable when:
- its identity/body is empty (schema),
- an ``Evidence`` references an unknown ``Source`` id
  (``InvalidEvidenceReference``),
- a source URL exists but is not http/https (fabricated URLs are forbidden;
  offline sources legitimately have no URL).
"""

from __future__ import annotations

from app.runtime.artifacts import AgentArtifact


class ArtifactValidationError(ValueError):
    pass


def validate_artifact(artifact: AgentArtifact) -> None:
    if not artifact.artifact_id.strip():
        raise ArtifactValidationError("artifact_id is empty")
    if not artifact.agent_id.strip():
        raise ArtifactValidationError("agent_id is empty")
    if not artifact.content.strip():
        raise ArtifactValidationError(f"{artifact.artifact_id}: content is empty")

    source_ids = {source.id for source in artifact.source_records}
    for item in artifact.evidence:
        # An empty source_id means "no source could be matched" (unverified
        # claim). Unknown non-empty ids are still rejected: links are never
        # fabricated just to satisfy this check.
        if item.source_id and item.source_id not in source_ids:
            raise ArtifactValidationError(
                f"InvalidEvidenceReference: {item.source_id!r} not in "
                f"{artifact.artifact_id} sources"
            )
    for source in artifact.source_records:
        if source.url and not source.url.startswith(("http://", "https://")):
            raise ArtifactValidationError(
                f"{artifact.artifact_id}: source '{source.id}' has a non-http url"
            )
