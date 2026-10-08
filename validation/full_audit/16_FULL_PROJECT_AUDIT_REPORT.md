# AutoTeam v0.6.2 Candidate — Full Project Audit Report

> 审计日期：2026-10-03
> 审计性质：**只读审计**。未修改业务代码、未修改测试、未修复问题、未重构、未新增功能、未改变配置。
> 未执行：git commit / push / tag / GitHub Release / 版本提升 / v0.7.0 开发。
> 未新增：真实 LLM 调用、真实 Web Search 调用、新的真实 E2E / Baseline。

---

## 1. Executive Summary

本次对 AutoTeam v0.6.2 候选（= v0.6.1 tag `f3f7330` + 未提交的 B1/B2/B3 修复）进行了跨 16 个模块的只读审计，结论为 **CONDITIONALLY_READY**。

- **发现 26 个问题**：CRITICAL 0、HIGH 4、MEDIUM 9、LOW 6、INFO 7。
- **18 个已确认（CONFIRMED）**，4 个设计限制，3 个测试缺口，1 个待验证。
- **无 Secret 泄漏、无崩溃级缺陷、无数据造假**；Evidence/Sources 结构完整性 100%（0 悬空、36/36 URL 合法，0 误标 verified）。
- **最主要的发现**是交付物 headline 指标的可信度问题：`finding_counts.supported = 9/10（90%）`，但严格逐 claim 引用核验仅 **2/10（20%）**——多 Agent 一致与派生估算被计入 “supported”。
- 另有 3 个 HIGH 属执行/隔离层面：并发上限从未启用、ResultStore 跨 run 污染、Replan 空操作却上报「已重规划」。
- 三者之所以能潜伏到发布候选，是因为**均无对应回归测试**——本次实际测试 519 passed 与 4 个 HIGH 并存，有力说明「测试通过 ≠ 系统可靠」。

---

## 2. Audit Scope

**已检查模块**：项目结构与 Git 状态、整体架构与 API 边界、Scheduler/AgentRuntime/Session/Retry-Replan、Task Understanding 与 Dynamic Team、ToolRegistry/LLM Provider/Web Search、Artifact/Evidence/Sources/Assembler、最终交付物质量、API/SSE/前端一致性、安全与隐私、测试质量、性能与稳定性、文档版本一致性、跨模块端到端、既有真实运行产物。

**未能充分覆盖（诚实披露）**：Task Understanding 与 Role Allocation 的 LLM 语义路径未逐行审查；前端组件未逐个阅读（Markdown 消毒、响应式布局待验证）；未审计 Git 历史 commit；根目录 60+ `*.log` 未逐文件细读；未做 SAST 深度扫描。

---

## 3. Project and Git Status

- 分支 `master`，HEAD `f3f73300f9327f36491ce736dc3374da07a49d63`（v0.6.1 tag），与 origin 同步。
- **未提交**：8 个文件（+116/−7）——B1 版本常量、B2 SSE 游标、B3 partial 贯通（含前端 4 处 + 3 项回归测试）。
- **未跟踪**：10 份 `validation/` 报告。
- v0.6.1 四处版本号一致（B1 已消除 health 过期暴露）。
- 仓库卫生：根目录散落 60+ `*.log` 调试文件。

---

## 4. Architecture Audit

分层清晰：**Core = `execute_task`（session.py:126）**，API 仅投影，编排约束（timeout/retry/offline 强制 mock，session.py:149-150）不可被旁路 ✅。**无循环导入** ✅。
主要问题：失败原因未暴露（008）、无取消端点（009）、Registry 无界增长（010）、单例不支持多 worker（013）、双 `assembler.py` 同名（016）、DTO 键耦合（017）。详见 02 号报告。

---

## 5. Core Execution Audit

调度**正确性无缺陷**（拓扑排序、依赖检测、SKIPPED 传播、无 double-schedule、无死锁）。
缺陷在于：**并发上限在三条核心路径均未启用**（001）、**ResultStore 跨 run 累积并污染 status_of**（002）、**Replan 为空操作却上报事件**（003）、重试退避占用 Semaphore（006）、partial 产物下游照用（007）。详见 03 号报告。

---

## 6. Dynamic Team Audit

`CAPABILITY_TOOLS` 为**唯一授权源**、缺省拒绝，Tool-free 能力有显式理由，`validate_allowed` 提供代码级二次校验 ✅；DAG 无环由代码强制 ✅；本次真实运行 8 agent 全部动态生成、无硬编码 ✅。
未充分覆盖：语义路径与团队规模泛化质量（024）。详见 04 号报告。

---

## 7. Tool and Provider Audit

Mock/Real 隔离良好（无 key 回退 Mock，provider.py:175-178）；**Provider 错误明确不含密钥/header/原文**（provider.py:33-45,95-97）✅；token 缺失报 None 不臆造 ✅；web_search 双模 + 诚实 fallback ✅。
问题：legacy 路径绕过权限（012）、`AUTOTEAM_LLM_MAX_TOKENS` 未配置致 length 自愈惰性（021）。详见 05 号报告。

---

## 8. Artifact / Evidence / Sources Audit

- Evidence 67：22 条绑定 source 且有 snippet，**45 条显式降级为 unverified_claim**，**verified=True 计数 0** ✅
- Sources 36：URL 36/36 合法、去重、标题完整 ✅
- Artifact 8/8 产出无空 ✅；来源缺口被诚实检测（8 个）✅
- 问题：headline 计数口径夸大（004）；partial 被当完整（007）；access_status 全空（023）
- 注：**Artifact 协作「结构关系已验证，语义使用尚未充分验证」**

---

## 9. Final Deliverable Quality

基于 1 次真实多 Agent 样本（8 agent / 67 evidence / 36 sources）重算：

| 指标 | 结果 |
|---|---|
| Claim 证据覆盖率 | 10/10 = 100%（仅表示有绑定） |
| Source 关联完整率 | 22/67 = 32.8% |
| 数值支撑率 | 16/32 = 50% |
| 严格引用核验 supported | **2/10 = 20%** |
| 系统 headline supported | **9/10 = 90%**（口径夸大 → 004） |
| 非数值 Claim 未核验 | **2/10 = 20%**（→ 011） |
| **人工核验事实支持率** | **未测量**（未做人工核验，不以 0%/100% 替代） |

**结论**：现有数据**不能证明**最终报告的事实准确性；系统**可以**证明结构完整性与不确定性保留诚实。详见 07 号报告。

---

## 10. API / SSE / Frontend Audit

8 个端点齐全；B1/B2/B3 回归均通过且有测试 ✅；前端 TypeScript 类型（`types.ts`）与后端 DTO 对齐良好（含 v0.6.6 新字段）✅。
问题：失败原因未暴露（008）、无取消（009）、Registry 增长（010）、弱类型（017/018）、**前端 0 单元测试（020）**。SSE 在 B2 后无确认缺陷。详见 08 号报告。

---

## 11. Security Audit

**未发现已知泄漏**：源码 55 处命中全为变量名/参数名，无 `sk-` 真实密钥字面量；`.env` 未入库且被 ignore（.gitignore:16-18）；Provider 错误不含密钥；前端不接触 Secret；测试中的密钥为假数据/反泄漏断言。
次生安全风险：跨 run 数据污染（002）、legacy 权限旁路（012）。
**不能断言零风险**：未审计 Git 历史、未细读全部日志、未做 SAST。详见 09 号报告。

---

## 12. Test Quality Audit（本次实际执行）

| 项 | 本次实际结果 |
|---|---|
| pytest | **519 passed**（16.44s），0 failed |
| ruff | **All checks passed!** |
| frontend build | **BUILD_EXIT=0**（`✓ built in 3.46s`） |

29 个测试文件，覆盖域较完整。**关键缺口**：并发上限、ResultStore 跨 run、Replan 误导事件、partial 下游消费、失败原因暴露——**均无针对性测试**（这正是 4 个 HIGH 潜伏的原因）。详见 10 号报告。

---

## 13. Performance and Stability

唯一真实样本：8 agents / 20 LLM / 9 检索 / 193.1s / ≈$2.416；Baseline 1 agent / 9.0s / ≈$0.046。
会在长稳劣化的点：Registry（010）与 ResultStore（002）均无淘汰；并发保护缺失（001）；无法优雅终止（009）。
**明确「尚未测量」**：Agent 数-时长曲线、并发 vs 失败率、内存曲线、大规模装配耗时、SSE 并发上限、成本规律。详见 11 号报告。

---

## 14. Documentation Consistency

**未发现确认的文档—代码矛盾 Bug**：四处版本号一致，入口描述与实际一致。
多 worker 不支持已在代码注释声明，但面向用户的 README 披露情况**未核实**；`.env.example` 与上表变量完整性**未逐行比对**。
建议补充披露：并发上限缺失、headline supported 口径、非数值 Claim 未核验。详见 12 号报告。

---

## 15. Cross-module Findings

6 个真实跨模块风险，共同特征是「每层单独看正确，但层间契约缺失」：
1. Scheduler 有并发能力但无人调用（001）
2. Replanner 结果被丢弃却仍上报（003）
3. partial 跨模块被稀释（007）
4. 严格核验与 headline 宽松口径混用（004）
5. ResultStore 无 run 隔离（002）
6. handle.error 在 Core→API 丢失（008）
已排除：重复执行、Team/计划不一致、Artifact 未使用、SSE 乱序等。详见 13 号报告。

---

## 16. Full Issue Inventory

完整清单见 `15_FULL_PROJECT_ISSUE_LIST.md`（26 项，编号 AT-AUDIT-001…026）。

| 严重程度 | 数量 |
|---|---|
| CRITICAL | 0 |
| HIGH | 4 |
| MEDIUM | 9 |
| LOW | 6 |
| INFO | 7 |

| 状态 | 数量 |
|---|---|
| CONFIRMED | 18 |
| DESIGN_LIMITATION | 4 |
| TEST_GAP | 3 |
| NEEDS_VALIDATION | 1 |

---

## 17. Release Risk Assessment

# ⚠️ CONDITIONALLY_READY

- **无 CRITICAL**；无安全阻断；无崩溃/必错交付阻断 → 不属 BLOCKED
- 存在 **4 项确认 HIGH** 与未验证风险 → 不属 AUDIT_COMPLETE_WITH_KNOWN_LIMITATIONS
- 证据足以判断关键风险（代码实证 + 真实样本 + 519 测试）→ 不属 INSUFFICIENT_EVIDENCE

**发布前强烈建议处理**：004（headline 口径，改动小收益最高）、002（数据隔离）、003（状态诚实）、001（并发保护）。
**若按现状发布的最低要求**：Release Notes 必须披露多 worker 限制、并发上限缺失、非数值 Claim 未核验、headline supported 的真实含义。详见 14 号报告。

---

## 18. Top 10 Issues

| 序 | 编号 | 严重度 | 标题 |
|---|---|---|---|
| 1 | AT-AUDIT-004 | HIGH | headline `supported` 口径夸大（90% vs 实际 20%） |
| 2 | AT-AUDIT-002 | HIGH | ResultStore 跨 run 累积 + 跨任务状态污染 |
| 3 | AT-AUDIT-001 | HIGH | 核心执行路径并发上限从未启用 |
| 4 | AT-AUDIT-003 | HIGH | Replan 空操作却上报「已重规划」 |
| 5 | AT-AUDIT-011 | MEDIUM | 非数值 Claim 完全绕过核验（20% Claim） |
| 6 | AT-AUDIT-007 | MEDIUM | partial Artifact 被下游当作完整产物 |
| 7 | AT-AUDIT-010 | MEDIUM | Run Registry 无界增长 |
| 8 | AT-AUDIT-009 | MEDIUM | 无取消端点/无全局超时 |
| 9 | AT-AUDIT-008 | MEDIUM | 运行失败原因未暴露 |
| 10 | AT-AUDIT-013 | MEDIUM | 单例 Registry 不支持多 worker（须披露） |

---

## 19. Recommended Fix Priority

**P0（安全与数据完整性）**：002（跨任务污染）
**P1（核心执行链路）**：001、003、005、006、007、012
**P2（最终生成质量）**：004、011、023（附带 22）
**P3（API/SSE/前端一致性）**：008、009、010、013、016、017、018
**P4（稳定性/测试/文档）**：014、015、019、020、021、024、025、026 + 文档披露

修复归因而非表现：多数问题的根因是「缺少跨层契约/默认值」，不是 Agent Engine 本身的错误。

---

## 20. Test and Verification Summary

| 验证 | 本次实际结果 |
|---|---|
| pytest | **519 passed**（0 failed），**REAL_EXECUTION_ENABLED=False**，无真实调用 |
| ruff | **All checks passed!** |
| frontend build | **BUILD_EXIT=0**（3.46s） |
| 真实运行 | **未新增**；复用既有 1 次真实多 Agent + 1 次 Baseline 做只读重算 |
| 证据完整性重算 | Evidence 67 / Sources 36 / Finding 10 / claim_audit 10（临时脚本已删除） |
| 安全扫描 | 源码 55 命中全为标识符；`.env` 未入库 → 0 确认泄漏 |
| GitHub / Git 写操作 | **未执行** |

---

## 21. Known Limitations

- 内存 Run Registry 重启丢历史（R8，设计）
- 多 worker 不支持（013）
- `AUTOTEAM_LLM_MAX_TOKENS` 未配置 → length 自愈惰性（021）
- 校验为语法级，语义空输出可判成功（022）
- Source 只存元数据，URL 有效 ≠ 内容核验（023）
- 单次真实样本，无法证明稳定性（024）

---

## 22. Audit Coverage and Unverified Areas

**已覆盖**：结构/架构/执行/工具/溯源/交付质量/API-SSE-前端/安全/测试/性能/文档/跨模块。

**未验证（列出）**：
1. Task Understanding / Role Allocation 的 LLM 语义正确性
2. 团队构建阶段是否有超时保护
3. 前端 Markdown 消毒 / 响应式布局 / 逐个组件审查
4. Git 历史 commit 是否曾含敏感信息
5. 根目录 60+ `*.log` 逐文件内容
6. `.env.example` 与环境变量完整性逐行比对
7. README 中测试数量等数字与本次实际的一致性
8. **事实准确率**（需人工/权威核验，本次明确未做）
9. 并发压测与长稳内存曲线

以上均未作为 Bug 报告，记录为验证缺口。

---

## 23. Final Conclusion

AutoTeam v0.6.2 候选**工程质量整体扎实**：核心约束不可旁路、负责人编排单一来源、工具权限代码级二次校验、Evidence/Sources 零悬空零伪造、不确定性保留诚实、Secret 隔离设计优良，pytest 519 / ruff / 前端构建三项门禁全绿。

但本次审计也确认了 **4 个 HIGH 缺陷**与若干可改进项，其中最值得优先处理的是 **headline 指标口径（AT-AUDIT-004）**——它不改变数据本身，却显著影响读者对交付物可信度的判断，属于「诚实呈现」层面的缺陷。

**发布状态：CONDITIONALLY_READY。** 建议在明确接受已知限制（或先行处理 001/002/003/004）后再行发布。本审计**未执行**任何发布动作。

> 最后提醒：本审计报告的范围是工程实施、执行链路、数据可靠性、安全性与交付质量的**可核实部分**；它**不能替代**对最终业务结论的人工事实验证。
