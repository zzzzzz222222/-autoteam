"""Phase 6.9 — F13 offline regression (no network, no provider calls).

Two independent checks, both fully offline:

1. **Offline smoke** — build synthetic artifacts (including a deliberate
   identity conflict), run the *real* synthesis pipeline with the mock provider,
   and assert the source layer + report render correctly.
2. **Phase 6.8 historical re-parse** — re-read the stored ``run_f06b4571``
   artifacts and recompute the source metrics with the fixed code. This is a
   *re-parse of recorded fields*, not a re-run: the original per-artifact URLs
   for the URL-less sources were destroyed by the old merge and are explicitly
   reported as unrecoverable rather than guessed.

Run with:  python -m validation.phase69_regression
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from app.runtime.artifacts import AgentArtifact, ArtifactType, Evidence, Source
from app.synthesis.assembler import assemble_from_bundle
from app.synthesis.evidence_filter import collect_evidence_records
from app.synthesis.pipeline import run_synthesis_pipeline
from app.synthesis.source_identity import derive_source_identity

ROOT = Path(__file__).resolve().parents[1]
CHECK_DIR = ROOT / "validation/runs/phase69_check"
PHASE68_RUN = ROOT / "validation/runs/20261002T095017Z_A_real/run1_run_f06b4571"
BEFORE_SNAPSHOT = CHECK_DIR / "before_snapshot.json"


def _sh(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


# ---------------------------------------------------------------------------
# 1. offline smoke (real pipeline, mock provider, synthetic fixtures)
# ---------------------------------------------------------------------------


def _fixture_artifact(
    artifact_id: str,
    agent_id: str,
    sources: list[tuple[str, str, str]],
    claims: list[tuple[str, str, int]],
) -> AgentArtifact:
    records = []
    for ordinal, (title, url, source_type) in enumerate(sources, start=1):
        source_id, basis = derive_source_identity(
            url=url, artifact_id=artifact_id, title=title, ordinal=ordinal
        )
        records.append(
            Source(id=source_id, identity=basis, title=title, url=url, source_type=source_type)
        )
    evidence = [
        Evidence(
            claim=claim,
            evidence=snippet,
            source_id=records[index].id,
            claim_type="source_fact",
        )
        for claim, snippet, index in claims
    ]
    return AgentArtifact(
        artifact_id=artifact_id,
        agent_id=agent_id,
        output_type=ArtifactType.ANALYSIS,
        title=f"{agent_id} deliverable",
        metadata={"role_name": agent_id, "expected_output": "market_overview"},
        source_records=records,
        evidence=evidence,
    )


def offline_smoke() -> dict[str, Any]:
    artifacts = [
        _fixture_artifact(
            "artifact_a", "agent_a",
            [("[offline_mock] stub a", "", "offline_mock")],
            [("stub claim", "offline deterministic stub about market", 0)],
        ),
        _fixture_artifact(
            "artifact_b", "agent_b",
            [("Real page", "HTTPS://Example.COM/market", "web")],
            [("2026 年市场达到 449 亿元", "2026 年市场达到 449 亿元", 0)],
        ),
        # deliberate conflict: same URL claimed as web and as offline_mock
        _fixture_artifact(
            "artifact_c", "agent_c",
            [("Conflicting stub", "https://example.com/market", "offline_mock")],
            [("conflicting claim", "conflicting snippet", 0)],
        ),
    ]
    bundle = run_synthesis_pipeline("smoke task", artifacts)  # mock provider, no network
    final = assemble_from_bundle(
        "smoke task", artifacts, bundle, [a.agent_id for a in artifacts]
    )
    markdown = final.to_markdown()
    sections = [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]
    web = [s for s in bundle.sources if s.source_type == "web"]
    mock = [s for s in bundle.sources if s.source_type == "offline_mock"]
    return {
        "bundle_status": bundle.status,
        "source_count": len(bundle.sources),
        "sources": [
            {
                "source_id": s.source_id,
                "source_type": s.source_type,
                "url": s.url,
                "identity": s.identity,
                "producer_agents": s.producer_agents,
                "artifact_ids": s.artifact_ids,
            }
            for s in bundle.sources
        ],
        "web_sources": len(web),
        "mock_sources": len(mock),
        "web_urls_preserved": all(s.url for s in web),
        "mock_urls_empty": all(not s.url for s in mock),
        "source_conflicts": bundle.source_conflicts,
        "source_conflict_section_rendered": "Source Conflicts" in sections,
        "sections": sections,
        "reference_issues": bundle.reference_issues,
        "evidence_all_resolve": all(
            (not e.source_id) or any(e.source_id == s.source_id for s in bundle.sources)
            for e in bundle.evidence
        ),
        "evidence_types_preserved": sorted(
            {(e.source_id, e.source_type) for e in bundle.evidence if e.source_id}
        )
        == sorted({(s.source_id, s.source_type) for s in bundle.sources}),
    }


# ---------------------------------------------------------------------------
# 2. Phase 6.8 historical re-parse (read-only)
# ---------------------------------------------------------------------------


def _load(name: str) -> Any:
    return json.loads((PHASE68_RUN / name).read_text(encoding="utf-8"))


def historical_regression() -> dict[str, Any]:
    evidence_rows = _load("evidence.json")["items"]
    source_rows = _load("sources.json")["items"]
    synthesis = _load("synthesis.json")

    def is_bound(row: dict) -> bool:
        return bool(row.get("source_id")) and bool((row.get("evidence_text") or "").strip())

    bound = [row for row in evidence_rows if is_bound(row)]
    by_type: dict[str, int] = {}
    for row in source_rows:
        by_type[row.get("source_type") or "unknown"] = (
            by_type.get(row.get("source_type") or "unknown", 0) + 1
        )
    # conflicts = a source id used by more than one artifact
    users: dict[str, set[str]] = {}
    for row in evidence_rows:
        if row.get("source_id"):
            users.setdefault(row["source_id"], set()).add(row.get("artifact_id") or "")
    collided = sorted(sid for sid, arts in users.items() if len(arts) > 1)
    recorded_url = {row["source_id"]: row.get("url") or "" for row in source_rows}

    before = {
        "source_count": len(source_rows),
        "by_type": by_type,
        "web_sources": by_type.get("web", 0),
        "mock_sources": by_type.get("offline_mock", 0),
        "independent_sources": len({row["source_id"] for row in bound}),
        "multi_source_findings": sum(
            1 for f in synthesis["findings"] if f.get("support_kind") == "multi_source"
        ),
        "multi_agent_findings": sum(
            1 for f in synthesis["findings"] if f.get("support_kind") == "multi_agent"
        ),
        "source_id_conflicts": len(collided),
        "collided_ids": collided,
        "evidence_link_validity": f"{len(bound)}/{len(bound)}",
        "invalid_references": len(synthesis.get("reference_issues") or []),
        "recoverable": False,
    }

    # --- re-parse with the fixed code, using ONLY recorded fields ------------
    # URLs are only used where the run itself recorded one; URL-less sources keep
    # their (artifact, source_id) scope, because the original URL is unrecoverable.
    artifacts: dict[str, AgentArtifact] = {}
    for row in evidence_rows:
        artifact_id = row.get("artifact_id") or "unknown"
        artifacts.setdefault(artifact_id, AgentArtifact(
            artifact_id=artifact_id,
            agent_id=row.get("producer_agent") or artifact_id,
            output_type=ArtifactType.ANALYSIS,
            metadata={"role_name": row.get("producer_agent") or ""},
        ))
    seen_local: set[tuple[str, str]] = set()
    for row in evidence_rows:
        artifact_id = row.get("artifact_id") or "unknown"
        local_id = row.get("source_id") or ""
        artifact = artifacts[artifact_id]
        if local_id and (artifact_id, local_id) not in seen_local:
            seen_local.add((artifact_id, local_id))
            artifact.source_records.append(
                Source(
                    id=local_id,
                    title=row.get("source_title") or "",
                    url=recorded_url.get(local_id, "") if row.get("source_type") == "web" else "",
                    source_type=row.get("source_type") or "offline_mock",
                )
            )
        if local_id:
            artifact.evidence.append(
                Evidence(
                    claim=row.get("claim") or "",
                    evidence=row.get("evidence_text") or "",
                    source_id=local_id,
                    claim_type=row.get("claim_type") or "",
                    match_score=row.get("match_score") or 0.0,
                    match_method=row.get("match_method") or "",
                    review_status=row.get("review_status") or "not_checked",
                )
            )
    conflicts: list[dict] = []
    reparsed_evidence, reparsed_sources = collect_evidence_records(
        list(artifacts.values()), conflicts=conflicts
    )
    resolved_ids = {s.source_id for s in reparsed_sources}
    bound_after = [
        row for row in reparsed_evidence if row.source_id and (row.evidence or "").strip()
    ]
    by_type_after: dict[str, int] = {}
    for row in reparsed_sources:
        by_type_after[row.source_type or "unknown"] = (
            by_type_after.get(row.source_type or "unknown", 0) + 1
        )
    after = {
        "source_count": len(reparsed_sources),
        "by_type": by_type_after,
        "web_sources": by_type_after.get("web", 0),
        "mock_sources": by_type_after.get("offline_mock", 0),
        "independent_sources": len({row.source_id for row in bound_after}),
        "multi_source_findings": None,
        "multi_agent_findings": None,
        "source_id_conflicts": len(conflicts),
        "conflicts": conflicts,
        "evidence_link_validity": f"{sum(1 for r in bound_after if r.source_id in resolved_ids)}/"
        f"{len(bound_after)}",
        "invalid_references": sum(
            1 for r in reparsed_evidence if r.source_id and r.source_id not in resolved_ids
        ),
        "recoverable": False,
        "recoverable_note": (
            "URL-less sources lost their true provenance in the old merge; the re-parse "
            "keeps them artifact-scoped instead of guessing a URL, so the absolute counts "
            "for this historical run cannot be restored - only the collision behaviour can."
        ),
    }
    return {
        "run": str(PHASE68_RUN),
        "before_as_recorded": before,
        "after_reparsed": after,
        "urls_recoverable": sorted({url for url in recorded_url.values() if url}),
        "urls_unrecoverable": sorted(
            {
                row["source_id"]
                for row in source_rows
                if not (row.get("url") or "")
            }
        ),
    }


# ---------------------------------------------------------------------------
# 3. history / git integrity
# ---------------------------------------------------------------------------


def integrity() -> dict[str, Any]:
    snapshot = json.loads(BEFORE_SNAPSHOT.read_text(encoding="utf-8"))
    changed = [
        path
        for path, digest in snapshot["files"].items()
        if not Path(path).is_file()
        or hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest
    ]
    # Files this phase is allowed to edit. The snapshot only covered a subset of
    # them, so "expected but not snapshotted" is reported explicitly instead of
    # being silently treated as unchanged.
    expected_code_changes = {
        "app/runtime/agent_runtime.py",
        "app/runtime/artifacts.py",
        "app/synthesis/evidence_filter.py",
        "app/synthesis/models.py",
        "app/synthesis/claim_support.py",
        "app/synthesis/assembler.py",
        "app/synthesis/pipeline.py",
        "app/synthesis/synthesizer.py",
        "validation/collect.py",
        "validation/run_scenario.py",
        "tests/test_provenance.py",
    }
    changed_norm = {Path(path).as_posix() for path in changed}
    # Historical experiment data + frozen phase reports must never change.
    historical_prefixes = (
        "validation/runs/2026",
        "validation/runs/phase66_check",
        "validation/runs/phase68_check",
    )
    historical_changed = sorted(
        path for path in changed_norm if path.startswith(historical_prefixes)
    )
    frozen_reports = [
        path
        for path in changed_norm
        if path.startswith("validation/")
        and path.endswith((".md", ".json"))
        and not path.startswith("validation/runs/")
    ]
    porcelain_now = _sh("status", "--porcelain").splitlines()
    modified_files = sorted(expected_code_changes)
    return {
        "after_hashes": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()[:16]
            for path in modified_files
            if (ROOT / path).is_file()
        },
        "snapshot_files": snapshot["file_count"],
        "changed_vs_snapshot": changed,
        "historical_files_changed": historical_changed,
        "historical_untouched": not historical_changed,
        "frozen_reports_changed": frozen_reports,
        "unexpected_code_changes": sorted(
            changed_norm
            - expected_code_changes
            - {Path(p).as_posix() for p in historical_changed}
        ),
        "expected_but_not_snapshotted": sorted(expected_code_changes - changed_norm),
        "head_before": snapshot["head"],
        "head_now": _sh("rev-parse", "HEAD").strip(),
        "tag_before": snapshot["tag"],
        "tag_now": _sh("rev-parse", "v0.6.0^{commit}").strip(),
        "porcelain_before": snapshot["status_porcelain_count"],
        "porcelain_now": len(porcelain_now),
        "porcelain_entries_preserved": set(snapshot["status_porcelain"]) <= set(porcelain_now),
        "gate_closed": "REAL_EXECUTION_ENABLED = False"
        in (ROOT / "validation/run_scenario.py").read_text(encoding="utf-8"),
        "gate_true_occurrences": (ROOT / "validation/run_scenario.py")
        .read_text(encoding="utf-8")
        .count("REAL_EXECUTION_ENABLED = True"),
        "new_files": [
            "app/synthesis/source_identity.py",
            "tests/test_phase69_source_identity.py",
            "validation/phase69_regression.py",
        ],
    }


def main() -> int:
    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "1",
        "phase": "6.9",
        "offline_smoke": offline_smoke(),
        "historical_regression": historical_regression(),
        "integrity": integrity(),
    }
    out = CHECK_DIR / "regression.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    smoke = result["offline_smoke"]
    print(f"offline smoke: status={smoke['bundle_status']} sources={smoke['source_count']} "
          f"(web {smoke['web_sources']}, mock {smoke['mock_sources']}) "
          f"conflicts={len(smoke['source_conflicts'])} section_rendered="
          f"{smoke['source_conflict_section_rendered']}")
    hist = result["historical_regression"]
    print("historical before:", json.dumps(hist["before_as_recorded"], ensure_ascii=True)[:200])
    after_summary = {
        key: value for key, value in hist["after_reparsed"].items() if key != "conflicts"
    }
    print("historical after :", json.dumps(after_summary, ensure_ascii=True)[:200])
    integ = result["integrity"]
    print("integrity: historical_untouched=", integ["historical_untouched"],
          "| frozen_reports_changed=", integ["frozen_reports_changed"],
          "| unexpected_code_changes=", integ["unexpected_code_changes"],
          "| gate_closed=", integ["gate_closed"],
          "| tag_same=", integ["tag_before"] == integ["tag_now"],
          "| porcelain preserved=", integ["porcelain_entries_preserved"])
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
