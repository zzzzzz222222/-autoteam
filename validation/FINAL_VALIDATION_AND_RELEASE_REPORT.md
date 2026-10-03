# AutoTeam v0.6.0 — Final Validation & Release Report

> 生成时间：2026-10-03（UTC+8）
> 执行范围：Phase 1–14（真实验证、全面验收与发布决策）
> 报告性质：**验证报告**，不是宣传材料。所有结论标注证据来源与可信度。

---

## 0. 最终结论

# 🔴 NO-GO / DEFERRED（**已被后续轮次取代 — 见下方更新**）

**未满足全部发布门禁，本次不执行 commit / tag / push / GitHub Release。**

判定依据（详见 §7 门禁表）：G7（真实 Scenario B 通过率 2/3）、G10（交付物 Executive Summary 实质为空）、G11（`length_limit` 重试不自适应）三项未达标。按预设规则「仅当全部门禁满足才 GO」，结论为 NO-GO。

---

> ## 📌 状态更新（2026-10-03 后续轮次）
>
> 本报告记录的 D1 / D3 / D2 三项未达标门禁**已在后续轮次修复并通过 1 次真实 Scenario B 复测**，
> 门禁由「8 过 3 不过」变为 **11/11 满足**，结论更新为 **🟡 GO / READY_TO_RELEASE**（仍未执行发布）。
>
> **本报告中的历史失败记录保持原样、未被覆盖**（B 场景 1/3 invalid、Executive Summary 为空、
> length_limit 重试不自适应），这是后续结论的前提事实。
>
> 后续完整报告：`validation/TARGETED_HARDENING_REVALIDATION.md`；
> 门禁同步见：`validation/RELEASE_READINESS.md` §8。

**这不是回退**：相比本轮开始前的状态，v0.6.0 取得了实质进展——真实 API 可用性已证实（此前误判为 402 不可用）、13 次真实运行完成、R1 用量/成本可观测性由真实数据闭环、并新发现并修复了 2 处失真报告缺陷。

---

## 1. 关键状态翻转：API 可用性

本轮开始前的项目记忆断言「DeepSeek API 余额耗尽（HTTP 402），真实运行 BLOCKED」。

该断言**已被实测推翻**【真实运行】：

| 探测项 | 方法 | 结果 |
|---|---|---|
| LLM 余额 | 1-token 受控探针（DeepSeek） | `RESULT: OK`，返回 `pong`，total_tokens=15 |
| Web Search | 真实 Tavily 路径探针 | `kind=web, offline=False`，返回 5 条真实结果（含 finance.yahoo.com 等） |

**结论**：前置条件满足，真实执行闸门在授权窗口内开启并完成验证，已于 Phase 8 恢复为 `False`。

---

## 2. 真实运行证据总览【真实运行】

### 2.1 运行清单

| # | 场景 | Run | Verdict | Web | LLM 调用 | Tokens | 成本(USD) |
|---|---|---|---|---|---|---|---|
| 1 | A | `20261002T074824Z` | valid_real_e2e | 7 | 16 | — | n/a |
| 2 | A | `20261002T081913Z` | degraded_partial | 6 | 12 | — | n/a |
| 3 | A | `20261002T083810Z` | degraded_partial | 6 | 17 | — | n/a |
| 4 | A | `20261002T085948Z` | valid_real_e2e | 5 | 17 | 128,253 | n/a |
| 5 | A | `20261002T095017Z` | valid_real_e2e | 5 | 18 | 159,225 | n/a |
| 6 | A | `20261002T102529Z` | valid_real_e2e | 6 | 15 | 110,908 | n/a |
| 7 | A | `20261002T140813Z` | valid_real_e2e | 6 | 16 | 109,608 | n/a |
| 8 | A | **`20261003T032043Z`** | **valid_real_e2e** | 5 | 17 | 87,577 | **1.7620** |
| 9 | B | `20261003T033232Z` | **invalid_missing_real_web_search** | 0 | 10 | 65,397 | 1.4283 |
| 10 | B | `20261003T033843Z` run1 | **valid_real_e2e** | 1 | 18 | 115,661 | 2.2638 |
| 11 | B | `20261003T033843Z` run2 | **valid_real_e2e** | 3 | 16 | 80,389 | 1.4920 |
| 12 | Baseline | `20261003T032856Z` | valid_real_e2e | 2 | 3 | 15,021 | 0.2635 |
| 13 | Baseline | `20261003T032919Z` | valid_real_e2e | 1 | 2 | 4,594 | 0.1005 |

> #1–#7 为历史真实运行（成本字段当时尚未实现，故为 n/a，非缺失异常）。
> **可测量总成本：7.31 USD**（#8–#13）。

### 2.2 通过率

| 场景 | 真实运行数 | valid | degraded | invalid | 通过率 |
|---|---|---|---|---|---|
| Scenario A | 8 | 6 | 2 | 0 | 75%（含 degraded 则 100% 非无效） |
| Scenario B | 3 | 2 | 0 | 1 | **67%** |
| Single-Agent Baseline | 2 | 2 | 0 | 0 | 100% |

---

## 3. 真实 Scenario A 深度数据【真实运行】

Run：`validation/runs/20261003T032043Z_A_real/run1_run_16d0d1a0`

| 维度 | 实测值 |
|---|---|
| 真实性判定 | `is_real_llm=True`、`is_real_web_search=True`、`blocked_llm_calls=0` |
| 检索 | web=5，**offline=0、offline_fallback=0** |
| 团队 | 8 agents，DAG 4 层、11 条边 |
| 执行 | 162.794s，8 成功 / 0 失败 / 0 跳过，retries=2，termination=completed |
| LLM | 17 次调用，tokens 49,300 → 38,277（合计 87,577） |
| 成本 | **1.761956 USD** |
| 产物 | artifacts 8，evidence 60，sources 17 |
| 综合 | completed、degraded=False、findings 14、insights 4、contradictions 4、uncertainties 5、tradeoffs 3、recommendations 5、**reference_issues 0**、source_gaps 7、claim_audit 14 |

### 3.1 来源真实性审计【人工核验】

- 17 个来源 **100% 携带 URL**，缺失数 = 0。
- 15 个**互不相同的真实域名**：finance.yahoo.com、rasa.com、www.blueprism.com、www.uschamber.com、joget.com、www.accelirate.com 等。
- 无任何占位/伪造域名。
- 全部 `web_search` 调用标记为 `offline=False`，`offline_fallback=0`。

> **结论：未发现来源伪造。**「绝不伪造 URL / 来源」这一设计不变量在真实运行中得到验证。

### 3.2 综合质量审计【人工核验】

**优点（真实、可追溯）**

- 每条 finding / insight / contradiction / tradeoff / recommendation 均携带 `evidence_ids` 与来源 agent。
- `claim_audit`（14 条）**逐数值核验**：例如 `kf_1` 判定 `partial (2/7 asserted numbers found)`，并明确列出**未找到**的数值（2025年、37亿、2030年、200亿）。
- 能识别 `unbound_citation`（证据未绑定来源 → 不可支撑来源级声明）。
- `source_gaps`（7 条，severity=high）主动把「无检索片段支撑的来源性断言」**降级为 `unverified_claim`**。
- `uncertainties` 诚实暴露真实短板：*「competitor_analyst 与 technology_analyst 仅返回部分工具结果，缺少完整竞品与定价对比」*。

**缺陷（见 §6 D3）**：Executive Summary 实质为空。

---

## 4. 真实 Scenario B 深度数据与失败根因【真实运行】

### 4.1 三次运行对比

| Run | 成功/失败/跳过 | retries | Web 调用 | Verdict |
|---|---|---|---|---|
| `run_72704df1` | 4 / 1 / 2 | 2 | **0** | **invalid_missing_real_web_search** |
| `run_fdf8616f` | 7 / 0 / 0 | 5 | 1 | valid_real_e2e |
| `run_c9f89856` | 5 / 1 / 1 | 3 | 3 | valid_real_e2e |

### 4.2 失败根因（run_72704df1）【真实运行】

逐 agent 状态：

| Agent | 状态 | 说明 |
|---|---|---|
| requirement_analyst | success | **已授权 web_search，但未调用** |
| system_architect | success | — |
| **database_engineer** | **failed ×3** | `structured output invalid [length_limit]: JSON decode failed: Unterminated string` |
| financial_analyst | success | — |
| technology_analyst | success | **已授权 web_search，但未调用** |
| test_engineer | skipped | upstream dependency failed |
| proposal_writer | skipped | upstream dependency failed |

**根因链条**：
1. Scenario B 为系统设计类任务（「设计面向 100 人企业的 AI 智能客服系统」），两个持有 `web_search` 授权的 agent 均**未发起检索**（LLM 决策，非授权缺陷——授权本身正确）。
2. `database_engineer` 输出撞上 token 上限 → `[length_limit]` → 同参数重试 3 次**全部重复同一错误** → 浪费 72.5s。
3. 两个下游 agent 因上游失败被级联跳过。

> 真实性判定机制**正确工作**：未静默放行，而是判为 `invalid_missing_real_web_search`。

### 4.3 `offline_mock` 诚信核查【人工核验】

复跑中出现 `offline_mock=3` / `offline_mock=1`，已逐条核验：

- `offline_mock` 全部来自**本地确定性工具**（`schema_validator` ×3、`calculator` ×1），**不是** `web_search` 回退。
- 所有 `web_search` 均为 `kind=web, offline=False`。
- `offline_fallback = 0`。

> **结论：无来源污染，`valid_real_e2e=True` 成立。**

---

## 5. Single-Agent Baseline 公平对照【真实运行】

| 指标 | 多 Agent（A，run_16d0d1a0） | 单 Agent Baseline（2 次） |
|---|---|---|
| Agent 数 | 8 | 1 |
| LLM 调用 | 17 | 2 – 3 |
| Web 检索 | 5 | 1 – 2 |
| Evidence | **60** | 3 |
| Sources | 17 | 5 – 10 |
| Findings | 14 | 不产出综合 findings |
| 耗时 | 162.8s | 15.7 – 24.4s |
| 成本 | **1.7620 USD** | 0.1005 – 0.2635 USD |

**结论**：多 Agent 在证据规模与综合产出上显著优于单 Agent（evidence 60 vs 3），代价是约 7–17 倍成本与 7–10 倍耗时。这是**真实对照数据**，补齐了此前遗留的 R3（Baseline 对照未执行）。

---

## 6. 本轮修复的缺陷与发现的缺陷

### 6.1 已修复（Phase 2）【实际测试】

| ID | 文件 | 问题 | 修复 |
|---|---|---|---|
| **F1** | `validation/counting_provider.py` L41–45、L60–63 | 文档字符串声称「provider 丢弃 `response.usage`，token 与成本不可观测，报 null」——**与代码实际行为矛盾**（`_meta_fields` 实际从 `last_response_meta` 捕获 usage 并聚合） | 改为如实描述：token 可观测，仅当真实调用未携带 usage 块时为 null |
| **F2** | `validation/single_agent_baseline.py` L361 | 控制台**硬编码**打印 `cost data: unavailable`，即使成本已算出（实测 0.100548 仍显示不可得） | 按 `cost_data_available` 分支打印真实值 |
| **F3** | `validation/single_agent_baseline.py` L263–265 | 原因串称「baseline runs have no real provider」——Baseline 现可真实运行，表述失真 | 修正为「无观测到 usage 时为 null」 |
| **F4** | `tests/test_realworld.py:401` | `_real_execution` 已返回 5 元组，仍按 4 元组解包 → `ValueError` | 改为 5 元组解包 |

### 6.2 新发现但未修复（列入发布阻塞/遗留）【人工核验】

| ID | 严重度 | 问题 | 证据 |
|---|---|---|---|
| **D1** | High | **`length_limit` 重试不自适应**：输出撞 token 上限后，3 次重试用相同参数必然重复失败 | B `run_72704df1`：database_engineer 3/3 同错，浪费 72.5s，级联跳过 2 agent |
| **D2** | Medium | **`supported_findings` 计数异常**：`counts.supported_findings=0` 且 `single_source_findings=0`，与 14 条 findings 并存，口径不一致 | A `synthesis.json` |
| **D3** | Medium | **Executive Summary 实质为空**：`summary_chars=0`，`assembler.py:338` 回退为一行统计句「Cross-agent synthesis over 8 artifacts and 60 evidence records.」 | A `synthesis.json` + `report.md` |
| **D4** | Low | Scenario B 中已授权 `web_search` 的 agent 可能不发起检索，导致整轮判为 invalid | B 3 次中 1 次 |

**D1 与 A 场景的对比（说明其可复现性）**：A 的 `competitor_analyst` 曾出现 `[truncated]` 错误，但**重试恢复成功**；B 的 `[length_limit]` 是**确定性失败**，重试无效。二者是不同失败模式。

---

## 7. 发布门禁判定【实际测试 / 人工核验】

| # | 门禁 | 结果 | 依据 |
|---|---|---|---|
| G1 | 全量离线回归通过 | ✅ PASS | **481 passed / 7 skipped**，exit=0 |
| G2 | 静态检查（ruff）全绿 | ✅ PASS | `All checks passed!` |
| G3 | 无密钥入库 | ✅ PASS | 已跟踪 142 文件 0 命中；382 个运行产物 0 命中；`.env` 被 `.gitignore:16` 忽略 |
| G4 | 真实执行闸门已恢复 `False` | ✅ PASS | `run_scenario.py:58` 已复原；依赖它的 2 个测试自动转绿 |
| G5 | R1 用量/成本可观测 | ✅ PASS | 真实数据闭环：逐调用 usage + 聚合 + `estimated_cost_usd` 计算成功 |
| G6 | 真实 Scenario A E2E | ✅ PASS | 本次 1/1 valid；累计 6/8 valid、2 degraded、0 invalid |
| G7 | 真实 Scenario B E2E | ❌ **FAIL** | **2/3 valid**，1 次 `invalid_missing_real_web_search`（对应 D1/D4） |
| G8 | 真实 Baseline 对照 | ✅ PASS | 2/2 valid，R3 遗留已消除 |
| G9 | 无来源伪造 | ✅ PASS | 17 来源全真实 URL，15 域名，offline_fallback=0 |
| G10 | 交付物语义质量 | ❌ **FAIL** | Executive Summary 为空（D3）；计数口径异常（D2） |
| G11 | 无未修复严重缺陷 | ❌ **FAIL** | D1（High）未修复 |

**门禁结果：8 通过 / 3 未通过 → NO-GO / DEFERRED**

---

## 8. 发布前必须完成的最小修复集

按优先级：

1. **D1（High，阻塞）**：`length_limit` 重试自适应——重试时提升 `max_tokens`，或注入「精简输出」约束，或在该失败模式下提前放弃而非重复 3 次。
2. **D3（Medium，用户可见）**：修复综合阶段 `summary` 未生成的问题，使 Executive Summary 具备实质内容；若确不生成，应从交付物移除该空节或明确标注为空。
3. **D2（Medium）**：修正/澄清 `supported_findings` 计数口径。
4. **D4（Low）**：评估是否要求 `SOURCE_REQUIRED_INTENTS` 命中的 agent 强制发起检索，或调整 Scenario B 的真实性判定口径。
5. **工程卫生**：建议将 `validation/runs/`（10.19 MB 可再生原始产物）加入 `.gitignore`，仅提交工具与报告（0.37 MB）。

完成 1–3 并复跑真实 Scenario B ≥1 次达到 valid，即可重新评估为 GO。

---

## 9. 未执行 / 受限事项声明

| 事项 | 状态 | 说明 |
|---|---|---|
| Git commit / tag / push / Release | **未执行** | 门禁未全过；且按用户既定规则，git 提交需显式确认，禁止自动提交 |
| 前端构建复验 | 【未验证】 | 上轮已通过 `vue-tsc` + `vite build`；本轮未改动前端，未重复构建 |
| 完整语义人工逐条复核（60 条 evidence） | 【部分】 | 已做来源域名/URL 全量核验与抽样内容审查，未逐条人工判读 |
| 更高并发/长时稳定性 | 【未验证】 | 仅完成限定预算内的 13 次真实运行 |

---

## 10. 证据可信度标注汇总

| 标签 | 本报告中用于 |
|---|---|
| 【真实运行】 | §1 余额探测、§2 运行清单、§3 A 数据、§4 B 数据、§5 Baseline 对照 |
| 【实际测试】 | §7 门禁 G1/G2/G4（481 passed、ruff、闸门测试） |
| 【静态审计】 | §6.1 F1–F4 代码缺陷定位 |
| 【人工核验】 | §3.1 来源域名核验、§4.3 offline_mock 逐条核查、§6.2 缺陷确认 |
| 【设计推断】 | §8 修复优先级排序 |
| 【未验证】 | §9 前端构建复验、高并发稳定性 |

---

## 11. 一句话总结

v0.6.0 在真实环境下跑通了多 Agent 主链路（A 场景 8 次真实运行 6 次完全有效、来源零伪造、成本可观测），但 **Scenario B 存在 1/3 概率的确定性失败（token 上限重试不自适应）**，且**最终交付物的执行摘要实质为空**——这两项使其尚不足以正式发布；建议完成 §8 的 1–3 项后再评估 GO。
