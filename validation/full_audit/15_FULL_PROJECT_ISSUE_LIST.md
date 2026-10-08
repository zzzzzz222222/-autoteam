# AutoTeam v0.6.2 Candidate — 15 全项目问题清单

> 审计日期：2026-10-03｜编号连续唯一：`AT-AUDIT-001` … `AT-AUDIT-026`
> 排序：CRITICAL → HIGH → MEDIUM → LOW → INFO

---

## 0. 统计总览

### 0.1 按严重程度

| 严重程度 | 数量 |
|---|---|
| CRITICAL | **0** |
| HIGH | **4** |
| MEDIUM | **9** |
| LOW | **6** |
| INFO | **7** |
| **合计** | **26** |

### 0.2 按状态

| 状态 | 数量 | 编号 |
|---|---|---|
| CONFIRMED | **18** | 001-012, 014-019 |
| DESIGN_LIMITATION | **4** | 013, 021, 022, 023 |
| TEST_GAP | **3** | 020, 024, 026 |
| NEEDS_VALIDATION | **1** | 025 |
| **合计** | **26** | — |

### 0.3 发布阻断

| 项 | 数量 |
|---|---|
| CRITICAL 阻断 | 0 |
| 建议在发布前处理 | 4（001, 002, 003, 004） |
| 可作为已知限制保留但须披露 | 6（009, 010, 011, 013, 021, 022, 023） |
| 不阻塞后续处理 | 16 |

---

## 1. CRITICAL

**无（0 项）。** 本次审计未发现 Secret 泄漏、崩溃级数据丢失、越权访问或必定错误交付的问题。

---

## 2. HIGH（4）

### AT-AUDIT-001
- **标题**：核心执行路径从未启用并发上限（Semaphore 未创建）
- **严重程度**：HIGH｜**状态**：CONFIRMED｜**模块**：Scheduler / Session / Orchestrator / DynamicTeam
- **相关文件**：`app/scheduler/scheduler.py:44`、`app/runtime/session.py:185-187`、`app/runtime/orchestrator.py:62-64`、`app/runtime/dynamic_team.py:113-115`
- **问题描述**：`AsyncDAGScheduler` 仅在 `max_concurrency` 为真值时创建 Semaphore；三条核心执行路径均未传该参数。
- **直接证据**：`semaphore = asyncio.Semaphore(self.max_concurrency) if self.max_concurrency else None`（scheduler.py:44）；`AsyncDAGScheduler(executor=runtime, retry_policy=..., timeout=timeout)`（session.py:185-187）无 max_concurrency
- **触发条件**：DAG 同层出现 ≥2 个 ready agent（动态团队普遍存在的多分支并行）
- **实际表现**：`asyncio.gather`（scheduler.py:72）无限制并发执行全部 ready agent
- **预期表现**：受 configured 并发上限保护
- **影响**：真实 LLM/检索场景瞬时打满速率限制与连接池，可能触发 429 与成本失控
- **根本原因**：调用点未填参数，Scheduler 机制存在但无人启用
- **修复建议**：为 `AsyncDAGScheduler.__init__` 设安全默认值，或在三个调用点显式传入
- **建议回归测试**：`test_core_paths_set_concurrency_cap`（断言三个调用点非 None）
- **当前是否阻止发布**：**建议处理**
- **验证限制**：未压测，未真实触发 429

---

### AT-AUDIT-002
- **标题**：单例 ResultStore 跨 run 无限累积 events + `status_of` 跨 run 状态污染
- **严重程度**：HIGH｜**状态**：CONFIRMED｜**模块**：Runtime / Orchestrator
- **相关文件**：`app/runtime/result_store.py:39-41`、`67-80`、`app/runtime/orchestrator.py:46-53`
- **问题描述**：`record()` 仅 append 不清理；`status_of` 遍历全部历史 events 取最后一条；orchestrator 单例跨 run 复用同一 store
- **直接证据**：`def record(self, event): with self._lock: self.events.append(event)`（result_store.py:39）；`self.store = store or ResultStore()`（orchestrator.py:46）
- **触发条件**：长时间进程中通过单例 orchestrator 处理 ≥2 次 run
- **实际表现**：events 单调增长；第二次 run 期间 `status_of("market_research")` 可能在当前 run 未写结果时返回**上一次 run** 的 done 状态
- **预期表现**：每次 run 隔离，不跨 run 读取
- **影响**：内存泄漏 + **跨任务数据污染**（数据隔离失效）
- **根本原因**：无 run_id 分区 / 无清理
- **修复建议**：`run()` 开始时清理 events 或按 run_id 分区；`status_of` 增加 run 过滤
- **建议回归测试**：`test_result_store_isolated_per_run`
- **当前是否阻止发布**：**建议处理**（涉及数据隔离）
- **验证限制**：FastAPI session 路径每次新建 ResultStore，不受影响；主要影响单例 orchestrator（Streamlit/长驻）

---

### AT-AUDIT-003
- **标题**：Replan 为空操作但仍向 trace 写入「已重规划」事件
- **严重程度**：HIGH｜**状态**：CONFIRMED｜**模块**：Scheduler / Session
- **相关文件**：`app/scheduler/replan.py:37-41`、`app/scheduler/scheduler.py:82-87`、`app/runtime/session.py:201-206`
- **问题描述**：Replanner 恒返回 `replanned=False`；scheduler 仅收集事件不应用；session 对每个失败 agent 记录 `AGENT_REPLANNED`
- **直接证据**：`return ReplanResult(replanned=False, reason="no viable recovery plan", ...)`（replan.py:37-41）；`trace.record("AGENT_REPLANNED", ...)`（session.py:201-206）
- **触发条件**：任一 agent 失败
- **实际表现**：trace/UI 显示「已重规划」，但拓扑从未变更、无自愈动作
- **预期表现**：未发生重规划时不应上报重规划事件
- **影响**：状态与 UI 不一致；用户误判系统已自愈
- **根本原因**：No-op 实现 + 事件语义未区分
- **修复建议**：真正应用 recovery.topology；或移除 “replanned” 语义，改为记录 “failure propagated”
- **建议回归测试**：`test_replan_noop_emits_no_replan_event`
- **当前是否阻止发布**：**建议处理**

---

### AT-AUDIT-004
- **标题**：`finding_counts.supported` 口径夸大，与严格引用核验差距 4.5 倍
- **严重程度**：HIGH｜**状态**：CONFIRMED｜**模块**：Synthesis / Final Deliverable
- **相关文件**：`app/synthesis/synthesizer.py:636-637`、`686-692`、`640-701`
- **问题描述**：`supported` 的判定把 `agent_consensus`（多 agent 一致，无独立来源）与 `derived`（派生估算）都算作 supported，且仅 `review_status == "unsupported"` 才排除
- **直接证据**：`SUPPORTED_LEVELS = frozenset({"source_text", "agent_consensus", "derived"})`（synthesizer.py:636）；`UNSUPPORTED_REVIEW = frozenset({"unsupported"})`（:637）
- **量化证据（本次重算真实产物）**：headline `finding_counts.supported = 9/10（90%）`；而逐 claim 严格核验（claim_audit）`supported_by_citation = 2/10（20%）`、partially 5、unsupported 1、no_numeric_claim 2
- **触发条件**：任何含多 agent 一致或派生结论的合成结果
- **实际表现**：最终报告呈现「90% 结论已获支撑」
- **预期表现**：区分为「有支撑层级」与「引用核验通过」两个不同指标
- **影响**：**用户显著高估交付物可信度**；属诚实性/呈现正确性风险（非数据造假）
- **根本原因**：headline 指标语义与直觉含义不匹配
- **修复建议**：拆分 `supported`（改名 `backed_count`）与新增 `citation_verified`；两者并列展示，不得混用
- **建议回归测试**：`test_finding_counts_excludes_consensus_and_derived`
- **当前是否阻止发布**：**强烈建议处理**
- **验证限制**：事实准确率本身未做人工核验（未测量）

---

## 3. MEDIUM（9）

### AT-AUDIT-005
- **标题**：重规划拓扑即使生成也绝不应用（latent bug）
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：Scheduler
- **相关文件**：`app/scheduler/scheduler.py:86`
- **问题描述**：`if recovery.replanned and recovery.topology is not None: TopologyValidator().validate(recovery.topology)` —— 只校验不赋值，`recovery.topology` 被丢弃
- **直接证据**：scheduler.py:86 无赋值语句；`:87` 后仍用旧 topology
- **触发条件**：未来 Replanner 返回 `replanned=True`（当前不会）
- **影响**：潜在静默失效，未来启用真 replan 时会无效
- **修复建议**：重建 predecessors/statuses 并重进入循环，或删除该分支
- **建议回归测试**：`test_replan_topology_is_applied`
- **阻止发布**：否（latent）

---

### AT-AUDIT-006
- **标题**：重试退避 `asyncio.sleep` 期间仍占用 Semaphore
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：Scheduler
- **相关文件**：`app/scheduler/scheduler.py:104-152`（`async with semaphore` 在 attempt 循环外层，sleep 在 :152）
- **影响**：有效并发下降；小并发上限 + 长退避时吞吐显著拖累
- **修复建议**：将 `async with` 缩小到单次 execute，退避 sleep 移到锁外
- **建议回归测试**：`test_retry_backoff_releases_semaphore`
- **阻止发布**：否

---

### AT-AUDIT-007
- **标题**：partial Artifact 被下游当作完整产物消费
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：AgentRuntime / Context / Session
- **相关文件**：`app/runtime/agent_runtime.py:678-693`、`app/runtime/session.py:271-279`、`app/runtime/context.py:67-90`
- **问题描述**：预算/迭代耗尽产生 `metadata["partial"]`，但调度器状态仍为 SUCCESS，`assemble_agent_context` 不识别 partial
- **影响**：残缺产物注入下游 → 「success without valid deliverable」向下游传播
- **触发条件**：agent 预算或迭代耗尽
- **修复建议**：`AgentArtifact` 增 `is_partial` 字段，context/assembler 显式标注或隔离
- **建议回归测试**：`test_partial_artifact_not_injected_as_complete`
- **阻止发布**：否（真实样本未触发，由测试保障）→ **AT-AUDIT-024**

---

### AT-AUDIT-008
- **标题**：运行失败原因未向客户端暴露
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：API / RunRegistry
- **相关文件**：`app/api/runs.py:229-232`、`142-157`、`249-261`、`app/api/routes.py`
- **问题描述**：失败原因存于 `handle.error` / `session.error`，但 `snapshot()` 返回 dict 无 error 字段，无端点输出
- **影响**：客户端无法区分「崩溃」与「无最终产物」；排障困难
- **修复建议**：`TaskSnapshot`（`app/api/models.py:29`）增 `error: str | None` 并回填
- **建议回归测试**：`test_snapshot_exposes_failure_reason`
- **阻止发布**：否

---

### AT-AUDIT-009
- **标题**：无取消/终止端点，且无全局运行预算
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：API / Scheduler
- **相关文件**：`app/api/routes.py:46-209`（无 cancel/delete/stop）、`app/api/runs.py:223`（timeout=600 为单 agent 上限）、`app/scheduler/scheduler.py:163-166`
- **问题描述**：grep 确认 app/api 下无 cancel/terminate/stop/delete/shutdown；超时仅作用于单次 execute
- **影响**：长尾运行无法优雅终止；只能重启进程
- **修复建议**：`RunHandle.cancel()` + `DELETE /api/tasks/{id}`；引入全局预算 + 单 agent 上限双层
- **阻止发布**：否，但须披露

---

### AT-AUDIT-010
- **标题**：Run Registry 无界增长，无淘汰机制
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：RunRegistry
- **相关文件**：`app/api/runs.py:185-202`（`self._runs` 仅追加）、`242-246`（list 线性遍历）
- **影响**：长稳内存泄漏；list 响应越来越长
- **修复建议**：最大保留数/TTL/LRU 淘汰
- **阻止发布**：否，须披露

---

### AT-AUDIT-011
- **标题**：非数值 Claim 完全绕过引用/支撑核验
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：Synthesis / claim_support
- **相关文件**：`app/synthesis/claim_support.py:318-319`（`no_numeric_claim` 分支）、`:20-21`（自述不做语义评分）
- **量化证据**：真实样本 10 条 claim 中 **2 条（20%）** 走该分支，既未判 supported 也未判 unsupported
- **影响**：定性事实主张不被自动核验；若对外宣称「全部结论已核验」则失真
- **修复建议**：显式区分数值/非数值 claim 的核验状态；或在报告中声明非数值主张未自动核验
- **阻止发布**：否，**但必须披露**

---

### AT-AUDIT-012
- **标题**：legacy orchestrator 路径 `_run_tools` 绕过 `agent.tools` 权限校验
- **严重程度**：MEDIUM｜**状态**：CONFIRMED｜**模块**：AgentRuntime（legacy）
- **相关文件**：`app/runtime/agent_runtime.py:880-893`（不经 `validate_allowed`）
- **对比**：real-LLM 路径有 `validate_allowed`（`agent_runtime.py:620-644`）
- **影响**：旧 orchestrator 路径工具权限边界失效（session/FastAPI 路径不受影响）
- **修复建议**：统一经 `tool_registry.validate_allowed`
- **阻止发布**：否（仅旧路径）

---

### AT-AUDIT-013
- **标题**：模块级单例 Registry 不支持多 worker
- **严重程度**：MEDIUM｜**状态**：DESIGN_LIMITATION｜**模块**：API / RunRegistry
- **相关文件**：`app/api/routes.py:27`、`app/api/main.py:5`（已声明 single process）
- **影响**：`uvicorn --workers N` 时跨 worker 查询返回 404
- **修复建议**：文档显式声明禁止多 worker / 需粘性会话，或外置状态
- **阻止发布**：否，**必须写进部署说明**

---

## 4. LOW（6）

| 编号 | 标题 | 状态 | 文件 | 说明 / 建议 |
|---|---|---|---|---|
| AT-AUDIT-014 | 调度器定义 `RUNNING` 但从不赋值 | CONFIRMED | `app/scheduler/models.py:15`、`scheduler.py:71` | 执行中 agent 内部状态停留在 READY，无法区分「已就绪」与「运行中」；建议进入执行前置 RUNNING |
| AT-AUDIT-015 | `ReplanEvent.previous_topology/new_topology` 永远为 None | CONFIRMED | `app/scheduler/replan.py:14-18` | 死字段；建议移除或填充 |
| AT-AUDIT-016 | 两个同名 `assembler.py` | CONFIRMED | `app/runtime/assembler.py:31-249`、`app/synthesis/assembler.py:14,322` | 职责不同、数据类单一来源，但同名易误改；建议抽数据类到独立模块 |
| AT-AUDIT-017 | API DTO 与 snapshot 字典键耦合无编译期保证 | CONFIRMED | `app/api/models.py:77-94`、`app/api/runs.py:85-141` | `final.get("findings") or []` 键漂移会静默落默认值；建议显式映射/Pydantic 构造 |
| AT-AUDIT-018 | `TeamResponse.agents` / `explanation.agents` 弱类型 | CONFIRMED | `app/api/models.py:46-53`、`frontend/src/types.ts:169` | `list[dict[str,Any]]` / `unknown[]`；建议提取强类型 `AgentTeamMember` |
| AT-AUDIT-019 | `ExecutionStatus` 与 `SessionStatus` 语义重叠 | CONFIRMED | `app/scheduler/models.py:12-18`、`app/runtime/session.py:33-38` | 两枚举均有 pending/running/success/failed，靠 `.value` 字符串约定衔接；建议文档说明职责或派生 |

---

## 5. INFO（7）

| 编号 | 标题 | 状态 | 文件/位置 | 说明 / 建议 |
|---|---|---|---|---|
| AT-AUDIT-020 | 前端 0 单元测试 | TEST_GAP | `frontend/src`（`*.test.ts`/`*.spec.ts` = 0） | partial 渲染、SSE 处理、空/异常分支无自动化保障；建议引入 Vitest |
| AT-AUDIT-021 | `AUTOTEAM_LLM_MAX_TOKENS` 未设置 → length 自愈惰性 | DESIGN_LIMITATION | `app/llm/provider.py:111-115,185-192` | 无 max_tokens 可增长，D1 自愈真实环境从未触发（仅离线 12 项测试）；建议文档推荐配置 |
| AT-AUDIT-022 | 产物校验为语法级（非空即通过） | DESIGN_LIMITATION | `app/runtime/validation.py:21-44` | 语义空/无意义输出仍可 SUCCESS；可接受为设计取舍，建议补轻量启发式 |
| AT-AUDIT-023 | Source `access_status` 全空，URL 有效 ≠ 内容核验 | DESIGN_LIMITATION | 运行产物 `sources.json`（36/36 空） | 无法证明 source 被真正抓取；建议回填 access_status |
| AT-AUDIT-024 | 真实运行样本不足 | TEST_GAP | `validation/runs/` | 仅 1 次真实多 Agent；partial/failure 真实路径无样本；不能得出稳定性结论 |
| AT-AUDIT-025 | `ExecutionTrace.record` 无锁 | NEEDS_VALIDATION | `app/runtime/events.py:56-73` | 当前单事件循环写、结束读，实践安全；若未来后台写+UI 读则理论竞态 |
| AT-AUDIT-026 | 无性能/并发压测 | TEST_GAP | `tests/` | 并发、长稳、大规模 evidence 均无测量；多数性能指标标记「尚未测量」 |

---

## 6. 未发现 / 不适用（明确标注 0）

| 类别 | 数量 |
|---|---|
| CRITICAL 问题 | **0** |
| 确认 Secret 泄漏 | **0** |
| 源码硬编码真实密钥 | **0** |
| 伪造 URL / 伪造 Source | **0** |
| Evidence / Artifact / Finding 悬空引用 | **0** |
| 无限重试 | **0** |
| DAG 环路导致不可执行 | **0** |
| Mock 冒充真实运行的可证实路径 | **0** |

---

## 7. 与相邻重复项的处理说明

- `AT-AUDIT-003`（事件误导）与 `AT-AUDIT-005`（拓扑不应用）源于同一 Replanner 实现，但**表现与修复点不同**（一个是 trace 语义，一个是调度器赋值），故分开记录并在各自描述中交叉引用，避免重复计数。
- `AT-AUDIT-002`（events 累积）与 `AT-AUDIT-010`（Registry 累积）是**两个不同对象**的内存泄漏，根因不同，分开记录。
