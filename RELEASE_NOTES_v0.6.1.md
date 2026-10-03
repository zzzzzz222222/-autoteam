# AutoTeam v0.6.1 Release Notes

> Released: 2026-10-03 · Base: v0.6.0 (`f651f73`)
> Theme: **Honesty & Reliability Hardening** — make the pipeline report what it
> actually did, and stop retrying failures that cannot succeed.

---

## Summary

v0.6.1 is a targeted hardening release on top of v0.6.0. It does **not** add new
agent capabilities. Instead it closes a set of concrete gaps found during real
LLM + real web-search validation runs, in three areas:

1. **Provenance you can audit** — every claim is scored against the evidence it
   cites, and unsupported claims are downgraded instead of silently passing.
2. **Failures that tell the truth** — structured-output failures are classified
   (truncated / length_limit / invalid_json / schema), and only the failure that
   is actually deterministic gets a bounded adaptive retry.
3. **Costs and verdicts that are real** — per-call token usage, estimated cost,
   and a strict real-E2E verdict that refuses to pass a run which never searched
   the web when the scenario required it.

---

## Changed

### Provenance & evidence
- **Source identity** (`app/synthesis/source_identity.py`): URL normalisation so
  the same source is not double-counted, and conflicting identities are split
  and surfaced instead of silently overwritten.
- **Claim support** (`app/synthesis/claim_support.py`, `app/synthesis/claim_quality.py`):
  every asserted number in a finding is checked against the cited snippets and
  reported as `partial` / `supported` / `unbound_citation` — including which
  numbers could **not** be found.
- **Evidence selection** (`app/synthesis/evidence_selection.py`): value-ranked
  evidence budgeting so large runs keep the most useful evidence under a cap.
- **Source policy** (`app/synthesis/source_policy.py`): declarative per-intent
  source requirements; a deliverable whose declared intent needs sources but has
  no bound snippet is reported as a gap, and unsourced `source_fact` claims are
  downgraded to `unverified_claim`.
- **Provenance validation** (`tests/test_provenance.py`): dangling evidence
  references are rejected instead of rendered as citations.

### Reliability
- **Structured-output classification** (`app/llm/structured.py`): failures are
  categorised (`empty` / `not_json` / `truncated` / `invalid_json` /
  `schema_mismatch` / `length_limit`) with safe diagnostics (length, hash,
  delimiter balance) — never the raw payload.
- **Adaptive `length_limit` retry** (`app/runtime/agent_runtime.py`): a confirmed
  length stop is deterministic, so re-sending the identical request just fails
  again. The agent runtime now raises the output ceiling (bounded, clamped,
  restored afterwards) and asks for a smaller answer — at most
  `LENGTH_LIMIT_ADAPTIONS` extra calls, always inside the run's LLM budget. All
  other failure categories keep their previous behaviour.
- **Partial-deliverable honesty** (`app/runtime/agent_runtime.py`,
  `app/runtime/session.py`): budget/iteration exhaustion and missing
  deliverables are marked `partial` instead of being counted as full success.

### Observability
- **Token usage & cost**: the provider copies `response.usage` into
  `last_response_meta`; the validation `CountingProvider` aggregates it, and
  `validation/pricing.py` derives `estimated_cost_usd` from real usage. Unknown
  models report `null` — never a guess.
- **Real-E2E verdicts** (`validation/collect.py`): a run is only
  `valid_real_e2e` when the LLM was real, the web search was real, nothing was
  blocked, and the scenario's source requirements were met. Offline/mock
  fallback is always reported as such.
- **Executive summary states**: the summary is `model`-written, composed from
  validated findings (`derived_from_findings`), or explicitly `unavailable` — a
  statistical placeholder is never presented as a summary.
- **Deterministic finding counts** (`compute_finding_counts`): findings are
  classified in code (total / with valid evidence / supported / multi-source /
  single-source / unverified / unsupported), so counters can no longer disagree
  with the data.

### Frontend
- Result view surfaces the new summary state and finding-count breakdown;
  execution view shows clearer DAG edges; i18n strings updated.

---

## Validation

| Check | Result |
|---|---|
| `pytest -q` | **510 passed / 7 skipped** |
| `ruff check .` | clean |
| `npm run build` (frontend) | pass |
| Offline Scenario A / B | 8/8 and 7/7 agents succeed |
| Offline Single-Agent Baseline | pass |
| Historical `synthesis.json` compatibility | 22/22 parse cleanly |
| Secret scan | 0 hits across tracked files and run artifacts |

### Real-LLM evidence (limited, experimental)

Real runs use DeepSeek (`deepseek-chat`) and the Tavily search API. Across the
validation programme: **14 unique real runs** (Scenario A ×8, Scenario B ×4,
Single-Agent Baseline ×2), measured cost ≈ **$9.63**. The most recent real
Scenario B run completed `valid_real_e2e` with 7/7 agents, 2 real web searches,
123,057 tokens and a 545-character grounded executive summary.

These are **small-sample experiments**, not a production-grade stability claim.

---

## Known limitations

- The adaptive `length_limit` branch has **not** been observed triggering in a
  real run yet (all calls in the latest real run finished with
  `finish_reason=stop`); its coverage is offline tests.
- The post-fix real-E2E sample is small (one run); the earlier real Scenario B
  failure rate is documented and remains valid context.
- Evidence/citation checks verify *referential integrity* — they do not
  substitute for human review of the underlying facts.
- High-concurrency and long-running stability have not been profiled.
- Some market-research conclusions still require verification against the
  original sources.

---

## Upgrade notes

- No schema migrations. `SynthesisResult` gained additive, code-owned fields
  (`summary_status`, `summary_reason`, `finding_counts`); older payloads parse
  unchanged.
- `validation/runs/` is now git-ignored (regenerable run artifacts); the
  validation harness and reports remain tracked.
- Configuration is unchanged: `AUTOTEAM_API_KEY` / `AUTOTEAM_WEB_SEARCH_API_KEY`
  remain optional — without them everything runs offline on the mock provider.
