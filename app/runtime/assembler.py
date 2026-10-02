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
        lines.extend(["## Executive Summary", "", self.summary, ""])
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
                    f"- `{key}` = `{value}`" for key, value in section.structured_data.items()
                )
                lines.append("")
        if self.evidence:
            lines.extend(["## Evidence", ""])
            for item in self.evidence:
                ref = f" `{item.evidence_id}`" if item.evidence_id else ""
                nature = f" _[{item.claim_type}]_" if item.claim_type else ""
                lines.append(f"- {item.claim} — {item.evidence} (`{item.source_id}`){ref}{nature}")
            lines.append("")
        if self.source_records:
            lines.extend(["## Sources", ""])
            lines.extend(
                f"{index}. {source.title or source.id} "
                f"({source.source_type}{', ' + source.url if source.url else ''})"
                for index, source in enumerate(self.source_records, start=1)
            )
            lines.append("")
            if all(source.source_type == "offline_mock" for source in self.source_records):
                lines.append("> Data source: offline_mock (deterministic stubs, no live web).")
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
