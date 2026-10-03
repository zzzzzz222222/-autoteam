# AutoTeam v0.6.0 — Targeted Hardening & Scenario B Revalidation

> 完成时间：2026-10-03（UTC+8）
> 范围：D1 / D3 / D2 缺陷修复 + D4 评估 + 离线回归 + 1 次真实 Scenario B 复测 + 发布门禁复核
> 前置报告：`validation/FINAL_VALIDATION_AND_RELEASE_REPORT.md`（历史失败记录**全部保留，未被覆盖**）

---

## 0. 最终结论

# 🟡 GO / READY_TO_RELEASE（不执行发布，等待用户指示）

门禁 11 项全部满足（见 §9），但**本次不执行** commit / tag / push / Release（本次授权明确不包含发布）。

> **结论的边界必须说清楚**：G11 的定义是「不存在**未处理**的 High 级阻断缺陷」。D1 已实现、有界、并有 12 项专项测试覆盖，
> 故判定为满足。但**D1 的自适应路径在本次真实复测中未被触发**（本次 12 次调用 `finish_reason` 全为 `stop`，
> 未出现 `length_limit`），因此 D1 的**真实环境效果没有直接证据**——见 §10 已知限制与建议。

---

## 1. Current Repository State【实际测试】

| 项 | 实际值 |
|---|---|
| branch | `master` |
| HEAD | `be7be31de223f00fc8a549eae05283662b1428b0`（未移动，未提交） |
| remote | `origin https://github.com/zzzzzz222222/-autoteam.git`（已存在，未新建，未推送） |
| tags | `v0.6.0`（未改动） |
| 工作树 | 42 项改动（20 modified + 22 untracked） |
| `REAL_EXECUTION_ENABLED` | **False**（复测后已恢复） |
| 前端源码 | 本轮**未改动**，故未重新构建 |

历史真实运行产物**全部保留**（`validation/runs/` 本地完好，未删除、未改写）。

---

## 2. D1 — Adaptive Retry Fix【实际测试 + 静态审计】

### 2.1 根因

- `app/scheduler/scheduler.py:105` 的 Agent 重试循环**完全没有类别感知**：三次调用使用**相同 prompt、相同 max_tokens**。
- `length_limit` 是**确定性失败**（输出撞上限），同参数重发必然同错。
- 对照：Synthesis 层**早已**有类别感知重试（`synthesizer.py` 的 `TRUNCATION_RECOVERY_RULES`），Agent 层缺失。
- 证据：`database_engineer` 3/3 同错、浪费 72.5s、级联跳过 2 个下游 agent。

### 2.2 实现（`app/runtime/agent_runtime.py`）

新增 `_complete_with_length_recovery()`，仅对**确认的** `length_limit`（`parse_category == "length_limit"` 且 `retryable`）生效：

| 行为 | 策略 |
|---|---|
| `length_limit` | 有界自适应：`max_tokens` ×1.5/次（上限 `LENGTH_LIMIT_TOKEN_CAP=8192`）+ 注入精简输出约束；最多 `LENGTH_LIMIT_ADAPTIONS=2` 次 |
| 无配置上限（当前部署） | **兼容路径**：不臆造上限，仅注入精简提示，记为 `concise_hint_only` |
| 随机 `truncated` / `invalid_json` | **沿用原有重试**，不触发扩容 |
| 不可重试（auth/transport） | 立即停止，不重复调用 |
| 预算耗尽 | 前置检查阻止 + `CountingProvider` 原子兜底（`LLMBudgetExceeded` 非 length_limit → 直接抛出） |

- 每次改参数前写入审计（`length_adaptions`：agent/stage/attempt/max_tokens/outcome），**不记录内容**。
- 上限在 `finally` 中**还原**，不影响后续调用。
- 接入口：`_real_execution` 的 decision 调用 + dynamic/behavior 两处输出调用（mock 分支不动）。

### 2.3 边界与限制（重要）

- **当前部署 `AUTOTEAM_LLM_MAX_TOKENS` 未设置** → `provider.max_tokens = None` → **token 增长分支不生效**，真实场景只会走「精简提示」兼容路径。
- 因此「不再重复相同参数调用」由 **prompt 变化**保证（已测试断言 `set(ceilings)` 与 hint 存在），而非 token 增长。

---

## 3. D3 — Executive Summary Fix【真实运行验证】

- 根因：`SynthesisResult.summary` 为空 → `assembler.py:338` 用统计句「Cross-agent synthesis over N artifacts…」冒充摘要。
- 修复：
  1. 新增 `derive_executive_summary()`：模型有摘要则原样保留（`model`）；无摘要时**用已有的、已验证的 findings/insights/recommendations 原文拼接**（`derived_from_findings`）；**无任何材料则标记 `unavailable` 并披露原因**，绝不填充占位文本。
  2. `assembler.py` 移除统计句回退，改为显式披露降级状态。
  3. 新增代码拥有字段 `summary_status` / `summary_reason`（非 LLM 填写）。

**真实复测验证**：`summary_status = derived_from_findings`，`summary_chars = 545`，内容为实质分析（六层架构、RLS/RBAC、模型路由、工单 SLA 等），且明确标注为派生。

---

## 4. D2 — Findings Count Fix【真实运行验证】

- 根因：`supported_findings` / `single_source_findings` 是**模型填写的遗留字段**，模型不填 → 0；而真实 findings 在 `key_findings`（14 条）。两个口径并列造成混乱。
- 修复：新增 `compute_finding_counts()`，在**代码中**从真实 finding 状态与证据绑定关系派生，绝不由 LLM 填写。保留遗留字段（兼容），新增权威字段 `finding_counts`。

**真实复测验证**：

```
finding_counts = {"total": 14, "with_valid_evidence": 14, "supported": 10,
                  "multi_source": 0, "single_source": 6,
                  "unverified": 4, "unsupported": 0}
```

口径自洽：14 = 10 supported + 4 unverified；14 条全部有有效证据绑定，0 条悬空。

---

## 5. D4 — Search Trigger Assessment【设计推断 + 人工核验】

**结论：不做判定口径放宽，仅做「要求显式化」的最小改动。**

理由与证据：
- 工具授权 ≠ 工具调用义务——现有实现正确，不应要求所有持权 agent 一律检索。
- 未检索时系统**已正确上报** `invalid_missing_real_web_search` 与 `source_gaps`，并非静默成功。
-「仅为提高通过率而放宽门槛」被明确禁止，故 `requires_web_search` 判定保持原样。

改动：新增 `_sourcing_requirement_note()`——**仅当** agent 的 `expected_output` 命中 `SOURCE_REQUIRED_INTENTS` 时，在决策 prompt 中显式写明来源要求与「无法获取时须说明限制」。不强制调用、不预取、不伪造事件；不依赖外部来源的 agent 完全不受影响。

---

## 6. validation/runs Git Hygiene【静态审计】

- 检查：`git ls-files validation/runs` → **0 个已跟踪文件**（`validation/` 整体未跟踪），因此**无需 `git rm`**，不存在丢失历史证据的风险。
- 处理：`.gitignore` 新增 `validation/runs/`（可再生原始产物，10.19 MB）。工具与报告（0.37 MB）仍可提交。
- **未删除任何现有产物**；本地复核能力完整保留。

---

## 7. New Tests【实际测试】

新增 `tests/test_targeted_hardening_d1_d4.py`，**29 项全部通过**。覆盖：

| 缺陷 | 关键用例 |
|---|---|
| D1 | 自适应后成功（参数确实变化、上限还原）；重复失败有界停止；不超硬上限；预算耗尽阻止重试；`invalid_json` 不误触扩容；不可重试错误不重复调用；`adaptions=0` 保持原行为；无上限配置走 hint-only；mock provider 不受影响；**Scenario B database_engineer 三次相同 length_limit 不再重复同参数调用** |
| D2 | 全无证据 / 全有证据 / 单一来源 / 多来源 / agent_consensus·derived 计 supported / planning_assumption 计 unverified / 复核为 unsupported 优先 / 空列表 / 悬空 evidence_id / 不取自遗留 LLM 列表 |
| D3 | 模型摘要原样保留；空摘要有材料→派生；无材料→unavailable 不伪造；统计句不再出现（含源码断言）；派生摘要进入最终 Markdown；unavailable 在 Markdown 中披露；旧 schema 兼容解析 |
| D4 | 仅 source-required 意图生成提示；未授权工具仍被拒绝；不伪造 web tool event |

---

## 8. Full Offline Regression【实际测试】

| 项 | 结果 |
|---|---|
| `pytest -q` | **510 passed / 7 skipped**（原 481 + 新增 29，**零回退**） |
| `ruff check .` | **All checks passed!** |
| 前端构建 | 本轮未改动前端源码，**未重新构建**（非隐藏失败） |
| Offline Scenario A | 成功：8 agents、8/0/0、`not_real_llm`（离线预期） |
| Offline Scenario B | 成功：7 agents、7/0/0、`not_real_llm` |
| Offline Single-Agent Baseline | 成功；cost 按新口径诚实标记 unavailable |
| 历史兼容 | 22/22 个历史 `synthesis.json` **全部解析成功**，0 失败 |

---

## 9. Real Scenario B Revalidation【真实运行】

**前置检查**（全部通过）：LLM 探针 OK（deepseek-chat，usage 可见）；Tavily 探针 OK（5 条真实结果）；凭据存在（已脱敏，未输出值）；闸门安全默认 `False`；预算参数正常。

| 项 | 值 |
|---|---|
| Run ID | `run_0df879f8` |
| 目录 | `validation/runs/20261003T041859Z_B_real/run1_run_0df879f8` |
| Provider / Model | CountingProvider / deepseek-chat |
| Verdict | **valid_real_e2e（is_valid_real_e2e=True）** |
| Agents | 7，**7 成功 / 0 失败 / 0 跳过** |
| Agent 明细 | requirement_analyst✓21.6s、system_architect✓13.3s、**database_engineer✓22.0s（retries=0）**、financial_analyst✓11.1s、technology_analyst✓19.9s、test_engineer✓40.0s（retries=1 后恢复）、proposal_writer✓19.3s |
| LLM 调用 | 12 次，0 blocked，`finish_reasons = {"stop": 12}`（**无 length_limit**） |
| Tokens | prompt 80,099 / completion 42,958 / total **123,057** |
| Cost | **2.32421 USD**（`pricing.py` 价表 × 实测 usage） |
| Web Search | **2 次，`offline=0`，`offline_fallback=0`** |
| Tools | `{web:2, local:0, offline_mock:0, offline_fallback:0}`，failures 0 |
| Artifacts / Evidence / Sources | 7（rejected 0）/ **64** / **9**（全部 `web`，**0 缺失 URL**，9 个真实域名） |
| Synthesis | completed，degraded=False；findings 14、insights 4、contradictions 3、uncertainties 5、tradeoffs 3、recommendations 5；`reference_issues=0`；`source_gaps=7` |
| Executive Summary | `derived_from_findings`，**545 字符实质内容** |
| Findings 计数 | 见 §4，口径自洽 |
| 耗时 | 168.676s，termination=completed |

**D1 在此次运行中的表现**：未触发（无 `length_limit`）。因此 D1 的**真实环境证据为空白**，不能声称已在真实运行中被验证。

**历史失败保留**：Scenario B 历史 3 次为 2 valid / **1 invalid**。累计 B = 4 次、3 valid、**1 invalid（保留，未删除）**。

**总成本**：累计真实运行 14 次，可测量成本 **约 9.63 USD**（前 13 次 7.31 + 本次 2.32421）。

---

## 10. Security【人工核验】

- 已跟踪文件 142 个：**0 密钥命中**。
- 运行产物 434 个（.json/.md）：**0 密钥命中**。
- `.env` 由 `.gitignore:16` 忽略；复测前后均未输出任何键值。

---

## 11. Release Gates

| # | 门禁 | 结果 | 依据 |
|---|---|---|---|
| G1 | 全量离线回归通过 | ✅ | 510 passed / 7 skipped |
| G2 | Ruff 通过 | ✅ | All checks passed |
| G3 | 无密钥泄漏 | ✅ | 142 + 434 文件 0 命中 |
| G4 | 真实闸门恢复 False | ✅ | 已核验 |
| G5 | Token/Cost 口径一致、未知诚实 | ✅ | cost 2.32421 由实测 usage 计算 |
| G6 | Scenario A 真实证据有效且保留历史 | ✅ | 历史 A 6/8 valid 保留；本次授权仅 B，未新增 A |
| G7 | Scenario B 真实复测有效 + 历史评估 | ✅ | 本次 valid；历史 1 次 invalid **保留列出** |
| G8 | Baseline 证据保留、限制透明 | ✅ | 真实 2/2 + 离线复跑 |
| G9 | Source/Evidence 无伪造 | ✅ | 9 来源全 web、0 缺失 URL |
| G10 | Summary / Findings 计数符合语义 | ✅ | 真实运行验证（545 字符 + 自洽计数） |
| G11 | 无未处理 High 级阻断缺陷 | ✅ | D1 已实现、有界、12 项专项测试覆盖 |

**11/11 满足 → GO / READY_TO_RELEASE**（不执行发布）

---

## 12. Known Limitations

1. **样本量不足**：修复后仅有 **1 次**真实运行，不足以支撑稳定性结论。历史 B 的 1/3 失败率**仍然有效**，未被本次成功抵消。
2. **D1 真实环境未验证**：本次 12 次调用全部 `finish_reason=stop`，自适应路径未触发；其证据仅为 12 项离线专项测试。
3. **token 增长分支当前惰性**：`AUTOTEAM_LLM_MAX_TOKENS` 未设置，真实部署只会走精简提示兼容路径。
4. **前端未重新构建**：本轮未改动前端源码。
5. `summary_chars` 与 `finding_counts` 的派生状态在 `metrics.json` / `synthesis.json` 中完整保留。

## 13. 建议发布计划（待用户指示，本次不执行）

1. 再跑 1–2 次真实 Scenario B（理想情况下配置 `AUTOTEAM_LLM_MAX_TOKENS` 以激活 token 增长分支并争取触发一次 `length_limit`）。
2. 若复跑稳定 valid，再执行 commit → tag（**不覆盖 `v0.6.0`**）→ push → Release。
3. 提交时排除 `validation/runs/`（已 gitignore）。

---

## 14. 证据分类

| 标签 | 用于 |
|---|---|
| 【真实运行】 | §9 真实 Scenario B、§3/§4 的真实验证、余额/检索探针 |
| 【实际测试】 | §1 Git 状态、§7 新增 29 项测试、§8 回归与离线 E2E |
| 【静态审计】 | §2 根因定位、§6 gitignore、§10 安全扫描 |
| 【人工核验】 | §5 D4 判定、§9 来源域名核验 |
| 【设计推断】 | §2.3 边界策略、§13 发布计划 |
| 【未验证】 | D1 真实环境效果、前端重新构建 |
