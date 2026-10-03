"""Final artifact assembly (v0.4.0).

Combines the agents' intermediate artifacts into one readable ``FinalArtifact``.
Section structure is derived from the artifacts themselves (ordered by the
team's execution layers) — there is no fixed report template, and no universal
Writer agent is required.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.runtime.artifacts import AgentArtifact, Evidence, Source, now_iso


class FinalSection(BaseModel):
    title: str
    agent_id: str = ""
    agent_name: str = ""
    output_type: str = ""
    content: str = ""
    structured_data: dict[str, str] = Field(default_factory=dict)


def _clip(value: object, limit: int) -> str:
    """Flatten and truncate long text so raw dumps never enter the report body."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class FinalArtifact(BaseModel):
    title: str
    summary: str = ""
    sections: list[FinalSection] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    source_records: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    contributing_agents: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    def to_markdown(self) -> str:
        lines: list[str] = [f"# {self.title}", ""]
        run_id = str(self.metadata.get("run_id", ""))
        status = str(self.metadata.get("status", ""))
        if run_id:
            lines.append(f"_AutoTeam run `{run_id}` · status **{status}** · {now_iso()}_")
            lines.append("")
        if self.metadata.get("fallback_used"):
            reason = str(self.metadata.get("fallback_reason") or "see synthesis.json")
            if self.metadata.get("partial_stages_used"):
                lines.extend(
                    [
                        f"> **Partial synthesis** — {_clip(reason, 300)}",
                        "> The synthesis sections below are the validated output of the "
                        "stages that succeeded; the remaining categories are empty rather "
                        "than invented. Every citation is still traceable.",
                        "",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"> **Degraded synthesis** — {_clip(reason, 300)}",
                        "> The synthesis sections below are deterministic fallback output, "
                        "not cross-agent conclusions. Every citation is still traceable.",
                        "",
                    ]
                )
        lines.extend(["## Executive Summary", "", self.summary, ""])
        # v0.6.6 (A2): if the prompt budget trimmed high-value evidence, the report
        # says so instead of implying the model saw everything.
        selection = self.metadata.get("evidence_selection") or {}
        if isinstance(selection, dict) and selection.get("coverage_gap_note"):
            gaps = selection.get("coverage_gaps") or []
            lines.extend(
                [
                    f"> **Prompt coverage gap** — {_clip(selection['coverage_gap_note'], 240)} "
                    f"({len(gaps)} record(s) carrying unique numbers, sole-source "
                    "coverage or risk signals, e.g. "
                    + ", ".join(
                        str(item.get("evidence_id"))
                        for item in gaps[:5]
                        if isinstance(item, dict)
                    )
                    + ").",
                    "",
                ]
            )
        for section in self.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            lines.append(f"_{section.agent_name} · {section.output_type}_")
            lines.append("")
            lines.append(section.content)
            lines.append("")
            if section.structured_data:
                lines.append("**Key data:**")
                lines.append("")
                lines.extend(
                    f"- `{key}` = `{_clip(value, 200)}`"
                    for key, value in section.structured_data.items()
                )
                lines.append("")
        if self.evidence:
            compact = bool(self.metadata.get("compact_evidence"))
            lines.extend(["## Evidence", ""])
            bound = sum(
                1
                for item in self.evidence
                if item.source_id and (item.evidence or "").strip()
            )
            # v0.6.6 (A6): never imply full source coverage — state how much of
            # the evidence is actually bound to a retrieved snippet.
            lines.append(
                f"> {len(self.evidence)} evidence record(s) · {bound} bound to a "
                f"retrieved snippet · {len(self.evidence) - bound} unbound (agent "
                "statements without a retrieved snippet)."
            )
            lines.append("")
            if compact:
                lines.append(
                    "> Compact view — each claim with the matching snippet and source. "
                    "Full snippets and provenance live in the run's `evidence.json`."
                )
                lines.append("")
            for item in self.evidence:
                ref = f" `{item.evidence_id}`" if item.evidence_id else ""
                nature = f" _[{item.claim_type}]_" if item.claim_type else ""
                if compact:
                    status = getattr(item, "review_status", "") or "not_checked"
                    lines.append(
                        f"- {_clip(item.claim, 240)} — {_clip(item.evidence, 300)} "
                        f"(`{item.source_id or 'unbound'}`){ref}{nature} _[{status}]_"
                    )
                else:
                    lines.append(
                        f"- {item.claim} — {item.evidence} (`{item.source_id}`){ref}{nature}"
                    )
            lines.append("")
        if self.source_records:
            lines.extend(["## Sources", ""])
            mock_count = sum(
                1 for source in self.source_records if source.source_type == "offline_mock"
            )
            for index, source in enumerate(self.source_records, start=1):
                title = source.title or source.id
                if source.source_type == "offline_mock":
                    # v0.6.6 (A9): a stub must never read as a live web page.
                    lines.append(
                        f"{index}. {title} — **offline_mock** (deterministic stub, "
                        "NOT a live web source)"
                    )
                    continue
                rendered = f"{index}. {title} — {source.source_type}"
                if source.url:
                    rendered += f", {source.url}"
                status = getattr(source, "access_status", "") or ""
                # v0.6.6 (A10): an observed fetch failure is stated as such; it is
                # never presented as "the page has no such content".
                if status and status.lower() not in {"ok", "success", "200"}:
                    note = getattr(source, "access_note", "") or ""
                    rendered += (
                        f" — **could not be re-checked** ({status}"
                        f"{'; ' + note if note else ''}); its content was never confirmed"
                    )
                lines.append(rendered)
            lines.append("")
            if all(source.source_type == "offline_mock" for source in self.source_records):
                lines.append("> Data source: offline_mock (deterministic stubs, no live web).")
                lines.append("")
            elif mock_count:
                lines.append(
                    f"> Mixed provenance: {len(self.source_records) - mock_count} web "
                    f"source(s) and {mock_count} offline_mock stub(s). Entries marked "
                    "**offline_mock** are not live web pages."
                )
                lines.append("")
        elif self.sources:
            lines.extend(["## Sources", ""])
            lines.extend(f"- {source}" for source in self.sources)
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(
            f"_Contributing agents: {', '.join(self.contributing_agents) or '—'}_"
        )
        if self.metadata.get("source_type") == "offline_mock":
            lines.append("_All content generated in offline mock mode (deterministic stubs)._")
        return "\n".join(lines)


class ArtifactAssembler:
    def assemble(
        self,
        task: str,
        artifacts: list[AgentArtifact],
        agent_order: list[str],
        **meta: object,
    ) -> FinalArtifact:
        order = {agent_id: index for index, agent_id in enumerate(agent_order)}
        ordered = sorted(
            artifacts, key=lambda artifact: order.get(artifact.agent_id, len(order))
        )
        role_by_id: dict[str, str] = {}
        for artifact in ordered:
            role_by_id[artifact.agent_id] = str(
                artifact.metadata.get("role_name", artifact.agent_id)
            )
        sections = [
            FinalSection(
                title=artifact.title or artifact.output_type.value.replace("_", " ").title(),
                agent_id=artifact.agent_id,
                agent_name=role_by_id[artifact.agent_id],
                output_type=artifact.output_type.value,
                content=artifact.content,
                structured_data=dict(artifact.structured_data),
            )
            for artifact in ordered
        ]
        type_names = sorted({artifact.output_type.value for artifact in artifacts})
        summary = (
            f"This deliverable was assembled from {len(artifacts)} agent artifacts "
            f"({', '.join(type_names)}) produced for the task: '{task}'. "
            f"Sections follow the team's execution order."
        )
        sources: list[str] = []
        for artifact in ordered:
            for source in artifact.sources:
                if source not in sources:
                    sources.append(source)
        source_records: list[Source] = []
        seen_ids: set[str] = set()
        evidence: list[Evidence] = []
        for artifact in ordered:
            for record in artifact.source_records:
                if record.id not in seen_ids:
                    seen_ids.add(record.id)
                    source_records.append(record)
            evidence.extend(artifact.evidence)
        return FinalArtifact(
            title=f"Final Deliverable — {task}",
            summary=summary,
            sections=sections,
            sources=sources,
            source_records=source_records,
            evidence=evidence,
            contributing_agents=[artifact.agent_id for artifact in ordered],
            metadata=meta,
        )
