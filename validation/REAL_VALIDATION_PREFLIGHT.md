# AutoTeam v0.6.0 — 真实验证飞行前检查 (REAL VALIDATION PREFLIGHT)

> 生成时间：2026-10-03（Phase 1 重新审计 + Phase 3 余额核验）
> 分类：【真实运行】【实际测试】【静态审计】【设计推断】【人工核验】【未验证】【BLOCKED】
> 原则：第一步重新检查实际仓库，不假定上一轮状态仍准确。

---

## 1. 版本与 Git 状态【静态审计】

| 项 | 值 |
|----|----|
| 版本 | v0.6.0 |
| 分支 | `master` |
| HEAD | `be7be31de223f00fc8a549eae05283662b1428b0` |
| Remote | `origin` = `https://github.com/zzzzzz222222/-autoteam.git`（已存在，fetch + push） |
| Tag `v0.6.0` | 已存在（指向历史提交；当前 HEAD 领先于该 tag，存在未提交改动） |
| `.env` | 已被 `.gitignore:16` 忽略；`git ls-files` 未跟踪 → **无密钥泄漏风险** |

### 当前未提交文件清单（git status --short）
**已修改（19）**：README.md、RELEASE_NOTES_v0.6.0.md、app/llm/provider.py、app/runtime/{agent_runtime,artifacts,assembler,session,tool_selector,validation}.py、app/synthesis/{assembler,evidence_filter,models,pipeline,synthesizer}.py、app/tools/registry.py、frontend/src/{i18n/index.ts,types.ts,views/ExecutionView.vue,views/ResultView.vue}、tests/{test_api,test_realworld,test_synthesis}.py
**未跟踪（含 validation/ 整体）**：app/llm/structured.py、app/runtime/claim_quality.py、app/synthesis/{claim_support,evidence_selection,prompts,source_identity,source_policy}.py、tests/{test_final_hardening_r1_r2,test_phase611_tool_execution,test_phase612_capability_tools,test_phase66_repair,test_phase69_source_identity,test_provenance,test_synthesis_reliability,test_synthesis_scaling,test_validation,test_validation_budget}.py、validation/（含上一轮报告与 runs/）

> 说明：上述修改与未跟踪文件均为本轮硬化与历史硬化产出，用户原有改动完整保留；未发现无法确认归属的修改。

---

## 2. 真实执行闸门状态【静态审计】

- `validation/run_scenario.py:58`：`REAL_EXECUTION_ENABLED = False`（**当前仍为发布前安全默认**）。
- 用户已明确授权开启与恢复该闸门以执行真实验证；本检查阶段**未开启**。
- 真实运行仅在 `--mode real --confirm-real` 且闸门为真时执行；`real_mode_gate()` 二次确认。

---

## 3. Provider 与模型配置状态【静态审计】

| 配置键 | 状态（不含值） |
|--------|----------------|
| `AUTOTEAM_LLM_PROVIDER` | 已配置（值为 `deepseek`） |
| `AUTOTEAM_API_KEY` | **已设置**（不显示内容；长度 35） |
| `AUTOTEAM_LLM_MODEL` | 已配置（`deepseek-chat`） |
| `AUTOTEAM_LLM_BASE_URL` | 已配置（`https://api.deepseek.com/v1`） |
| `AUTOTEAM_WEB_SEARCH_URL` | 已配置（`https://api.tavily.com/search`） |
| `AUTOTEAM_WEB_SEARCH_API_KEY` | **已设置**（不显示内容；长度 58） |

- 解析路径：`get_llm_provider()`（app/llm/provider.py:167）→ 配置齐全时返回 `OpenAILLMProvider`（OpenAI 兼容端点，兼容 DeepSeek）。
- Web Search：`app/tools/registry.py:168 web_search()` 双模式——配置齐全时真实 POST Tavily，失败诚实降级为 `offline_fallback`（**绝不泄露密钥、绝不伪造 URL**）。

### 配置瑕疵（非阻断，不修改）
`.env` 第 37 行为合并的注释行（`# LOG_LEVEL=INFO` 与 `AUTOTEAM_WEB_SEARCH_URL=...` 被并入同一注释行），但第 38/39 行已有正确且生效的未注释 `AUTOTEAM_WEB_SEARCH_URL` / `AUTOTEAM_WEB_SEARCH_API_KEY`，故**不影响真实运行**。属纯注释瑕疵，不改动 `.env`（遵守"不得修改真实 API Key / 保留用户文件"约束）。

---

## 4. API 余额可信当前证据【真实运行 — 受控探针】

> 方法：单个 1-token 的真实调用（受控、预算内、不日志密钥），直接核验而非假设。

- **DeepSeek LLM**：实测返回 `RESULT: OK`，模型 `deepseek-chat` 真实响应（`pong`，`total_tokens=15`）。**余额可用**（此前"HTTP 402"为陈旧状态，已不复存在）。
- **Tavily Web Search**：经真实工具路径实测返回 `kind=web`、`offline=False`、5 条真实结果（finance.yahoo.com 等真实域名，URL 真实）。**真实 Web Search 可用**。
- 结论：**上一轮"API 余额耗尽 BLOCKED"的假设已被本次实测推翻**；真实验证前置条件**已满足**。

---

## 5. 预算限制及是否生效【实际测试 + 静态审计】

- `CountingProvider`（validation/counting_provider.py）：原子预约 + 线程安全，达顶拒绝新调用、截止时间拒绝；`blocked` 原因区分 `run_deadline` / `llm_budget_exhausted`；**不伪装为 mock**。已有测试 `test_validation_budget.py`（并发安全、达顶拒绝、截止拒绝、truth 反映 abort、不报 mock、wall-clock 超时中止、aborted 阻断后续）。
- `run_scenario.py` 预算旗标（天花板，非目标）：`--max-llm-calls`(默认20)、`--max-tool-calls`(6)、`--max-iterations`(4)、`--timeout`(300)、`--max-total-minutes`(10)、`--max-total-minutes` 同时约束批处理与单 run 墙钟。
- 真实运行将设置宽松但有限的单 run 天花板（如 `--max-llm-calls 80`、`--max-tool-calls 8`、`--max-iterations 5`、`--timeout 300`、`--max-total-minutes 20`）以保证完整完成，同时受硬天花板保护。

---

## 6. 真实运行入口与验证脚本【静态审计】

- 多 Agent 真实 E2E：`validation/run_scenario.py --mode real --scenario {A|B} --confirm-real --runs N`
- 单 Agent Baseline：`validation/single_agent_baseline.py --mode real --scenario A --confirm-real`
- 稳定性：上述脚本重复运行（Scenario A/B 各累计 3 次）；Baseline 至少 1 次。
- 预算防护：均经 `CountingProvider` + 旗标天花板。
- 数据链：`OpenAILLMProvider.last_response_meta.usage` → `CountingProvider.summary()` → `collect.collect_metrics()` → `pricing.compute_cost`（价表覆盖才报成本，未知/离线报 `None`）。

---

## 7. 当前测试覆盖情况【实际测试】

- 全量 pytest：**481 passed / 7 skipped**（含 R1/R2/R5 修复测试 `test_final_hardening_r1_r2.py`、预算 `test_validation_budget.py`、可靠性 `test_retry/test_replan/test_scheduler/test_api` 等）。
- ruff：All checks passed。
- 前端：`vue-tsc --noEmit` 通过；`vite build` 通过（56 模块）。
- 离线 E2E：Scenario A 8/8、Scenario B 7/7（verdict `not_real_llm`）。
- 离线 Baseline：跑通（cost unavailable 诚实）。

---

## 8. 历史遗留问题【静态审计】

- R8：`RunRegistry` 进程内、重启丢历史（设计限制，待 v0.7+；本轮不重构）。
- R1/R2/R5：核心缺陷**已修复并测试**（本轮硬化产出），详见 `FINAL_HARDENING_REPORT.md`。
- 真实运行历史证据：P6.14 单次真实 Scenario A（`validation/PHASE6_14_REAL_SCENARIO_A_REPORT.md`，`valid_real_e2e=True`，闸门已复原）——历史证据，**本次将重新复测**，不混同。

---

## 9. 本次真实验证前置条件【真实运行 + 静态审计】

| 前置条件 | 状态 |
|----------|------|
| 真实 LLM 凭据存在 | ✅ |
| Web Search 凭据 + Endpoint 配置正确 | ✅ |
| API 余额可信可用（实测） | ✅（DeepSeek 200 / Tavily 真实结果） |
| 预算控制生效 | ✅（CountingProvider + 旗标） |
| 闸门仍为安全默认 | ✅（False，待授权开启） |
| 无密钥泄漏风险 | ✅（.env gitignored；错误仅含异常类型名） |
| 无遗留真实进程 | ✅ |
| 异常退出恢复闸门机制 | ⚠️ 人工：真实运行后手动复原 `REAL_EXECUTION_ENABLED=False`（已计划于 Phase 8） |

---

## 10. 是否可以进入下一阶段

**✅ 可以进入 Phase 4（真实 Scenario A/B E2E）。**

- Phase 2（缺陷复核）将在开启闸门前以定向测试复确认 R1/R2/R5 仍正确。
- Phase 3 余额核验已完成且为 **MET**（实测可用）。
- 下一步：用户已授权，将开启闸门 → 执行真实 Scenario A（1 次）→ 核验 → Scenario B（1 次）→ Baseline → 稳定性复跑 → 语义审计 → 全量回归/安全 → 报告 → 满足条件则发布。
- 若任一真实运行暴露严重缺陷或安全问题，将暂停后续真实实验先修复（遵守停止条件）。
