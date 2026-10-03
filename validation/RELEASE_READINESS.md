# AutoTeam v0.6.0 — 发布就绪度 (RELEASE READINESS)

> 决策：🔴 NO-GO（本次不发布）。触发发布的前置门槛见 §3。
> 分类：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】【人工核验】

---

## 1. 当前就绪度快照【实际测试 + 静态审计】

| 维度 | 状态 | 证据 |
|------|------|------|
| 离线回归（pytest/ruff/前端 build） | ✅ 达标 | 481 passed/7 skipped；ruff 全绿；`vue-tsc`+`vite build` 通过 |
| 离线 E2E（Scenario A/B） | ✅ 达标 | 8/8、7/7 成功，verdict 诚实 |
| 离线 Baseline | ✅ 达标 | 跑通，cost unavailable 诚实 |
| 可靠性（超时/预算/Retry/Replan/SSE） | ✅ 达标 | 可靠性子集 116 passed/1 skipped |
| 安全 / 密钥 | ✅ 达标 | `.env` gitignored；源码密钥扫描 0 命中 |
| 语义守卫 | ✅ 达标（静态） | 见 SEMANTIC_QUALITY_AUDIT |
| R2/R5 诚实判定修复 | ✅ 达标 | 已完成 + 测试 |
| 真实运行证据（R1/R2/R3/稳定性） | 🔴 缺失 | BLOCKED（见 §2） |
| 文档（六份） | ✅ 完成 | 本目录 |

---

## 2. 发布阻断根因【设计推断 + BLOCKED】

1. **硬闸门不变量**：`validation/run_scenario.py:58` `REAL_EXECUTION_ENABLED = False` 必须在发布前保持 False（项目不变量 + 任务"验收前不发布"）。本次**未开启、不开启**。
2. **凭据不可达**：底层 LLM API 余额耗尽（HTTP 402，见工作记忆）；`.env` 虽配置了 Provider/模型/BaseURL/WebSearch，但真实运行会中止，无法产出有效真实证据。
3. **验收未达**：22 项验收中真实运行相关项 BLOCKED，整体为"部分达成"，未满足"验收后再发布"。

---

## 3. 触发发布的前置门槛（解锁后）

维护者须依次确认：

- [ ] **A. 明确授权开启真实运行**：将 `REAL_EXECUTION_ENABLED` 置 `True`（仅受控、短时），或经授权在受控脚本内临时开启并事后复原（闸门须恢复 `False`）。
- [ ] **B. 凭据可用**：配置有效 LLM API Key 与 Web Search Key，且余额充足（非 HTTP 402/401）。
- [ ] **C. 真实 Scenario 跑通**：`run_scenario.py --scenario A --mode real --confirm-real` 与 `--scenario B` 均产出 `valid_real_e2e=True`、真实 `token_usage` 被捕获、来源缺口诚实披露。
- [ ] **D. 真实 Baseline 对照**：`single_agent_baseline.py --mode real` 产出真实 `estimated_cost_usd`（非空），与多 Agent 成本对照成立。
- [ ] **E. 稳定性复跑**：真实 Scenario 至少 2–3 次复跑，结果稳定、无静默 mock 回退。
- [ ] **F. 真实语义人工核验**：真实产物来源缺口/数值支撑经人工抽检无误。
- [ ] **G. 闸门复原**：真实运行后 `REAL_EXECUTION_ENABLED` 恢复 `False`。

满足 A–G 后，回到 FINAL_VALIDATION_MATRIX 把真实项由 🔒 改为 ✅，再执行发布。

---

## 4. 发布执行步骤（满足 §3 后）

1. `git status` 复核仅预期文件改动；`.env` 不被纳入。
2. 提交（显式确认，绝不自动 commit）：`git add` 指定文件 → `git commit -m "..."`。
3. 打标签：`git tag v0.6.0`（若尚未打；当前 tag 已存在 `v0.6.0 = f651f73`，需确认是否快进/重建）。
4. 推送：`git push origin master --tags`（remote `origin` 已存在：`https://github.com/zzzzzz222222/-autoteam.git`）。
5. GitHub Release：基于 `v0.6.0` 发布，附 RELEASE_NOTES。
6. 更新 README 的版本/状态段。

---

## 5. 本次未执行项（明确记录）

- `git commit/tag/push/GitHub Release`：**本次不执行**（NO-GO）。工作树保留 19 modified + 17 untracked 供维护者复核。
- 真实运行：**本次不执行**（BLOCKED）。

---

## 6. 残留风险（发布前仍需关注）

- R8 `RunRegistry` 重启丢历史（设计限制，待 v0.7+ 轻量持久化）。
- 真实 API 成本依赖 `pricing.py` 价表覆盖；未知模型仍报 null。
- 真实检索非必然（LLM 决策），已由 `tool_selector` 保证授权衔接，不强制搜索。

---

## 7. 【更新 2026-10-03】真实运行已执行 — 结论仍为 NO-GO

> 本文档 §5 原记「真实运行：本次不执行（BLOCKED）」，该状态**已被解除**：
> 实测证实 DeepSeek 与 Tavily 均可用（此前 HTTP 402 断言为误判），真实执行闸门在授权窗口内开启并完成验证，
> 随后已于 Phase 8 恢复为 `False`。

**真实运行规模【真实运行】**：13 次唯一真实运行（Scenario A ×8、Scenario B ×3、Single-Agent Baseline ×2），
可测量总成本 **7.31 USD**。结果：A 6/8 valid（2 degraded、0 invalid）、B **2/3 valid**、Baseline 2/2 valid。

**结论仍为 🔴 NO-GO / DEFERRED**，原因是新增三项未达标门禁：

| 门禁 | 结果 | 阻塞项 |
|---|---|---|
| 真实 Scenario B E2E | ❌ | 2/3 valid；`length_limit` 重试不自适应（High） |
| 交付物语义质量 | ❌ | Executive Summary 实质为空（`summary_chars=0`）；`supported_findings` 计数口径异常 |
| 无未修复严重缺陷 | ❌ | 上述重试缺陷未修复 |

**本轮修复的失真报告缺陷**：`counting_provider.py` 过期文档字符串（声称 usage 被丢弃 → 实为可观测）、
`single_agent_baseline.py` 硬编码打印 `cost data: unavailable`（成本已算出仍显示不可得）+ 配套原因串、
`tests/test_realworld.py` 5 元组解包。

**回归与安全性【实际测试 / 人工核验】**：全量离线 481 passed / 7 skipped；ruff 全绿；
已跟踪 142 文件与 382 个运行产物**均无密钥命中**，`.env` 已被忽略。

**最小修复集**：见 `validation/FINAL_VALIDATION_AND_RELEASE_REPORT.md` §8（D1 优先）。
完成 D1–D3 并复跑真实 Scenario B 达标后，方可重新评估为 GO。

**完整报告**：`validation/FINAL_VALIDATION_AND_RELEASE_REPORT.md`（本文档的判定以其为准）。

---

## 8. 【更新 2026-10-03 二次】D1/D3/D2 修复 + 真实 Scenario B 复测 → GO / READY_TO_RELEASE

> 本文档 §7 的结论（NO-GO，因 G7/G10/G11 未达标）**已被本轮修复取代**。
> 历史失败记录（B 场景 1/3 invalid、Executive Summary 为空、length_limit 重试不自适应）**全部保留，未删除**。

**修复**：D1 有界自适应重试（仅对确认 `length_limit` 生效，含预算/上限边界与兼容路径）；
D3 Executive Summary 不再为空（模型摘要 / 由 findings 派生 / 明确 unavailable 三态披露，统计句已移除）；
D2 新增代码派生 `finding_counts`（14 = 10 supported + 4 unverified，口径自洽）；
D4 判定门槛**未放宽**，仅在 source-required 意图时显式化检索要求。

**验证**：新增 29 项专项测试全通过；全量离线 **510 passed / 7 skipped**（零回退）；ruff 全绿；
离线 A/B/Baseline 均成功；22/22 历史 `synthesis.json` 兼容解析；142 已跟踪 + 434 产物文件 0 密钥命中。

**真实复测（1 次 Scenario B，`run_0df879f8`）**：`valid_real_e2e=True`，7/0/0 全部成功，
2 次真实检索，12 次 LLM 调用，123,057 tokens，**2.32421 USD**，64 evidence / 9 sources（0 缺失 URL），
Executive Summary 545 字符（`derived_from_findings`）。

**门禁 11/11 满足 → 🟡 GO / READY_TO_RELEASE**（本次**未执行**发布，等待用户指示）。

**必须同时阅读的限制**：修复后真实样本仅 1 次（不足以支撑稳定性结论，历史 1/3 失败率仍有效）；
D1 自适应路径**在本次真实运行中未触发**（12/12 `finish_reason=stop`），其证据为离线测试；
`AUTOTEAM_LLM_MAX_TOKENS` 未设置 → token 增长分支当前惰性，仅精简提示路径生效。

**完整报告**：`validation/TARGETED_HARDENING_REVALIDATION.md`（本文档判定以其为准）。
