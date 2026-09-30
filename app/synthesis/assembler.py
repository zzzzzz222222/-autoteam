"""Final report assembly from a synthesis ReportBundle (v0.6.0).

Builds a ``FinalArtifact`` whose sections follow the v0.6 report outline
(Executive Summary → Key Findings → Insights → Contradictions → Trade-offs →
Recommendations → Evidence → Sources) while keeping every provenance link
intact. Empty sections are omitted — never rendered as "None".
"""

from __future__ import annotations

from app.runtime.artifacts import AgentArtifact, Evidence, Source, now_iso
from app.runtime.assembler import FinalArtifact, FinalSection
from app.synthesis.models import ReportBundle


def _flat(text: str) -> str:
    """Collapse newlines so evidence snippets cannot inject markdown headers."""
    return " ".join((text or "").split())


def _finding_lines(bundle: ReportBundle) -> list[str]:
    lines: list[str] = []
    findings = list(bundle.synthesis.key_findings)
    seen = {item.finding_id for item in findings}
    for extra in bundle.synthesis.supported_findings + bundle.synthesis.single_source_findings:
        if extra.finding_id not in seen:
            findings.append(extra)
            seen.add(extra.finding_id)
    for item in findings:
        support = ", ".join(item.evidence_ids) or "—"
        agents = ", ".join(item.supporting_agents) or "—"
        lines.append(
            f"- **{item.statement}**  \n  _support: {item.support_kind} · "
            f"evidence: {support} · agents: {agents}_"
        )
    return lines


def _insight_lines(bundle: ReportBundle) -> list[str]:
    lines: list[str] = []
    for item in bundle.synthesis.cross_agent_insights:
        evidence = ", ".join(item.supporting_evidence_ids) or "—"
        agents = ", ".join(item.producer_agents) or "—"
        uncertainty = f" · uncertainty: {item.uncertainty}" if item.uncertainty else ""
        lines.append(
            f"- **{item.statement}**  \n  _evidence: {evidence} · agents: {agents}{uncertainty}_"
        )
    return lines


def _contradiction_lines(bundle: ReportBundle) -> list[str]:
    lines: list[str] = []
    for item in bundle.synthesis.contradictions:
        status = item.status or "unresolved"
        resolution = item.resolution or (
            "Available evidence is insufficient to resolve the discrepancy."
        )
        lines.append(
            f"- **[{status}]** {item.claim_a} ↔ {item.claim_b}  \n"
            f"  _evidence: {', '.join(item.evidence_ids) or '—'} · "
            f"sources: {', '.join(item.source_ids) or '—'} · "
            f"agents: {', '.join(item.agents) or '—'}_  \n"
            f"  {resolution}"
        )
    for item in bundle.synthesis.uncertainties:
        evidence = ", ".join(item.evidence_ids) or "—"
        note = f" — {item.note}" if item.note else ""
        lines.append(
            f"- **({item.kind})** {item.statement}  \n  _evidence: {evidence}{note}_"
        )
    return lines


def _tradeoff_lines(bundle: ReportBundle) -> list[str]:
    lines: list[str] = []
    for item in bundle.synthesis.tradeoffs:
        lines.append(f"- **{item.dimension}**")
        if item.option_a or item.gains_a or item.costs_a:
            gains = "; ".join(item.gains_a) or "—"
            costs = "; ".join(item.costs_a) or "—"
            lines.append(f"  - Option A — {item.option_a or 'A'}: gains: {gains}; costs: {costs}")
        if item.option_b or item.gains_b or item.costs_b:
            gains = "; ".join(item.gains_b) or "—"
            costs = "; ".join(item.costs_b) or "—"
            lines.append(f"  - Option B — {item.option_b or 'B'}: gains: {gains}; costs: {costs}")
        evidence = ", ".join(item.evidence_ids) or "—"
        implications = "; ".join(item.implications) or "—"
        lines.append(f"  - _evidence: {evidence} · implications: {implications}_")
    return lines


def _recommendation_lines(bundle: ReportBundle) -> list[str]:
    supported: list[str] = []
    potential: list[str] = []
    unsupported: list[str] = []
    for item in bundle.synthesis.recommendations:
        chain = []
        if item.supporting_insight_ids:
            chain.append("insights: " + ", ".join(item.supporting_insight_ids))
        if item.supporting_tradeoff_ids:
            chain.append("trade-offs: " + ", ".join(item.supporting_tradeoff_ids))
        if item.supporting_evidence_ids:
            chain.append("evidence: " + ", ".join(item.supporting_evidence_ids))
        limitations = "; ".join(item.limitations) or "—"
        rendered = (
            f"- **{item.statement}**  \n"
            f"  _supported by: {' · '.join(chain) or 'no direct evidence'} · "
            f"limitations: {limitations}_"
        )
        if item.status == "supported":
            supported.append(rendered)
        elif item.status == "potential":
            potential.append(rendered)
        else:
            unsupported.append(rendered)
    lines = supported
    if potential:
        lines.append("")
        lines.append("*Potential considerations (not fully evidenced):*")
        lines.extend(potential)
    if unsupported:
        lines.append("")
        lines.append("*Unsupported ideas (not recommendations):*")
        lines.extend(unsupported)
    return lines


def assemble_from_bundle(
    task: str,
    artifacts: list[AgentArtifact],
    bundle: ReportBundle,
    agent_order: list[str],
    **meta: object,
) -> FinalArtifact:
    """Build the v0.6 final report from a synthesis bundle."""
    order = {agent_id: index for index, agent_id in enumerate(agent_order)}
    ordered = sorted(artifacts, key=lambda item: order.get(item.agent_id, len(order)))
    role_by_id = {
        item.agent_id: str(item.metadata.get("role_name", item.agent_id))
        for item in ordered
    }

    sections: list[FinalSection] = []
    summary = bundle.synthesis.summary or (
        f"Cross-agent synthesis over {len(artifacts)} artifacts "
        f"and {len(bundle.evidence)} evidence records."
    )
    # Executive Summary is rendered from FinalArtifact.summary by to_markdown();
    # do not add a duplicate section here.

    finding_lines = _finding_lines(bundle)
    if finding_lines:
        sections.append(
            FinalSection(
                title="Key Findings",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="findings",
                content="\n".join(finding_lines),
            )
        )

    insight_lines = _insight_lines(bundle)
    if insight_lines:
        sections.append(
            FinalSection(
                title="Cross-Agent Insights",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="insights",
                content="\n".join(insight_lines),
            )
        )

    contradiction_lines = _contradiction_lines(bundle)
    if contradiction_lines:
        sections.append(
            FinalSection(
                title="Contradictions & Uncertainties",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="contradictions",
                content="\n".join(contradiction_lines),
            )
        )

    tradeoff_lines = _tradeoff_lines(bundle)
    if tradeoff_lines:
        sections.append(
            FinalSection(
                title="Trade-offs",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="tradeoffs",
                content="\n".join(tradeoff_lines),
            )
        )

    recommendation_lines = _recommendation_lines(bundle)
    if recommendation_lines:
        sections.append(
            FinalSection(
                title="Recommendations",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="recommendations",
                content="\n".join(recommendation_lines),
            )
        )

    # Keep source material sections after the synthesis sections so the
    # report reads as analysis first, raw agent outputs second.
    for artifact in ordered:
        sections.append(
            FinalSection(
                title=artifact.title
                or artifact.output_type.value.replace("_", " ").title(),
                agent_id=artifact.agent_id,
                agent_name=role_by_id.get(artifact.agent_id, artifact.agent_id),
                output_type=artifact.output_type.value,
                content=artifact.content,
                structured_data=dict(artifact.structured_data),
            )
        )

    source_records: list[Source] = [
        Source(
            id=record.source_id,
            title=record.title,
            url=record.url,
            source_type=record.source_type,
            retrieved_at=record.retrieved_at,
        )
        for record in bundle.sources
    ]
    evidence_items: list[Evidence] = [
        Evidence(
            claim=_flat(record.claim),
            evidence=_flat(record.evidence),
            source_id=record.source_id,
            evidence_id=record.evidence_id,
            producer_agent=record.producer_agent,
            artifact_id=record.artifact_id,
        )
        for record in bundle.evidence
    ]

    metadata: dict[str, object] = dict(meta)
    metadata.setdefault("synthesis_status", bundle.status)
    if bundle.degradation_reason:
        metadata["synthesis_degradation_reason"] = bundle.degradation_reason
    metadata.setdefault("source_type", meta.get("source_type", "unknown"))

    return FinalArtifact(
        title=f"Final Deliverable — {task}",
        summary=summary,
        sections=sections,
        sources=[record.title or record.source_id for record in bundle.sources],
        source_records=source_records,
        evidence=evidence_items,
        contributing_agents=[item.agent_id for item in ordered],
        metadata={**metadata, "generated_at": now_iso()},
    )
