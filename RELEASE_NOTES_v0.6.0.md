# AutoTeam v0.6.0 — Release Notes

**Agent Team Synthesis & Evidence-Backed Reporting**

> AutoTeam is a dynamic multi-agent orchestration framework for real-world agent
> execution and evidence-backed research synthesis. It is an experimental design
> study — not a production platform and not an autonomous decision-maker.

## Highlights

| Capability | Status |
|---|---|
| Agent Team Synthesis (cross-agent synthesis pass) | implemented, tested & run live |
| Evidence Filtering (deterministic, provenance-complete) | implemented & tested |
| Key Findings with derived support status | implemented & tested |
| Cross-Agent Insights (single-agent flagged, never dressed up) | implemented & tested |
| Contradictions & Uncertainties (no automatic winner) | implemented & tested |
| Trade-offs (derived per task, never hardcoded) | implemented & tested |
| Recommendations with real traceability + status | implemented & tested |
| `claim_type` data-nature tagging (fact / estimate / assumption / unverified) | implemented & tested |
| Real / Offline / Local / Mock tool transparency | implemented & tested |
| Deterministic reference audit (dangling-ref detection) | implemented & tested |
| Result page readability + provenance layering | implemented & reviewed |
| Friendly error handling + honest degraded reporting | implemented & tested |

## Core execution chain

```
Task → Task Understanding → Capability Discovery → Dynamic Role Allocation
     → Agent Factory → DAG Validation → Async Execution → Real LLM
     → Real Tavily Search → Agent Artifacts → Evidence Filtering
     → Cross-Agent Synthesis → Insights → Contradictions / Uncertainties
     → Trade-offs → Recommendations → Final Markdown Report
```

The core principle is unchanged: **LLM proposes → Schema constrains → Code
validates → Executor executes.** v0.6.0 adds a *synthesis* stage after execution;
it does not replace the scheduler, runtime, retry/replan, or artifact system.

## What is new in v0.6.0

### 1. Evidence Filtering (`app/synthesis/evidence_filter.py`)

- Agent artifacts → normalised `EvidenceRecord[]` + `SourceRecord[]`.
- Stable `evidence_id` (content hash), source merging by id **and** URL,
  duplicate-claim merging.
- Every record keeps producer agent + artifact id; non-http URLs are stripped.
- Real URLs are never fabricated; offline sources stay `offline_mock` with an
  empty URL.

### 2. Cross-Agent Synthesis (`app/synthesis/`)

`SynthesisResult` = Key Findings · Supported · Single-source ·
Cross-Agent Insights · Contradictions · Uncertainties · Trade-offs ·
Recommendations.

Deterministic validation (no LLM judge, no scores):

- every cited `evidence_id` must resolve, or the item is dropped;
- recommendation → insight / trade-off links are kept consistent;
- finding `support_kind` is **derived from the cited evidence** (≥2 distinct
  agents *or* ≥2 distinct sources → `multi_source`), never from a raw count;
- insight `contributing_agents` is derived from the cited evidence producers —
  a single-agent insight is explicitly flagged, not dressed up as cross-agent;
- a deterministic reference audit (`validate_report_references`) reports
  duplicate / dangling references.

### 3. `claim_type` — data nature, never guessed

Optional, backward-compatible field on findings / insights / recommendations /
evidence:

| value | meaning |
|---|---|
| `source_fact` | a source states it directly (not an independent audit) |
| `derived_estimate` | computed from traceable inputs (inputs/method in `derivation`) |
| `planning_assumption` | product / business goal or forecast |
| `unverified_claim` | thin or unverifiable support |

Unknown or missing values are normalised to `""` (unclassified) — the system
never infers a data nature from formatting. In the UI an untagged numeric claim
is shown as *unclassified*, not as fact.

### 4. Result page (Vue) readability & provenance

- The report body no longer exposes internal ids in the reading flow; raw
  `evidence_id` / `agent_id` / `artifact_id` live in expandable **Traceability**
  areas.
- Key Findings / Insights / Contradictions / Trade-offs / Recommendations are
  rendered as structured blocks with support status, agents, evidence and source
  counts, data nature and derivations.
- Recommendations expand into a **Recommendation → Insight / Trade-off →
  Evidence → Source** chain; unresolved ids render as "reference missing".
- Source URLs are only clickable for valid `http(s)` links; long URLs are
  truncated but still open the full address; titles/domains are shown.
- Empty states and a degraded-synthesis banner are explicit. Original agent
  sections and Evidence / Sources are preserved; Copy / Save `.md` are kept.

### 5. Real / Offline / Mock transparency

`ToolResult.kind` records the true execution nature:

| kind | meaning |
|---|---|
| `web` | a real external web search actually succeeded |
| `local` | a real local deterministic tool (`calculator`, `local_knowledge`) |
| `offline_mock` | deterministic offline stub (`web_search` offline, `mock_search`, stubs) |
| `offline_fallback` | a real search attempt failed and degraded to offline results |

The UI reads `tool_kind` from real execution events — an *Offline* run is never
labelled *Real*, and a real local tool is never mislabelled *Mock*. Offline
`execute_task` runs now force mock tools even if real search keys exist in the
environment, so an Offline run can never silently hit the network.

### 6. Error handling

- Friendly user-facing messages; full exception detail stays in logs/raise chain.
- A model that finishes **without a deliverable** now fails (and is retried /
  replanned) instead of being recorded as a successful empty artifact.
- If synthesis cannot produce a valid structured result, the run degrades to a
  clearly-marked result (`synthesis_status = degraded/failed` + reason) — never a
  silent fake success.

## Verification (this release environment)

| Check | Result |
|---|---|
| `pytest -q` | **218 passed** |
| `ruff check .` | clean |
| `npm run build` (vue-tsc strict + Vite) | pass |
| Offline E2E (`examples/real_world_demo.py`, no key) | SUCCESS · `offline_mock` sources |
| Tool-kind / offline-determinism tests | pass |
| Deterministic reference audit | pass |
| Security scan (tracked files) | no tracked secrets / logs / absolute paths |
| Frontend unit tests | none exist in this repo (no test runner configured) |

### Real E2E (actually executed)

A live end-to-end run was executed with a real OpenAI/DeepSeek-compatible
provider and the real Tavily search adapter, using the task from the release
brief (AI Agent market + SME product plan). Honest result of that run:

- **Session status:** `success` (no provider fallback)
- **Agents:** 5, all produced substantive artifacts
  (Market Researcher, System Architect, Requirement Analyst, Test Engineer,
  Proposal Writer)
- **Retry:** 2 agents failed an attempt and recovered on retry (recorded as real
  `AGENT_FAILED` / `AGENT_RETRY` events, final status success)
- **Synthesis:** `completed` — 10 findings, 4 insights, 2 contradictions,
  6 uncertainties, 3 trade-offs, 6 recommendations
- **Provenance:** 20 evidence / 8 sources, all `web`, 8 real URLs;
  **0 dangling reference issues**
- **Tool kinds observed:** `web` (real search) + `offline_mock` + `local`
  (transparently separated in the same run)

Note: this was a single verified run, not sustained production testing, and the
report quality (not just the task status) was inspected manually. See the
Limitations section.

A **later audit run** (same task, same configured provider/Tavily) hit a real
structured-output failure during synthesis
(`LLM provider call failed: JSONDecodeError`). The run still completed with
`session_status = success` while `synthesis_status = degraded`: the report
clearly states that synthesis degraded, key findings fall back to artifact-level
records, and **no insights / trade-offs / recommendations were invented**. This
confirms the degradation path is honest; it also shows real synthesis reliability
is provider-dependent and **not guaranteed** — a documented limitation, not a
silent failure.

## UI improvements (summary)

- Reading-first layout; internal fields moved into expandable Traceability.
- Data nature, support status and provenance rendered as small badges/chips.
- Recommendations expose a real trace chain and honest status
  (evidence-backed / potential · unverified / no evidence support).
- Safe external links only; long URLs wrap instead of overflowing.
- Degraded and empty states are explicit.

## Known limitations

- Offline mock results are not a substitute for real model quality.
- Real synthesis reliability is **provider-dependent and not guaranteed**: a
  real model can return invalid JSON for the synthesis schema. When that happens
  the run degrades transparently (`synthesis_status = degraded`, legacy/artifact-
  level findings) instead of fabricating insights.
- Cross-agent insights require evidence from ≥2 agents; when only one agent
  produced citable evidence, insights are labelled **single-agent** rather than
  invented as cross-agent.
- `claim_type` is proposed by the synthesis model and validated against a
  whitelist; it is a *label*, not an independent fact-check.
- Market numbers come from the cited sources and were **not** independently
  audited by AutoTeam.
- Session state and the API run registry are in-memory (no persistence).
- This is not a production-grade distributed execution platform and makes no
  "fully autonomous" or "100% accurate" claim.
- There are no frontend unit tests (only `npm run build` type-check + manual
  review).

## Difference from v0.5.0

v0.5.0 delivered real-world agent execution (real LLM, real Tavily, Sources /
Evidence, validation). v0.6.0 adds the **synthesis and reporting layer** on top:
deterministic evidence filtering, cross-agent synthesis, insights /
contradictions / uncertainties / trade-offs / recommendations, data-nature
tagging, a deterministic provenance audit, honest tool-kind transparency, and a
reading-first Result page. No core orchestration, scheduler, retry/replan or
runtime protocol was rewritten.

## Breaking changes

None. All new schema fields are optional with safe defaults; historical
artifacts and older API clients continue to parse.

---

## Hardening Pass Addendum (2026-10-03)

> 分类：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】【人工核验】

本附录记录 v0.6.0 **发布前硬化收尾**的实际状态，覆盖上文"Verification (this release environment)"之外的增量工作。

### 增量修复（本次硬化）【实际测试】
- **R2 诚实判定（真阻断）**：`CompletionCriteria` 现纳入"真来源缺口"与"部分交付"，不再把缺来源/部分交付谎报为 SUCCESS（`app/runtime/session.py`）。
- **R5 部分交付标记（真阻断）**：`_real_execution` 返回 5 元组并写入 `metadata["partial"]`；预算/迭代耗尽或"无交付却有工具调用"明确标 partial（`app/runtime/agent_runtime.py`）。
- **R1 可观测性**：核心早已捕获 `response.usage`（已聚合）；本次修复**上报层**——新增 `validation/pricing.py`（价表 + `compute_cost`，未知/离线报 `None`），`collect.py` / `baseline.py` / `run_scenario.py` 诚实上报 usage 与成本（绝不臆测）。
- **来源策略收紧**：`SOURCE_REQUIRED_INTENTS` 与 `CAPABILITY_TOOLS` 对齐，移除 `data_insights` 不一致项；`source_gaps_present` 仅在真未满足需求时降级。

### 增量验证证据【实际测试】
| 项 | 结果 |
|----|------|
| `pytest -q` | **481 passed, 7 skipped** |
| `ruff check .` | clean |
| `vue-tsc --noEmit` + `vite build` | pass (built ~1.6s) |
| 离线 Scenario A / B E2E | 8/8、7/7 成功（verdict `not_real_llm`） |
| 离线 Single-Agent Baseline | 跑通（cost unavailable 诚实） |
| 安全 / 密钥扫描 | `.env` gitignored & 未跟踪；源码密钥签名 0 命中 |

### 真实运行复核状态【BLOCKED】
上文"Real E2E (actually executed)"为发布前 pre-publication pass 的**历史**真实证据，**本次硬化未重新执行真实运行**，原因双重且独立：
1. 硬闸门 `REAL_EXECUTION_ENABLED = False`（发布前不变量）禁止开启；
2. 配置的底层 LLM API 余额耗尽（HTTP 402），即便开启亦会中止。

因此 R1 真实观测 / R2 真实工具调用 / R3 真实 Baseline / 稳定性复跑均标 **BLOCKED**；真实语义质量需真实运行 + 人工核验，标 **未验证**。

### 发布决策【设计推断】
**NO-GO / DEFERRED（本次不发布）**：离线质量/可靠性/安全达标，但真实运行证据缺失，未满足"验收后再发布"。本次**不执行** `git commit/tag/push/GitHub Release`，工作树保留供维护者复核。解锁门槛见 `validation/RELEASE_READINESS.md` §3。

### 六份配套报告（validation/）
`FINAL_HARDENING_REPORT.md` · `FINAL_VALIDATION_MATRIX.md` · `BASELINE_COMPARISON_REPORT.md` · `SEMANTIC_QUALITY_AUDIT.md` · `RELEASE_READINESS.md` · `AUDIT_MATRIX.md`（审计基础）。
