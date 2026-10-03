"""Final report assembly from a synthesis ReportBundle (v0.6.0).

Builds a ``FinalArtifact`` whose sections follow the v0.6 report outline
(Executive Summary → Key Findings → Insights → Contradictions → Trade-offs →
Recommendations → Evidence → Sources) while keeping every provenance link
intact. Empty sections are omitted — never rendered as "None".
"""

from __future__ import annotations

import re

from app.runtime.artifacts import AgentArtifact, ArtifactType, Evidence, Source, now_iso
from app.runtime.assembler import FinalArtifact, FinalSection
from app.synthesis.models import ReportBundle

_STATEMENT_NOISE = re.compile(r"[\s\*\-#_`「」【】（）()：:，,。.、;；!！?？\"'“”‘’]+")


def _normalize_statement(text: str) -> str:
    return _STATEMENT_NOISE.sub("", (text or "").lower())


def _flat(text: str) -> str:
    """Collapse newlines so evidence snippets cannot inject markdown headers."""
    return " ".join((text or "").split())


def _nature(claim_type: str) -> str:
    """Render a data-nature tag only when the system actually has one."""
    return f" · nature: {claim_type}" if claim_type else ""


def _finding_lines(bundle: ReportBundle) -> list[str]:
    lines: list[str] = []
    # Defensive guard: never render the same conclusion twice, even if a caller
    # supplies overlapping lists (the synthesis layer also merges them).
    findings = []
    seen_ids: set[str] = set()
    seen_statements: set[str] = set()
    for item in (
        bundle.synthesis.key_findings
        + bundle.synthesis.supported_findings
        + bundle.synthesis.single_source_findings
    ):
        normalized = _normalize_statement(item.statement)
        if item.finding_id in seen_ids or (normalized and normalized in seen_statements):
            continue
        findings.append(item)
        seen_ids.add(item.finding_id)
        seen_statements.add(normalized)
    for item in findings:
        support = ", ".join(item.evidence_ids) or "—"
        agents = ", ".join(item.supporting_agents) or "—"
        derivation = f"  \n  _derivation: {_flat(item.derivation)}_" if item.derivation else ""
        # v0.6.6 (A4-A7): state *how* the claim is supported. Independent sources
        # and agreeing agents are printed separately so "several agents said it"
        # can never be read as "several sources confirmed it".
        level = (
            f"level: {item.support_level} · independent sources: "
            f"{item.independent_source_count} · agents: {item.agent_support_count} · "
            f"evidence: {item.evidence_count}"
        )
        citation = f" · citation check: {item.review_status}" if item.review_status else ""
        lines.append(
            f"- **{item.statement}**  \n  _support: {item.support_kind} · "
            f"{level}{citation}_  \n  _evidence: {support} · agents: {agents}"
            f"{_nature(item.claim_type)}_{derivation}"
        )
        if item.unsupported_parts:
            lines.append(
                "  - _not found in the cited snippets: "
                + ", ".join(item.unsupported_parts)
                + "_ (kept as an open item — nothing was deleted)"
            )
    return lines


def _citation_audit_lines(bundle: ReportBundle) -> list[str]:
    """Per-claim citation audit (v0.6.6, A1).

    Fixed code — not an LLM judge. For every finding it lists which asserted
    numbers the *cited* snippets actually contain, which they do not, and
    (informationally, never as a binding) any uncited record that carries them.
    """
    findings = bundle.synthesis.key_findings
    if not findings:
        return []
    lines: list[str] = []
    for item in findings:
        audit = item.support_audit or {}
        status = audit.get("status") or "no_numeric_claim"
        if status == "no_numeric_claim" and not item.evidence_ids:
            lines.append(f"- **{item.finding_id}** — no citation and no numeric claim.")
            continue
        total = len(audit.get("assertions") or [])
        found = len(audit.get("numbers_supported") or [])
        lines.append(
            f"- **{item.finding_id}** check **{audit.get('numeric_check', 'n/a')}** "
            f"({found}/{total} asserted number(s) found in the cited snippets) · "
            f"review: {item.review_status} · kind: {item.support_kind} · "
            f"level: {item.support_level}"
        )
        for witness in (audit.get("witnesses") or [])[:6]:
            # v0.6.9 (F13): show the witness source *type* so a mock stub can
            # never be read as a real web page (and vice versa).
            witness_type = str(witness.get("source_type") or "").strip() or "unknown"
            lines.append(
                f"  - {witness.get('number')} ← `{witness.get('evidence_id')}`"
                f" (`{witness.get('source_id') or 'unbound'}` · {witness_type}) · "
                f"{witness.get('match_reason')} · "
                f"{witness.get('scope_note') or 'scope confirmed'} · "
                f"confidence: {witness.get('confidence')}"
            )
        missing = audit.get("numbers_missing") or []
        if missing:
            lines.append("  - not found in any cited snippet: " + ", ".join(missing))
        for candidate in (audit.get("uncited_candidates") or [])[:4]:
            caveat = ""
            if candidate.get("scope_conflicts"):
                caveat = " (scope conflict: " + "; ".join(candidate["scope_conflicts"]) + ")"
            elif candidate.get("scope_unflagged"):
                caveat = " (scope not stated in the snippet)"
            lines.append(
                f"  - reference only, **not cited**: `{candidate.get('evidence_id')}` "
                f"(`{candidate.get('source_id') or 'unbound'}`) carries "
                f"{', '.join(candidate.get('numbers') or [])}{caveat}"
            )
        for row in (audit.get("checks") or [])[:6]:
            if row.get("source_backed"):
                continue
            lines.append(
                f"  - `{row.get('evidence_id')}` (`{row.get('source_id') or 'unbound'}`) "
                f"check: {row.get('check_status')} — {row.get('match_reason')}"
            )
    return lines


def _source_gap_lines(bundle: ReportBundle) -> list[str]:
    """Structured evidence gaps (v0.6.6, A3) — never a fabricated source."""
    lines: list[str] = []
    for gap in bundle.source_gaps or []:
        title = gap.get("role_name") or gap.get("producer_agent") or gap.get("artifact_id")
        lines.append(
            f"- **{title}** (`{gap.get('artifact_id')}`) · severity: {gap.get('severity')} · "
            f"intent: `{gap.get('declared_intent') or 'undeclared'}` · "
            f"source records: {gap.get('source_count')} · bound evidence: "
            f"{gap.get('bound_evidence_count')}/{gap.get('evidence_count')}"
        )
        for reason in gap.get("reasons") or []:
            lines.append(f"  - {reason}")
        if gap.get("unverified_claims"):
            lines.append(
                "  - kept but downgraded to `unverified_claim`: "
                + ", ".join(gap["unverified_claims"][:8])
            )
    return lines


def _insight_lines(bundle: ReportBundle) -> list[str]:
    lines: list[str] = []
    for item in bundle.synthesis.cross_agent_insights:
        evidence = ", ".join(item.supporting_evidence_ids) or "—"
        agents = ", ".join(item.contributing_agents or item.producer_agents) or "—"
        uncertainty = f" · uncertainty: {item.uncertainty}" if item.uncertainty else ""
        derivation = f"  \n  _derivation: {_flat(item.derivation)}_" if item.derivation else ""
        lines.append(
            f"- **{item.statement}**  \n  _evidence: {evidence} · agents: {agents}"
            f"{_nature(item.claim_type)}{uncertainty}_{derivation}"
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
            f"limitations: {limitations}{_nature(item.claim_type)}_"
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


def _source_conflict_lines(bundle: ReportBundle) -> list[str]:
    """Audited source-identity conflicts (v0.6.9, F13).

    A conflict means one identity basis carried *different* url/type claims: the
    records were split instead of one silently overwriting the other. The report
    states what was kept, what was split and why.
    """
    lines: list[str] = []
    for item in bundle.source_conflicts or []:
        kept = item.get("kept") or {}
        split = item.get("split") or {}
        lines.append(
            f"- **conflict** — `{item.get('kept_source_id')}` kept "
            f"({kept.get('source_type')}, {kept.get('url') or 'no url'}; agents: "
            f"{', '.join(kept.get('artifact_ids') or []) or '—'}) vs "
            f"`{item.get('split_source_id')}` split "
            f"({split.get('source_type')}, {split.get('url') or 'no url'}; agents: "
            f"{', '.join(split.get('artifact_ids') or []) or '—'})"
        )
        lines.append(f"  - reason: {item.get('reason')}")
    return lines


def _artifact_section_titles(
    ordered: list[AgentArtifact], canonical_report_id: str, reserved: set[str] | None = None
) -> dict[str, str]:
    """Collision-free section titles for artifact sections (v0.6.6, A8).

    The canonical final deliverable keeps its own title. Any other section whose
    title collides with a title already taken is disambiguated by its role in the
    pipeline — the content is always kept, only the heading changes.
    """
    titles: dict[str, str] = {}
    taken: set[str] = {_normalize_statement(item) for item in (reserved or set())}
    taken.discard("")

    def base_title(artifact: AgentArtifact) -> str:
        return artifact.title or artifact.output_type.value.replace("_", " ").title()

    def claim(preferred: str, fallback_prefix: str) -> str:
        candidate = preferred
        suffix = 2
        while _normalize_statement(candidate) in taken:
            candidate = f"{fallback_prefix} ({suffix})"
            suffix += 1
        taken.add(_normalize_statement(candidate))
        return candidate

    # 1) the canonical final deliverable reserves its title first — unless that
    #    title would clash with a synthesis section, in which case it is marked
    #    as the final deliverable instead of duplicating a heading (A8).
    for artifact in ordered:
        if artifact.artifact_id == canonical_report_id:
            base = base_title(artifact)
            titles[artifact.artifact_id] = claim(base, f"{base} (final deliverable)")

    # 2) every other artifact, in team order.
    for artifact in ordered:
        if artifact.artifact_id in titles:
            continue
        base = base_title(artifact)
        if artifact.output_type is ArtifactType.REPORT:
            preferred = f"Intermediate deliverable (not the final report) — {base}"
        elif _normalize_statement(base) in taken:
            preferred = f"{base} (upstream {artifact.output_type.value.replace('_', ' ')} draft)"
        else:
            preferred = base
        titles[artifact.artifact_id] = claim(preferred, base)
    return titles


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
    # D3: a statistical sentence is NOT an executive summary. When synthesis has
    # no model-written summary, ``derive_executive_summary`` has either composed
    # one from validated findings or marked it unavailable - surface that state
    # instead of dressing up an empty section.
    summary = (getattr(bundle.synthesis, "summary", "") or "").strip()
    summary_status = str(getattr(bundle.synthesis, "summary_status", "") or "")
    if not summary:
        reason = str(getattr(bundle.synthesis, "summary_reason", "") or "")
        summary = (
            "_Executive summary unavailable._ "
            + (reason or "synthesis produced no summary for this run.")
        )
    elif summary_status == "derived_from_findings":
        summary = (
            summary
            + "\n\n_(composed from validated synthesis findings; "
            "the model returned no summary)_"
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

    # v0.6.6 (A1): the report carries its own citation audit so a reader can see
    # exactly which asserted numbers the cited snippets contain.
    citation_lines = _citation_audit_lines(bundle)
    if citation_lines:
        sections.append(
            FinalSection(
                title="Citation Audit",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="citation_audit",
                content="\n".join(citation_lines),
            )
        )

    # v0.6.6 (A3): structured evidence gaps — what could not be sourced.
    gap_lines = _source_gap_lines(bundle)
    if gap_lines:
        sections.append(
            FinalSection(
                title="Evidence Gaps",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="evidence_gaps",
                content="\n".join(gap_lines),
            )
        )

    # v0.6.9 (F13): same identity with conflicting url/type is split, never
    # overwritten — say so explicitly instead of hiding the ambiguity.
    conflict_lines = _source_conflict_lines(bundle)
    if conflict_lines:
        sections.append(
            FinalSection(
                title="Source Conflicts",
                agent_id="synthesis",
                agent_name="Synthesis Pipeline",
                output_type="source_conflicts",
                content="\n".join(conflict_lines),
            )
        )

    # Keep source material sections after the synthesis sections so the
    # report reads as analysis first, raw agent outputs second.
    # Exactly one artifact is the canonical final report. Any other REPORT
    # artifact is clearly relabelled so nobody mistakes it for a second final.
    report_artifacts = [item for item in ordered if item.output_type is ArtifactType.REPORT]
    canonical_report_id = report_artifacts[-1].artifact_id if report_artifacts else ""
    # v0.6.6 (A8): the proposal writer and the report writer can end up with the
    # *same* title (Phase 6.4 produced two identical sections). Titles are now
    # made unique deterministically; no artifact's content is ever dropped.
    titles = _artifact_section_titles(
        ordered, canonical_report_id, reserved={section.title for section in sections}
    )
    for artifact in ordered:
        is_extra_report = (
            artifact.output_type is ArtifactType.REPORT
            and artifact.artifact_id != canonical_report_id
        )
        sections.append(
            FinalSection(
                title=titles[artifact.artifact_id],
                agent_id=artifact.agent_id,
                agent_name=role_by_id.get(artifact.agent_id, artifact.agent_id),
                output_type=(
                    "intermediate_report" if is_extra_report else artifact.output_type.value
                ),
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
            claim_type=record.claim_type,
            match_score=record.match_score,
            match_method=record.match_method,
            review_status=record.review_status,
        )
        for record in bundle.evidence
    ]

    metadata: dict[str, object] = dict(meta)
    metadata.setdefault("synthesis_status", bundle.status)
    metadata.setdefault("compact_evidence", True)
    metadata["canonical_report_artifact"] = canonical_report_id
    # v0.6.6: carry the code-owned audits into the final artifact metadata so the
    # report/run dump can show selection coverage, citation checks and gaps.
    if bundle.evidence_selection:
        metadata["evidence_selection"] = dict(bundle.evidence_selection)
    if bundle.claim_audit:
        metadata["claim_audit"] = list(bundle.claim_audit)
    if bundle.source_gaps:
        metadata["source_gaps"] = list(bundle.source_gaps)
    if bundle.fallback_used:
        metadata["fallback_used"] = True
        metadata["fallback_reason"] = bundle.fallback_reason
        metadata["synthesis_retry_count"] = bundle.retry_count
        metadata["synthesis_validation_errors"] = list(bundle.validation_errors)
        metadata["stage_audit"] = list(bundle.stage_audit)
        metadata["partial_stages_used"] = any(
            stage.get("ok") for stage in bundle.stage_audit
        )
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
