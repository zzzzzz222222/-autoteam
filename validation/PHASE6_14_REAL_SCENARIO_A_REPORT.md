# AutoTeam v0.6.0 — Phase 6.14 真实 Scenario A 单次验证与最终审计 报告

分类标签：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】

## 0. 结论（Verdict）

- **P6.14 判定：PASS — 真实端到端链路验证通过（`valid_real_e2e`）**
- 本次（P6.14 授权内）执行 **1 次**真实 Scenario A：`run_bf825850`，`session_status=success`，`termination=completed`，`verdict=valid_real_e2e`。
- 这直接消解了 P6.13 的 BLOCKED 状态：真实 LLM（DeepSeek）+ 真实 Web Search 链路确实可端到端运行并完成六类综合。
- 闸门已在运行后**立即恢复为 `False`**（sha256 复原逐字节校验通过），未遗留开启态。

## 1. 授权与边界（与 P6.14 指令对齐）

- 授权动作：临时将 `validation/run_scenario.py` 的 `REAL_EXECUTION_ENABLED` 由 `False` 翻为 `True`，执行一次真实运行后**立即**恢复 `False`。
- 本次**仅执行 1 次**真实运行（`runs=1`）。未做第二次、未做 Baseline、未扩大预算、未泄露密钥、未写 Git、未自动进入 P6.15。
- 预算上限（严格遵守）：`--max-llm-calls 20 | --max-tool-calls 6 | --max-iterations 4 | --timeout 300 | --max-total-minutes 10`。

## 2. 闸门改动记录（Gate Mutation Record）

| 项 | 值 |
|---|---|
| 文件 | `validation/run_scenario.py` |
| 行 | 58 |
| 改动前 | `REAL_EXECUTION_ENABLED = False` |
| 改动后（临时） | `REAL_EXECUTION_ENABLED = True`（注释标记 P6.14 临时） |
| 复原后 | `REAL_EXECUTION_ENABLED = False` |
| 改动前 sha256 | `f23c27f8def55e3b59eda8b1f8be3af990deb6756c81d1189551e3eecb79f543` |
| 临时(True) sha256 | `cd5bc83d9006cb00985e01df58fecf98a20c552da2e855b9e6073030b711b850` |
| 复原后 sha256 | `f23c27f8def55e3b59eda8b1f8be3af990deb6756c81d1189551e3eecb79f543`（与改动前**逐字节一致**） |
| 复原校验 | PASS（哈希一致 + 行内容确认 `False`） |
| 残留进程 | 无（运行 `EXIT=0` 后进程已退出） |

## 3. 预检（Pre-flight，只读）结论

- CLI 参数与 P6.14 规范完全一致：`--scenario A --runs 1 --mode real --confirm-real --max-tool-calls 6 --max-iterations 4 --timeout 300 --max-total-minutes 10 --max-llm-calls 20`。
- Provider 解析：`AUTOTEAM_LLM_PROVIDER=deepseek`（含行内注释），且显式设置 `AUTOTEAM_LLM_MODEL=deepseek-chat`、`AUTOTEAM_LLM_BASE_URL=https://api.deepseek.com/v1` → `get_llm_provider()` 解析为**真实 `OpenAILLMProvider`**（非静默回退 Mock）。
- 权限链：`CAPABILITY_TOOLS` 含 `REQUIREMENT_ANALYSIS: ("web_search")`（`tool_selector.py:36`，P6.12 修复在位）。
- Web Search：`AUTOTEAM_WEB_SEARCH_URL` 与 `AUTOTEAM_WEB_SEARCH_API_KEY` 均存在 → `web_search` 在本运行执行**真实外部检索**（Tavily 兼容端点），失败时优雅降级为 `offline_fallback`（不崩溃、不泄露密钥）。

## 4. 本次真实运行指标（`run_bf825850` / batch `20261002T140813Z_A_real`）

| 维度 | 值 |
|---|---|
| provider | `CountingProvider` → `OpenAILLMProvider(deepseek-chat)` |
| `is_real_llm` | `True` |
| `is_real_web_search` | `True`（web=6, offline=0） |
| agents | 8（全部 success） |
| DAG | 4 层 / 11 边 / hierarchical |
| llm calls | 16（blocked=0） |
| tool calls | 6（web:6, local:0, offline_mock:0, offline_fallback:0） |
| retries | 1 |
| elapsed | 171.122 s |
| termination | `completed`（非 aborted / 非 timeout / 非 budget_exhausted） |
| session_status | `success` |
| verdict | `valid_real_e2e` / `is_valid_real_e2e=True` |

## 5. 权限链 / 团队工具映射核验（P6.12 修复在真实运行中的实证）

`team.json`（本次真实运行生成）：
- `requirement_analyst`：`capabilities=[requirement_analysis]`，`tools=["web_search"]` ✅（P6.12 修复生效；此前为 `tools=[]`）
- `market_researcher` / `competitor_analyst` / `technology_analyst`：`tools=["web_search"]`
- `data_analyst`：`tools=["data_analyzer","calculator"]`
- `backend_developer`：`tools=["code_analysis"]`
- `proposal_writer` / `report_writer`：`tools=[]`（聚合/撰写角色，按设计不持工具）✅

## 6. 源身份（Source Identity, P6.9 不变量）审计

- `sources.json`：`count=25`，`by_type={web:25}`。
- 25 条归一化 `identity` **全部唯一**（无重复 URL）；全部 `https`；无空 URL；无 `offline_mock`。
- 真实外部域名示例：gartner.com、precedenceresearch.com、grandviewresearch.com、marketsandmarkets.com、upwork.com、finance.yahoo.com、en.wikipedia.org、techaisle.com 等。
- **结论：无 Mock 伪装为真实、无重复、无空引用。**

## 7. 证据绑定（Evidence Binding）审计

- `evidence.json`：`count=83`。
  - 绑定到真实 web 源（`source_fact`）：**20 条**
  - 未绑定（`unverified_claim`，`source_id` 为空，属内部假设/派生）：**63 条**
  - **悬空引用（非空但指向不存在的源）：0 条** ✅
- 说明：63 条未绑定证据均被系统**显式降级**为 `unverified_claim`（非伪造），并在 `report.md` 的 Citation Audit / Evidence Gaps 中透明标注。

## 8. 综合六类（Synthesis Six Types）审计

`synthesis.json`：`available=True`，`status=completed`，`degraded=False`。

| 类型 | 数量 |
|---|---|
| findings | 6 |
| insights | 4 |
| contradictions | 4 |
| uncertainties | 5 |
| tradeoffs | 3 |
| recommendations | 5 |

- 注：`supported_findings=0` / `single_source_findings=0`（6 条 `key_findings` 未进一步细分到 supported/single_source 子类，属综合分类细节，不影响六类完整性）。

## 9. `requirement_analyst` Web Search 实证（P6.12 修复的核心验收点）

- **授权层（已验证修复）**：`team.json` 确认 `requirement_analyst` 持 `tools=["web_search"]`；本次真实运行未发生 `ToolDenied`；agent 以 `success` 完成。
- **真实运行调用层**：`trace.json` 显示 `requirement_analyst` 仅经历 `READY→STARTED→OUTPUT→ARTIFACT`，**未发起 `web_search` 工具调用**（本次 6 次 web 调用来自 Market / Competitor / Technology Analyst）。其交付物的 9 条证据 `source_id` 均为空，被降级为 `unverified_claim`。
- **透明性**：`requirement_analyst` 交付物原文声明"由于本轮未调用外部工具，本报告所有结论均为工作假设与待验证项"（`report.md:217`），并给出 `evidence_plan` / `search_queries_to_run` 待执行清单 —— 系统**未伪造**需求侧证据。
- **离线旁证**：P6.12 离线运行（`run_68744dc8`）中 `requirement_analyst` 曾调用 `web_search`（7 次工具调用），证明授权路径在"决定检索时"确实可执行。
- **设计推断（非缺陷）**：本真实运行中 LLM 的任务分解未触发 `requirement_analyst` 的 `web_search`；授权修复本身正确，但"需求侧结论是否被真实检索支撑"仍取决于 LLM 每次的分解决策。列为后续观察项（见 §12）。

## 10. 真实运行诚实度 / 不确定性评估

- Citation Audit：`kf_001` partial、`kf_002` none/unsupported、`kf_003` none、`kf_004` partial、`kf_005` all_matched、`kf_006` no_numbers；多处 `unbound_citation` 被明确标出。
- Evidence Gaps 逐 agent 标注 source 覆盖率（Requirement 0/9、Data 0/11、Backend 0/14、Proposal 0/15、Report 0/11、Competitor 9/10、Technology 1/3）。
- Technology Analyst 为 partial deliverable（工具/迭代预算耗尽）→ 技术侧证据稀薄，已在报告中标注。
- **结论：系统对未支撑 / 未检索 / 时效性 / 证据缺口均显式标注，无粉饰。**

## 11. 离线回归（P6.14 任务 #5）

- `pytest -q`：**471 passed, 7 skipped**（与 P6.12 基线完全一致；闸门翻转为净零改动，无回归）。
- `ruff check .`：**All checks passed!**
- 前端未改动 → 未触发前端构建。

## 12. 残留风险 / 观察项（Watch Items）

1. **真实 API 成本不可测量**：核心 provider 丢弃 token usage，`REAL_MODE_NOTICE` 已声明；本次真实运行花费的精确 USD **not_measured**（标记【未验证】）。
2. **`requirement_analyst` 真实检索非必然**：授权已修复，但 LLM 分解不保证每次触发其 `web_search`；如需"需求侧必含真实证据"，需进一步在 agent prompt / 任务分解层强制检索（超出 P6.14 范围）。
3. **Technology Analyst 预算敏感**：`max-iterations=4` / `max-tool-calls=6` 下出现 partial deliverable；若需完整技术侧证据，可适当上调预算或拆分。
4. **跨运行可复现性 not_verified**：P6.14 禁止第二次真实运行，故仅单点验证，未做多次一致性比对。
5. **Baseline 未执行**：P6.14 明确禁止 Baseline，故无基线对照。

## 13. 历史真实运行清单（透明披露）

磁盘上今日（2026-10-02）共 7 个 `A_real` 批次，全部 `is_real_llm=True`、`is_real_web_search=True`、`session_status=success`：

| 批次 | verdict | llm | web | 备注 |
|---|---|---|---|---|
| `20261002T074824Z_A_real` | valid_real_e2e | 16 | 7 | 早于 P6.14 授权 |
| `20261002T081913Z_A_real` | degraded_partial | 12 | 6 | 早于 P6.14 授权 |
| `20261002T083810Z_A_real` | degraded_partial | 17 | 6 | 早于 P6.14 授权 |
| `20261002T085948Z_A_real` | valid_real_e2e | 17 | 5 | 早于 P6.14 授权 |
| `20261002T095017Z_A_real` | valid_real_e2e | 18 | 5 | 早于 P6.14 授权 |
| `20261002T102529Z_A_real` | valid_real_e2e | 15 | 6 | 早于 P6.14 授权 |
| **`20261002T140813Z_A_real`** | **valid_real_e2e** | **16** | **6** | **P6.14 授权内执行（本报告主体）** |

说明：前 6 个批次早于本 P6.14 任务的显式授权，其授权背景不在本任务范围内，此处仅作透明披露。本任务严格只执行了 1 次（`140813Z`）真实运行，且已立即复原闸门。

## 14. 不可验证字段显式标注

- `real_api_cost_usd`: `"not_measured"`（provider 丢弃 usage）
- `token_usage`: `"not_available"`
- `requirement_analyst_web_search_invoked_this_run`: `"no"`（authorized=yes, offline_verified=yes）
- `cross_run_reproducibility`: `"not_verified"`（单点）
- `baseline_comparison`: `"not_performed"`（P6.14 禁止）

---

报告生成：2026-10-02（P6.14） · 分类：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】
主体运行目录：`validation/runs/20261002T140813Z_A_real/run1_run_bf825850/`
