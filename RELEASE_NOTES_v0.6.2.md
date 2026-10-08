# AutoTeam v0.6.2 Release Notes

> Released: 2026-10-08 · Base: v0.6.1 (`f3f7330`)
> Theme: **Release closure for the Honesty & Reliability Hardening** — finish the
> Web UI fixes, persist the audit trail end-to-end, and ship the release.

---

## Summary

v0.6.2 closes the remaining items on top of v0.6.1. It does **not** change the
agent execution model or add new agent capabilities. The work is in three areas:

1. **Audit trail that survives round-trips** — finding-level support audits are
   now projected inline and restored on offline reconstruction, so
   `citation_verified` no longer silently drops to zero when a run is re-read
   from disk.
2. **Web UI finish** — the version label reads `v0.6.2`, and the runtime
   dependency on Google Fonts is removed (the UI falls back to system fonts).
3. **Release packaging** — a documented, scoped release with the full validation
   suite green.

---

## Changed

### Persistence & audit
- **Support-audit persistence** (`validation/collect.py`): each finding carries an
  inline `support_audit` projection (`status` / `numeric_check` /
  `numbers_supported` / `numbers_missing` / `scope_flags`), restored from the
  finding row on offline rebuild — with a `claim_audit` join as fallback. The
  audit is self-contained; no second support model was introduced.
- **Result-store isolation** (`app/runtime/result_store.py`): per-run result
  stores are isolated so concurrent runs do not cross-read each other's state.

### Scheduler & team
- **Replan topology application** (`app/scheduler/replan.py`,
  `app/scheduler/scheduler.py`): a replan now applies its resulting topology
  consistently, and the event it emits is truthful about what changed.
- **Max-concurrency** (`app/runtime/orchestrator.py`): derived concurrency is
  bounded and applied deterministically.

### Frontend
- **Version label** (`frontend/src/i18n/index.ts`): bottom-left version reads
  `v0.6.2` (was stale at `v0.6.0`).
- **Google Fonts removed** (`frontend/src/style.css`, `frontend/index.html`):
  the runtime `@import` of `fonts.googleapis.com` and the `preconnect` links to
  `fonts.googleapis.com` / `fonts.gstatic.com` are gone. The font stack already
  had `system-ui` / `ui-monospace` fallbacks, so layout, sizes and weights are
  unchanged — the browser just uses system fonts.

### Version metadata
- `pyproject.toml` and `frontend/package.json`: `0.6.1` → `0.6.2` (version string
  only; no behaviour change).

---

## Added tests

- `tests/test_support_audit_persistence.py` — inline projection survives offline
  rebuild; parity with live counts.
- `tests/test_result_store_isolation.py` — per-run stores are isolated.
- `tests/test_replan_topology_application.py` — replan topology is applied.
- `tests/test_replanner_event_truthfulness.py` — replan events tell the truth.
- `tests/test_max_concurrency.py` — derived concurrency is bounded.
- `tests/test_support_level_semantics.py` — support-level classification is
  deterministic.

---

## Validation

| Check | Result |
|---|---|
| `pytest -q` | **621 passed / 7 skipped** |
| `ruff check .` | clean |
| `npm run build` (frontend) | pass (v0.6.2) |
| Real LLM (DeepSeek) validation | pass |
| Real Tavily web-search validation | pass |
| Offline validation | pass |
| UI manual acceptance | pass (only P3 polish items left) |
| Secret scan | 0 hits across tracked files |

Real runs use DeepSeek and the Tavily search API. The v0.6.2 release is built on
the same real-validation programme as v0.6.1 (Scenario A + B, real web search,
offline baselines); the earlier runs remain the evidence base. These are
**small-sample experiments**, not a production-grade stability claim.

---

## Known limitations

- The run registry remains in-memory; history is lost on restart (design limit,
  lightweight persistence deferred to v0.7+).
- Offline mode is intentionally deterministic / mock where configured.
- Agent count and team topology may vary under real LLM execution (a real
  Scenario B once degraded on a transient web-search timeout, then succeeded
  cleanly on re-run).
- BUG-02 (low-contrast badges) and BUG-03 (offline-label semantics) are
  intentionally unchanged in this release.

---

## Upgrade notes

- No schema migrations. `SynthesisResult` fields added in v0.6.1 remain; the
  inline `support_audit` on findings is additive.
- Configuration unchanged: `AUTOTEAM_API_KEY` / `AUTOTEAM_WEB_SEARCH_API_KEY`
  remain optional — without them everything runs offline on the mock provider.
- The runtime no longer makes any request to `fonts.googleapis.com` /
  `fonts.gstatic.com`; a hard browser refresh is enough to clear the previous
  `ERR_CONNECTION_TIMED_OUT`.
