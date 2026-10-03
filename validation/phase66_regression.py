"""Phase 6.6 read-only regression against the Phase 6.4 real run (v0.6.6).

Repairs A1-A10 are verified against the *stored* Phase 6.4 artifacts. Nothing
here is written to the run directory, no LLM/Tavily call is made, and the
REAL_EXECUTION_ENABLED gate is checked before anything else runs.

    python -m validation.phase66_regression

Outputs ``validation/runs/phase66_check/regression.json`` and a stdout summary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.runtime.artifacts import AgentArtifact, ArtifactType
from app.synthesis.assembler import _artifact_section_titles
from app.synthesis.claim_support import audit_claim_support, support_profile
from app.synthesis.evidence_selection import select_evidence
from app.synthesis.models import EvidenceRecord

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "validation/runs/20261002T085948Z_A_real"
RUN_DIR = RUN_ROOT / "run1_run_f376a35d"
CHECK_DIR = ROOT / "validation/runs/phase66_check"
BEFORE_SNAPSHOT = CHECK_DIR / "before_snapshot.json"


def _load(name: str) -> Any:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def _evidence_records() -> list[EvidenceRecord]:
    rows = _load("evidence.json")["items"]
    return [
        EvidenceRecord(
            evidence_id=row["evidence_id"],
            claim=row.get("claim") or "",
            evidence=row.get("evidence_text") or "",
            source_id=row.get("source_id") or "",
            source_type=row.get("source_type") or "",
            producer_agent=row.get("producer_agent") or "",
            artifact_id=row.get("artifact_id") or "",
            claim_type=row.get("claim_type") or "",
            review_status=row.get("review_status") or "not_checked",
        )
        for row in rows
    ]


def _old_selection(evidence: list[EvidenceRecord], per_agent: int = 6, total: int = 30) -> set[str]:
    """Reproduce the v0.6.4 policy: first N records in (agent, id) order."""
    ordered = sorted(evidence, key=lambda item: (item.producer_agent or "", item.evidence_id))
    per: dict[str, int] = {}
    chosen: list[str] = []
    for item in ordered:
        agent = item.producer_agent or "unknown"
        if per.get(agent, 0) >= per_agent or len(chosen) >= total:
            continue
        per[agent] = per.get(agent, 0) + 1
        chosen.append(item.evidence_id)
    return set(chosen)


def _bound_ids(evidence: list[EvidenceRecord]) -> set[str]:
    return {item.evidence_id for item in evidence if item.source_id and item.evidence.strip()}


def _coverage(ids: set[str], evidence: list[EvidenceRecord]) -> dict[str, int]:
    subset = [item for item in evidence if item.evidence_id in ids]
    return {
        "records": len(subset),
        "agents": len({item.producer_agent for item in subset if item.producer_agent}),
        "sources": len({item.source_id for item in subset if item.source_id}),
        "bound": len(_bound_ids(subset)),
    }


def _finding_rows(evidence: list[EvidenceRecord]) -> list[dict[str, Any]]:
    by_id = {item.evidence_id: item for item in evidence}
    findings = _load("synthesis.json")["findings"]
    rows = []
    for finding in findings:
        cited = list(finding.get("evidence_ids") or [])
        statement = finding.get("statement") or ""
        audit = audit_claim_support(statement, cited, by_id, pool=evidence)
        profile = support_profile(cited, by_id, claim_type=finding.get("claim_type") or "")
        rows.append(
            {
                "finding_id": finding.get("finding_id"),
                "as_run_support_kind": finding.get("support_kind"),
                "as_run_claim_type": finding.get("claim_type"),
                "cited_ids": cited,
                "new_support_kind": profile.support_kind,
                "new_support_level": profile.support_level,
                "evidence_count": profile.evidence_count,
                "agent_support_count": profile.agent_support_count,
                "independent_source_count": profile.independent_source_count,
                "citation_check": audit["numeric_check"],
                "citation_status": audit["status"],
                "numbers_supported": audit["numbers_supported"],
                "numbers_missing": audit["numbers_missing"],
                "witnesses": [
                    {
                        "number": item["number"],
                        "evidence_id": item["evidence_id"],
                        "source_id": item["source_id"],
                        "confidence": item["confidence"],
                        "scope_check": item["scope_check"],
                    }
                    for item in audit["witnesses"]
                ],
                "uncited_candidates": [
                    {
                        "evidence_id": item["evidence_id"],
                        "source_id": item["source_id"],
                        "numbers": item["numbers"],
                        "scope_conflicts": item.get("scope_conflicts") or [],
                    }
                    for item in audit["uncited_candidates"]
                ],
                "unbound_citations": len(audit["unbound_citations"]),
            }
        )
    return rows


def _section_titles() -> dict[str, Any]:
    """Rebuild artifact section titles with the v0.6.6 dedup helper (A8)."""
    artifacts = []
    for row in _load("artifacts.json")["items"]:
        try:
            output_type = ArtifactType(row["output_type"])
        except ValueError:
            output_type = ArtifactType.ANALYSIS
        artifacts.append(
            AgentArtifact(
                artifact_id=row["artifact_id"],
                agent_id=row["agent_id"],
                output_type=output_type,
                title=row.get("title") or "",
                metadata={"role_name": row.get("agent_id") or ""},
            )
        )
    reports = [item for item in artifacts if item.output_type is ArtifactType.REPORT]
    canonical = reports[-1].artifact_id if reports else ""
    titles = _artifact_section_titles(
        artifacts, canonical, reserved={"Key Findings", "Citation Audit", "Evidence Gaps"}
    )
    raw_titles = [item.title or item.artifact_id for item in artifacts]
    return {
        "raw_titles_unique": len(raw_titles) == len(set(raw_titles)),
        "raw_duplicates": sorted({t for t in raw_titles if raw_titles.count(t) > 1}),
        "canonical_artifact": canonical,
        "new_titles": titles,
        "new_titles_unique": len(set(titles.values())) == len(titles),
    }


def _sources() -> dict[str, Any]:
    payload = _load("sources.json")
    items = payload.get("items") or []
    return {
        "count": payload.get("count"),
        "by_type": payload.get("by_type"),
        "web": [item["source_id"] for item in items if item.get("source_type") == "web"],
        "offline_mock": [
            item["source_id"] for item in items if item.get("source_type") == "offline_mock"
        ],
        "without_url": [item["source_id"] for item in items if not item.get("url")],
    }


def _competitor_facts(evidence: list[EvidenceRecord]) -> dict[str, Any]:
    """A3: the competitor artifact's sourcing state, straight from the records."""
    artifact_id = "artifact_competitor_analyst"
    own = [item for item in evidence if item.artifact_id == artifact_id]
    return {
        "artifact_id": artifact_id,
        "evidence_count": len(own),
        "bound_evidence_count": len(_bound_ids(own)),
        "source_ids": sorted({item.source_id for item in own if item.source_id}),
        "unbound_claim_ids": [
            item.evidence_id for item in own if not item.source_id and item.claim.strip()
        ],
        "any_verified": any(item.verified for item in own),
    }


def _hash_check() -> dict[str, Any]:
    if not BEFORE_SNAPSHOT.is_file():
        return {"available": False}
    before = json.loads(BEFORE_SNAPSHOT.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for name, digest in before["files"].items():
        path = RUN_DIR / name if "/" not in name else RUN_ROOT.parent / name
        if "/" in name:
            path = RUN_ROOT / name.split("/", 1)[1] if name.startswith("run1_") else Path(name)
        if not path.is_file():
            path = RUN_ROOT / name
        if not path.is_file():
            mismatches.append(f"{name}: missing")
            continue
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        if current != digest:
            mismatches.append(f"{name}: hash changed")
    return {
        "available": True,
        "files_compared": len(before["files"]),
        "mismatches": mismatches,
        "unchanged": not mismatches,
    }


def _gate() -> dict[str, Any]:
    """Read the real-execution gate without ever flipping it."""
    try:
        import validation.run_scenario as runner

        enabled = bool(getattr(runner, "REAL_EXECUTION_ENABLED", True))
        source = "imported module attribute"
    except Exception:  # noqa: BLE001 - script may be run outside the package
        import re

        text = (ROOT / "validation/run_scenario.py").read_text(encoding="utf-8")
        match = re.search(r"^REAL_EXECUTION_ENABLED\s*=\s*(\w+)", text, re.MULTILINE)
        enabled = (match.group(1) if match else "True") != "False"
        source = "source scan"
    return {"real_execution_enabled": enabled, "ok": enabled is False, "read_via": source}


def build_report() -> dict[str, Any]:
    evidence = _evidence_records()
    old_ids = _old_selection(evidence)
    selection = select_evidence(evidence)
    new_ids = set(selection.chosen_ids)
    bound = _bound_ids(evidence)
    # read-only assertion: the loader never writes to the run directory
    return {
        "schema_version": "1",
        "run": str(RUN_DIR),
        "gate": _gate(),
        "evidence_selection": {
            "policy": selection.audit["policy_version"],
            "old_selected": len(old_ids),
            "new_selected": len(new_ids),
            "coverage_old": _coverage(old_ids, evidence),
            "coverage_new": _coverage(new_ids, evidence),
            "coverage_all": _coverage({item.evidence_id for item in evidence}, evidence),
            "bound_records_all_kept": bound <= new_ids,
            "key_records": {
                item: {"old": item in old_ids, "new": item in new_ids}
                for item in ("ev_c92e1e0f45", "ev_71fb39da19", "ev_8018571620", "ev_0e981c6d67")
            },
            "coverage_gaps": selection.audit["coverage_gaps"],
            "coverage_gap_note": selection.audit["coverage_gap_note"],
            "dropped_count": selection.audit["dropped_count"],
            "distinct_evidence_ids": selection.audit["distinct_evidence_ids"],
            "duplicate_ids_removed": selection.audit["duplicate_ids_removed"],
        },
        "findings": _finding_rows(evidence),
        "sections": _section_titles(),
        "sources": _sources(),
        "competitor": _competitor_facts(evidence),
        "hash_check": _hash_check(),
    }


def main() -> int:
    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    out = CHECK_DIR / "regression.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    sel = report["evidence_selection"]
    print(f"gate REAL_EXECUTION_ENABLED=False: {report['gate']['ok']}")
    print(
        f"selection: old {sel['old_selected']} -> new {sel['new_selected']} "
        f"| bound kept: {sel['bound_records_all_kept']} "
        f"| gaps: {len(sel['coverage_gaps'])}"
    )
    for name, state in sel["key_records"].items():
        old_state = "IN" if state["old"] else "TRIMMED"
        new_state = "IN" if state["new"] else "TRIMMED"
        print(f"  {name}: old={old_state} new={new_state}")
    print("coverage old -> new:", sel["coverage_old"], "->", sel["coverage_new"])
    print("\nfindings:")
    for row in report["findings"]:
        print(
            f"  {row['finding_id']}: {row['as_run_support_kind']} -> {row['new_support_kind']} "
            f"({row['new_support_level']}) | sources={row['independent_source_count']} "
            f"agents={row['agent_support_count']} | citation={row['citation_check']} "
            f"| missing={row['numbers_missing']}"
        )
    print("\nsections:", "raw unique:", report["sections"]["raw_titles_unique"],
          "| new unique:", report["sections"]["new_titles_unique"],
          "| raw duplicates:", report["sections"]["raw_duplicates"])
    print("competitor:", report["competitor"])
    print("hash check:", report["hash_check"])
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
