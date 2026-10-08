# AutoTeam v0.6.1 → v0.6.2 — 问题清单（Step 1 核对）

> 本文件为 v0.6.2 验收第一步：基于**当前工作区实际代码与文件**重新核对，不默认历史报告结论成立。
> 核对基准：`master @ f3f7330`（v0.6.1 tag）。核对时间：2026-10-03。

## 0. 当前工作区事实（已重新核对）

| 检查项 | 实际状态（本会话复核） |
|---|---|
| 分支 / HEAD / tag | `master` / `f3f73300…` / `v0.6.1` 指向 HEAD ✅ |
| 未提交差异 | 8 个文件修改（B1/B2/B3 修复 + 回归测试）+ 2 个未跟踪报告 |
| B1 修复行 | `app/api/routes.py:29` `VERSION = "0.6.1"` ✅ 在位 |
| B2 修复行 | `routes.py:198` `last = last + len(events)` ✅ 在位 |
| B3 修复行 | `routes.py:99` / `runs.py:77` / `session.py:100` partial 字段 ✅ 在位 |
| B3 前端修复 | `types.ts` / `i18n/index.ts` / `stores/team.ts` / `AgentStatus.vue` ✅ 在位 |
| 回归测试 | `tests/test_api.py:32` test_health、`210` test_sse_stream_no_event_loss_on_concurrent_append、`265` test_partial_agent_exposed_in_snapshot ✅ 在位 |
| `REAL_EXECUTION_ENABLED` | `validation/run_scenario.py:64 = False` ✅ 安全态恢复 |
| 历史 D1–D4 / SOURCE_REQUIRED_INTENTS | `_complete_with_length_recovery`(agent_runtime.py:327)、`compute_finding_counts`(synthesizer.py:640)、`derive_executive_summary`(synthesizer.py:715)、`_sourcing_requirement_note`(agent_runtime.py:229)、`SOURCE_REQUIRED_INTENTS`(source_policy.py:39) ✅ 全部在位 |
| 真实运行产物 | `validation/runs/20261003T084253Z_A_real/`（多 Agent）、`20261003T084839Z_A_real/`（Baseline）✅ 可复用 |

---

## 1. 问题状态总表

| 编号 | 归属重点 | 描述 | 复核结论 | 标记 |
|---|---|---|---|---|
| **B1** | 重点 4（版本一致性） | `/api/health` 报告 `0.6.0` ≠ 应用 `0.6.1`；测试反向钉死旧值 | 代码行已改为 `0.6.1`，测试改为 `== app.version`；`grep` 确认在位 | **FIXED** |
| **B2** | 重点 4/5（SSE 一致性 / 断连） | `stream_events` 游标用 `event_count()` 重读，并发追加时漏事件 | 游标改为 `last + len(events)`；回归测试构造竞态并断言全投递 | **FIXED** |
| **B3** | 重点 1（SUCCESS vs 交付） | 部分交付 Agent 的 per-agent 状态 / 前端误标 success | `session.partial_agent_ids` + `runs.py` 快照 + `routes.py` + 前端 4 处一致暴露 `partial`；回归测试覆盖 | **FIXED** |
| 重点 2 | Evidence / Sources / Claim | 悬空引用 / 错误关联 / 事实核验不足 | 基于真实运行产物做结构完整性扫描：Source 36（URL 全部 http 合法）、Evidence 67（45 未绑定→`unverified_claim`，22 绑定且 **0 悬空**）、Artifact→Evidence **0 悬空**、Finding→Evidence **0 悬空**。结构完整 | **NOT_REPRODUCED（无缺陷）** |
| 重点 3 | 真实 LLM / Web Search degraded/invalid/failed | 可复现的代码原因 | 真实运行 `is_real_llm=True`、`is_real_web_search=True`（9 次真实检索，0 回退）、`blocked_llm_calls=0`、`verdict=valid_real_e2e`。唯一 invalid 为 D4 设计取舍（授权 agent 决策不检索），非代码缺陷 | **NO_CODE_BUG_REPRODUCED** |
| 重点 5 | 超时 / 断连 / 异常退出 / 重复执行 | 状态错误 | 断连由独立守护线程处理，重连索引 0 幂等重放；每运行隔离 session、registry 按 uuid 键；真实运行 2 次重试均恢复、无状态破坏。唯一真实缺陷即 B2（已修） | **NOT_REPRODUCED（无缺陷，除已修 B2）** |
| 重点 6 | Run Registry | 内存态以外的实际 Bug | 内存态为 R8 设计限制；`create/start/get/list` 逻辑正确，未发现额外 Bug | **KNOWN_LIMITATION（R8）** |
| 重点 7 | 历史修复有效性 | D1/D2/D3/D4、`SOURCE_REQUIRED_INTENTS` 在 v0.6.1 仍有效 | `grep` 确认 5 处标记全部在位；真实运行实测 `summary_status=derived_from_findings`（D3 生效）、`SOURCE_REQUIRED_INTENTS` 驱动的 8 个来源缺口被诚实检测 | **FIXED（历史修复仍有效）** |

---

## 2. 状态语义说明

- **FIXED**：有代码改动 + 回归测试支持，且本会话重新核对代码确认修复行在位。
- **NOT_REPRODUCED**：当前代码走查 / 真实运行产物核对未发现该问题（重点 2/5 结构完整性 0 悬空；重点 5 无状态错误）。
- **NO_CODE_BUG_REPRODUCED**：真实运行中出现的 invalid 属既定设计取舍（D4），非新增代码缺陷。
- **KNOWN_LIMITATION**：R8 内存 Registry 重启丢历史，为设计边界，不在本次修复范围。
- **OPEN / NEEDS_REVIEW**：本轮未发现需要开启的 OPEN 项；详见各专项审计报告中的「观察项」。

---

## 3. 观察项（非缺陷，记录供后续）

- **O1（报告口径）**：合成结果同时输出 `finding_counts`（supported:9 / unsupported:0）与逐 finding `review_status`（partially_supported:5 / unsupported:1 / not_checked:4），两轴口径不同，读者可能误读。非代码 Bug，建议在报告中显式区分「有证据绑定」与「语义核验状态」。详见 `REPORT_QUALITY_AUDIT.md`、`EVIDENCE_PROVENANCE_AUDIT.md`。
- **O2（D1 惰性分支）**：`AUTOTEAM_LLM_MAX_TOKENS` 未设置，真实环境从未触发 length_limit；D1 仅有离线 12 项测试证据。属稳健性缺口，非缺陷。
- **O3（真实检索覆盖）**：本次真实运行出现 8 个来源缺口（4 high / 4 medium），主因是部分 claim 无法绑定到检索片段而被降级为 `unverified_claim`。这是诚实溯源机制在生效，不是失败，但提示真实检索召回仍有提升空间（属 D4 语义范畴）。

---

## 4. 结论

v0.6.1 发布后暴露的 3 个可复现代码 Bug（B1/B2/B3）**均已修复且本会话重新核对确认**。7 个重点排查中，重点 2/3/5/6/7 未发现新增代码缺陷；R8 为既定设计限制。历史修复 D1–D4 与 `SOURCE_REQUIRED_INTENTS` 在 v0.6.1 中**仍然有效**。

v0.6.2 候选的代码修复范围 = B1 + B2 + B3（均已就位、已测试、已真实验证）。
