# AutoTeam v0.6.2 Candidate — 07 最终交付物质量评估

> 审计日期：2026-10-03｜**未新增真实 LLM / Web Search 调用**；也未新增 E2E / Baseline。
> 方法：对既有真实运行产物做**只读重算**（临时脚本已删除）。
> 诚实原则：**不做无依据的主观打分**；无标准答案的事项标记为「未测量」；结构检查不代替事实准确率。

---

## 1. 样本来源与类型（严格区分）

| 样本 | 运行 ID | 产物目录 | 类型 | 能否作为真实质量证据 |
|---|---|---|---|---|
| 多 Agent A | `run_f4c191c6` | `validation/runs/20261003T084253Z_A_real/run1_run_f4c191c6/` | **Real LLM（deepseek-chat）+ Real Web Search（9 次，0 回退）** | ✅ 可以 |
| 单 Agent Baseline | `baseline_084830666126` | `validation/runs/20261003T084839Z_A_real/` | Real LLM、0 工具 | △ 仅作结构对照 |

**样本量局限**：本次**仅有 1 次真实多 Agent 运行**可用于质量评估。
→ **不能得出跨任务稳定性或系统级准确率结论**（见 §14 判定）。

**明确未掺杂**：未将 Offline/Mock 样本混作真实证据。Mock 输出自带 `[mock]`/`[offline_mock]` 前缀且 claim_type 为 `unverified_claim`（`provider.py:225-236,320-329`）。

---

## 2. 抽查范围与分母

| 项目 | 数量 | 说明 |
|---|---|---|
| 抽查最终报告 | 1 | `report.md`（100,431 字符） |
| 抽查 Findings（事实性 Claim） | **10** | `synthesis.json["findings"]`，全部纳入（非抽样） |
| 抽查 Evidence | **67** | 全部纳入 |
| 抽查 Sources | **36** | 全部纳入 |
| 参与 claim 审计 | **10** | `synthesis_audit.json["claim_audit"]` |

---

## 3. 事实支持状态统计（本次重算）

`claim_audit[].status` 分布（分母 **10**）：

| 状态 | 数量 | 占比 | 含义 |
|---|---|---|---|
| SUPPORTED（`supported_by_citation`） | **2** | **20%** | 数值在引用片段中全部匹配（值+单位+年份） |
| PARTIALLY_SUPPORTED | **5** | 50% | 部分数值匹配 |
| CONTRADICTED | **0** | 0% | 未见明确冲突标记 |
| UNVERIFIED（含 `unsupported` 与 `no_numeric_claim`） | **3** | 30% | 1 条明确 unsupported + 2 条无数值断言未做数值核验 |
| NOT_APPLICABLE | **0** | 0% | 本次 10 条均含事实性主张 |

**关键量**：`numbers_supported=16`、`numbers_missing=16` → 抽查数值中 **50%** 未能在被引用片段中找到支撑。

### 3.1 ⚠️ 与系统 headline 指标的巨大差距（AT-AUDIT-004）

| 指标 | 系统 headline | 严格逐 claim 核验 |
|---|---|---|
| “supported” 数量 | **`finding_counts.supported = 9 / 10`（90%）** | **2 / 10（20%）** |

**根因（代码实证）**：
- `app/synthesis/synthesizer.py:636`：`SUPPORTED_LEVELS = frozenset({"source_text", "agent_consensus", "derived"})`
- `:637`：`UNSUPPORTED_REVIEW = frozenset({"unsupported"})`
- `:686-692`：只有 review == `unsupported` 才排除在 supported 之外

**后果**：
1. **多 Agent 一致**（`agent_consensus`，无独立来源）被计入 “supported”
2. **派生估算**（`derived`）被计入 “supported”
3. `partially_supported`（5 条）与 `not_checked`（4 条）**全部计入** supported

**这是本次审计发现的最影响「用户信任」的问题**：最终交付物的 headline 数字会让读者以为 90% 的结论已被引证支持，而严格引用核验仅 20%。

- **判定**：`AT-AUDIT-004 / HIGH / CONFIRMED`
- **修复建议**：将 `finding_counts.supported` 收敛为仅 `source_text` + review 明确非不支持；或重命名字段为 `backed_count`（有支撑层级）并**并列展示** `citation_verified`（引用核验）计数，两者不得混用。

### 3.2 ⚠️ 非数值 Claim 完全绕过核验（AT-AUDIT-011）

- `app/synthesis/claim_support.py:20-21` 自述：
  > Nothing here calls an LLM and nothing here scores prose quality; every value is derived from text with a fixed rule.
- `:318-319`：claim 中**若提取不到数值** → `status = "no_numeric_claim"`，**既不判 supported 也不判 unsupported**
- 实测：**2 / 10** claim 走此分支（20%）

**含义**：该项目的事实核验机制**仅覆盖数值型主张**（值 + 单位 + 年份匹配），**非数值事实陈述（定性主张、定性市场判断）完全不在引用核验范围内**。

- **判定**：`AT-AUDIT-011 / MEDIUM / CONFIRMED`（属机制边界 + 报告易用性风险）

---

## 4. 引用可靠性

| 指标 | 实测 | 判定 |
|---|---|---|
| Source URL 合法（http/https） | 36/36 | ✅ |
| Source 标题完整 | 36/36 | ✅ |
| Source 去重 | 36 唯一 URL = 36 唯一 ID | ✅ |
| 引用对应真实 Source 记录 | 22/67 Evidence 绑定 source；45 条明确无绑定并降级 | ✅ 可追溯 |
| 引用**仅提供背景**而非直接支撑 Claim | **存在**：8 条 `unbound_citations` | ⚠️ |
| Source 内容是否被抓取核验 | `access_status` **36/36 为空** | ⚠️ `AT-AUDIT-023` |

**结论**：引用**元数据完整、链接真实、无伪造**；但仅部分引用能真正承担 Claim 的支撑职责。

---

## 5. Evidence 支撑度（分层判定）

严格区分五个层级，避免混淆：

| 层级 | 本系统是否达到 | 依据 |
|---|---|---|
| ① 数据结构关联正确 | ✅ 达到 | 0 悬空引用 |
| ② 文本/词法匹配 | ✅ 达到 | `match_score` / `match_method` 字段（如 `no_snippet`、`0.4159`） |
| ③ 语义相关 | △ 部分 | 数值+单位+年份匹配属结构化约束，**非真正语义理解** |
| ④ 证据充分支持 | ⚠️ 部分 | 仅 2/10 完全匹配；5/10 部分 |
| ⑤ 独立来源核验 | ⚠️ 有限 | `support_profile` 区分了 `multi_source(4)` / `single_source(6)`，但 Source 内容未被再核验 |

**明示**：现有机制主要依赖**数值/单位/年份的规则匹配**，**不是深度语义验证**。不应将其描述为「已完成深度语义校验」。

---

## 6. 内容完整性

- 最终报告 100,431 字符，含 findings(10) / insights(4) / contradictions(4) / uncertainties(5) / tradeoffs(3) / recommendations(5)
- 任务目标（场景 A：AI Agent 中小企业市场研究 + 产品方案）有对应章节，artifact 8/8 均纳入
- **未发现关键章节缺失**；但 §7「完整性 vs 真正回答任务」的**语义判定需要人工复核**，本次不做主观评分。

---

## 7. 逻辑一致性

- 合成层提供了 `contradictions`（4 条，LLM 侧语义矛盾）与 `uncertainties`（5 条）并保留，**未被强行调和** ✅ 符合「不得为报告整洁替系统调和」的审计要求
- Cross-agent 数值漂移：本次**未做**逐数值跨 artifact 漂移对比（超出预算），标记**未充分验证**

---

## 8. 可追溯性

链路完整性（抽查 10 findings）：

| 环节 | 结果 |
|---|---|
| Final Report → Finding | ✅ 10 findings 全部进入 final |
| Finding → Evidence | ✅ **0 悬空**（10/10 至少有 1 个可解析 evidence_id） |
| Evidence → Source | ✅ 22/67 绑定；45 条显式为 `unverified_claim`（非丢失，而是未绑定） |
| Source → URL | ✅ 36/36 合法 |
| Artifact → Evidence | ✅ 0 悬空 |

**可追溯率**（完整追溯到 Artifact+Evidence+Source 的 claim / 适用 claim）：`2/10 = 20%`（因仅 2 条完全 backbone），其余为部分链路（有 Evidence 但 Source 未绑定或数值未匹配）。

---

## 9. 不确定性处理 ✅

- 8 个来源缺口被显式记录并降级，未伪装成功
- 45 条 `unverified_claim` 在数据中显式标注；`verified=True` 计数为 **0**（保守）
- 合成 summary 状态为 `derived_from_findings`（诚实地说明非模型自撰）
- report.md 中包含 `unverified` / `not_checked` / 局限相关关键词（本次 grep 确认存在）→ **不确定性被保留到最终交付物** ✅

---

## 10. 可测量质量指标（含分母，不编造）

| 指标 | 计算 | 结果 | 说明 |
|---|---|---|---|
| Claim 证据覆盖率 | 有≥1 有效关联 Evidence 的 Claim / 抽查 Claim 总数 10 | **10/10 = 100%** | 仅表示**有绑定**，不代表事实准确 |
| Source 关联完整率 | 有有效 Source 关联的 Evidence 22 / Evidence 总数 67 | **22/67 = 32.8%** | 表示关联完整性，不代表来源内容真实 |
| 数值支撑率 | numbers_supported 16 / (16+16) | **50%** | 抽查数值的一半未匹配 |
| 可追溯率（严格） | 完全畅追溯到 Evidence+Source 且数值匹配的 Claim / 10 | **2/10 = 20%** | — |
| **人工核验事实支持率** | — | **未测量** | ❗本次**未执行人工/权威资料核验**，故不报告该指标，**不得以 0% 或 100% 替代** |
| 任务要求覆盖率 | — | **未测量** | 原始任务要求拆分需人工定义，本次不臆造规则 |

---

## 11. 未测量项（明确列出）

- **事实准确率（truth accuracy）**：❗**未测量** —— 需要人工比对原始网页/权威来源，本次明确**未做**，且本次**不新增外部访问**。
- 跨任务质量稳定性：❗**未测量**（仅 1 次真实样本）
- Source 内容级有效性：❗**未测量**（`access_status` 全空，未核验原文）

---

## 12. 典型样例（引自产物，证明机制诚实）

- `evidence_id=ev_81fdb47424`：Claim 为市场金额，但 `source_id=""`、`claim_type=unverified_claim`、`match_score=0.4159`、`match_method=no_snippet`、`verified=False` → **系统未把该数字当已核验事实**，属正确降级。
- `finding_id=kf_market_size`：`review_status=unsupported`，`unsupported_parts` 显式列出无法逐项核验的数值（如 “2026年[year]”、“91.4-109.1亿[currency]”）→ 对不确定部分逐字标注。

---

## 13. 人工复核建议（优先级）

1. **【高】核对 `finding_counts.supported` 的对外展示口径**（AT-AUDIT-004）—— 若报告面向他人阅读，90% vs 20% 的误导风险最大。
2. **【中】人工核验 `kf_market_size` 等 5 条 PARTIALLY_SUPPORTED 的关键数值**是否真实存在于对应 Source 原文。
3. **【中】补充非数值 Claim 的核验手段说明**（AT-AUDIT-011），或至少在报告中显式声明「数值型主张已核验，定性主张未自动核验」。
4. **【低】对 Source 增加 `access_status` 回填**（AT-AUDIT-023），使 URL 是否真正被抓取可追溯。

---

## 14. 审慎结论

**已验证：**
- Artifact 与 Evidence 的结构关联完整性（0 悬空、0 伪造 URL）
- Source 元数据合法性（36/36）与去重
- 不确定性被诚实保留到最终交付物（8 缺口显式降级、0 误标 verified）

**部分验证：**
- 抽查 Claim 的数值支撑（10/10 有 Evidence 绑定；但仅 2/10 完全数值匹配、2/10 未做数值核验）
- Artifact 上下游衔接：结构关系成立，**语义使用未充分证明**

**尚未充分验证：**
- **全部最终报告的事实准确率（未测量，未经人工核验）**
- 大规模/多任务条件下的内容质量稳定性（仅 1 样本）
- 外部 Source 原文的实际支撑能力（`access_status` 为空，未核验）

> ⚠️ 最重要的一句：本系统**不能**基于现有数据证明「最终报告的事实准确性」。其 headline 的 `supported: 9/10` 属于**支撑层级计数**，而非「已被引用核验为正确」，二者相差 4.5 倍（90% vs 20%）。
