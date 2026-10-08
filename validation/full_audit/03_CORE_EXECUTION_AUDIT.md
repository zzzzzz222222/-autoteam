# AutoTeam v0.6.2 Candidate — 03 核心执行审计（Scheduler / AgentRuntime / Session / Retry-Replan）

> 审计日期：2026-10-03｜只读审计，未修改任何代码。
> 审查文件：`app/scheduler/*`（scheduler/executor/retry/replan/models）、`app/runtime/*`（session/agent_runtime/events/artifacts/context/assembler/result_store/orchestrator/decomposer/dependency/validation）

---

## 1. Scheduler 审计

### 1.1 ⚠️ 高严重度：并发上限在核心路径从未启用

**AT-AUDIT-001 / HIGH / CONFIRMED**

- **代码**：
  - `app/scheduler/scheduler.py:44`：`semaphore = asyncio.Semaphore(self.max_concurrency) if self.max_concurrency else None`
  - `app/runtime/session.py:185-187`：`AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=2), timeout=timeout)` —— **未传 `max_concurrency`**
  - `app/runtime/orchestrator.py:62-64`：`AsyncDAGScheduler(executor=self.runtime, retry_policy=RetryPolicy(max_retries=1))` —— **未传**
  - `app/runtime/dynamic_team.py:113-115`：`AsyncDAGScheduler(executor=runtime, retry_policy=RetryPolicy(max_retries=1))` —— **未传**
  - 仅 `app/demo/service.py:161-163` 与 `app/evaluation/evaluator.py:37` 传入该值
- **实际表现**：三条核心执行路径的 `semaphore=None`，`ready` 中所有 agent 经 `asyncio.gather`（`scheduler.py:72`）**无限制并发**执行。
- **触发条件**：DAG 同层存在多个 ready agent（v0.6.x 动态团队普遍存在多分支并行，例如本次真实运行 8 agent / 4 层）。
- **影响**：真实 LLM + 工具场景下瞬时打满速率限制/连接池/内存；Semaphore 容错设计形同虚设。
- **建议**：为 `AsyncDAGScheduler.__init__` 的 `max_concurrency` 设置安全默认值，或在三条核心调用点显式传入。

### 1.2 DAG 拓扑排序与状态机（正确性核查）

| 检查项 | 结论 | 证据 |
|---|---|---|
| 调度方式 | level-synchronous 波次调度（每波选出父节点全 SUCCESS 的 PENDING agent 并发） | `scheduler.py:46-88` |
| 无环保证 | `is_directed_acyclic_graph` 校验 + `compute_parallel_layers` | `app/topology/validator.py:29,37` |
| 依赖完成检测 | `all(statuses[parent] is SUCCESS)` | `scheduler.py:62-64` |
| SKIPPED 传播 | `any(parent in {FAILED, SKIPPED})` → 后代 SKIPPED | `scheduler.py:48-57` |
| agent 重复调度 | **未发现**：状态转终态后不再入队；`_execute_one` 吞掉所有异常不抛出 | `scheduler.py:105,107-161` |
| 任务永不结束 | **未发现**：`ready` 为空但仍有 PENDING → `raise RuntimeError` | `scheduler.py:66-69` |
| Semaphore 释放 | `async with semaphore` 保证异常/取消时释放 | `scheduler.py:115` |

**结论**：调度**正确性本身无缺陷**；缺陷在于并发保护未启用（1.1）。

### 1.3 其他 Scheduler 发现

| 编号 | 发现 | 严重度 | 状态 | 证据 |
|---|---|---|---|---|
| AT-AUDIT-006 | 重试期间持有 Semaphore（含 `asyncio.sleep(retry_delay)` 退避），有效并发被拖累 | MEDIUM | CONFIRMED | `scheduler.py:104-152`（`async with` 在 `for attempt` 外层，`:115` 包住 execute，`:152` sleep 同块内） |
| AT-AUDIT-014 | 定义 `RUNNING` 状态但从不赋值；执行中 agent 内部状态停留在 `READY`，无法区分「已就绪」与「运行中」 | LOW | CONFIRMED | `app/scheduler/models.py:15`、`scheduler.py:71` |
| — | `retry_delay=0.0` 时跳过 sleep → 默认紧耦合立即重试（受 `max_retries` 封顶，不无限） | INFO | CONFIRMED | `scheduler.py:151`、`app/scheduler/retry.py:6` |
| AT-AUDIT-025 | 若未来引入取消，`READY/PENDING` 残留会导致 double-schedule | INFO | NEEDS_VALIDATION | `scheduler.py:46-80` |

---

## 2. AgentRuntime 审计

### 2.1 工具调用权限

- `_real_execution` 执行前二次 `validate_allowed`（`app/runtime/agent_runtime.py:620-644`），未授权工具被拒绝并要求模型重试，不执行外部调用 ✅
- **例外**：legacy 路径 `agent_runtime.py:880-893` 的 `_run_tools(behavior.tools, ...)` 直接执行，**未校验 `agent.tools`**（旧 orchestrator 路径，research/competitor/technology agent 固定预取 `["web_search"]`）
- **判定**：`AT-AUDIT-012 / MEDIUM / CONFIRMED`（仅影响 orchestrator 旧路径；session 路径因 `output_schema=AgentDeliverable` 走 artifact 分支，不受影响）

### 2.2 LLM 输出解析 / 空输出 / 错误写入

| 检查 | 结果 | 证据 |
|---|---|---|
| LLM 格式错误 | 非 length-limit 解析错误被重抛 → schedule 判 FAILED → 触发重试 ✅ | `agent_runtime.py:340-342` |
| length_limit 自适应恢复 | `_complete_with_length_recovery`（`:327-370`）有界自适应（×1.5、上限 8192、≤2 次、finally 还原） ✅ | `agent_runtime.py:327-370` |
| **上述分支在真实环境惰性** | `AUTOTEAM_LLM_MAX_TOKENS` 未设置 → `max_tokens=None` → 请求**不发** max_tokens（`provider.py:111-115`），故 never 触发 | `app/llm/provider.py:111-115,185-192` → `AT-AUDIT-021 / DESIGN_LIMITATION` |
| 空输出当成功 | **否**：`validate_artifact` 拒绝空 content；模型无 deliverable 且无工具结果时 `raise ProviderError` ✅ | `validation.py:26-27`、`agent_runtime.py:677` |
| 错误写入 artifact | **否**：异常在 `_build_artifact` 之前抛出 ✅ | `agent_runtime.py:903-920` |
| 超时后仍执行 | **否**：`asyncio.wait_for` 取消协程后转 `TimeoutError` ✅ | `scheduler.py:136,163-166` |
| 上游 context 注入 | 按传递闭包上游过滤，仅注入 SUCCESS 的 AgentArtifact ✅ | `app/runtime/context.py:63-90` |

### 2.3 ⚠️ partial 产物被下游当作完整产物消费（AT-AUDIT-007）

- **位置**：`agent_runtime.py:678-693`（预算耗尽 → `metadata["partial"]`）、`session.py:271-279`（仅 session 层降级 verdict，**调度器状态仍为 SUCCESS**）、`context.py:67-90`（`assemble_agent_context` 不识别 `partial`）
- **实际表现**：partial artifact 在调度器视角是 SUCCESS，会作为普通上游产物注入下游 agent；下游无从知晓上游残缺 → 「success-without-valid-deliverable」向下游传播。
- **判定**：**MEDIUM / CONFIRMED**
- **建议**：`AgentArtifact` 增加 `is_partial` 字段，`assemble_agent_context` / assembler 显式标注或隔离。
- **注**：本次真实运行 `partial_agent_ids` 为空，未触发该分支；其正确性由离线回归测试保障（真实环境样本不足 → `AT-AUDIT-024`）。

---

## 3. Replan / Retry 审计

### 3.1 ⚠️ 高严重度：Replan 为空操作，却写入「已重规划」事件（AT-AUDIT-003）

- **位置**：
  - `app/scheduler/replan.py:37-41`：永远返回 `ReplanResult(replanned=False, reason="no viable recovery plan", ...)`
  - `app/scheduler/scheduler.py:82-87`：取到 `recovery` 后仅 `self.replan_events.append(...)`；即使 `replanned=True` 也**只 validate 不使用**
  - `app/runtime/session.py:201-206`：对每个失败 agent 记录 `AGENT_REPLANNED` trace 事件
- **实际表现**：UI / trace 显示「replanned」，但实质上未发生任何重新规划或拓扑变更。
- **影响**：Retry/Replan 状态与 UI 显示不一致（用户误以为系统已自愈）。
- **判定**：**HIGH / CONFIRMED**
- **建议**：要么真正应用 `recovery.topology` 重建 predecessors/statuses 并重调度；要么移除 “replanned” 语义，诚实记录 “failure propagated / downstream skipped”。

### 3.2 重规划拓扑即使生成也绝不应用（AT-AUDIT-005 / MEDIUM / CONFIRMED）

- `scheduler.py:86`：`if recovery.replanned and recovery.topology is not None: TopologyValidator().validate(recovery.topology)` —— **无赋值，`recovery.topology` 被丢弃**
- 当前 Replanner 永不返回 `replanned=True`，属 **latent bug**：一旦未来启用真正 replan，会静默失效。

### 3.3 Retry 边界 ✅

- `_execute_one` 循环 `range(1, max_retries+2)`，由 `max_retries` 硬性封顶，**无无限重试** ✅（`scheduler.py:105`）
- 重试状态正确回写 `agent_results`（`status=success`、`attempt=2`），本次真实运行 2 次重试（competitor_analyst / data_analyst）均恢复正常 ✅
- 未发现「重试恢复成功却被标记失败」或「重试失败却误报成功」的证据。

---

## 4. Session / ResultStore 审计

### 4.1 ⚠️ 高严重度：Orchestrator 共享 ResultStore 跨 run 累积 + 状态污染（AT-AUDIT-002）

- **位置**：
  - `app/runtime/result_store.py:39-41`：`record()` 仅 `self.events.append(event)`，**永不清理**
  - `app/runtime/orchestrator.py:46-53`：单例 `self.store = store or ResultStore()` 跨 run 复用；`AgentRuntime(store=self.store)` 每次 agent 都 `store.record(RunEvent(...))`
  - `app/runtime/result_store.py:67-80`：`status_of(agent_id)` 遍历**全部**历史 events，取最后一个
- **影响**：
  1. 内存单调增长（每个 run 的 start/done/error 只增不删）
  2. **跨任务数据污染**：确定性 agent id（如 `market_researcher`）在历史 run 重复出现，`status_of` 在当前 run 尚未写入结果时可能返回**上一次 run** 的 `done` 状态 → Live View 显示旧 run 状态
- **范围限定**：FastAPI session 路径每次 `execute_task` 新建 `ResultStore()`（`session.py:177`），随 session 被 GC，**不跨 run 累积**；该问题主要影响单例 Orchestrator（Streamlit / 长驻实例）。
- **判定**：**HIGH / CONFIRMED**
- **建议**：每次 `run()` 开始清理 events 或按 `run_id` 分区；`status_of` 增加 run 过滤。

### 4.2 Session 生命周期与清理

- `TaskExecutionSession` 为纯内存对象，文档明确声明 `session.py:1-7`："Purely an in-memory object; persistence can be added later" → 进程重启丢状态（**已知设计限制**）
- **全局 grep 确认**：仓库内不存在 `cancel / clear / reset / evict / purge / shutdown`，也不存在 session/run 注册表结构 → **无任何 session/run 清理或淘汰机制**
- `ExecutionTrace`（`events.py:49-73`）append-only、无容量上限（per-session，不全局累积）
- 后台 Registry 无界增长见 `AT-AUDIT-010`（架构报告）

### 4.3 并发与重复执行 ✅

- 每次运行拥有隔离 session；Run Registry 按 uuid 键（`RunHandle`/`RunRegistry`）
- 未发现重复执行导致重复产物 / 跨 Task 数据污染的实际缺陷（除上述 orchestrator 单例路径）
- `ExecutionTrace.record` **无锁**（`events.py:56-73`，`event_id` 用 `len(self.events)+1` 非原子）：当前 session 路径单事件循环写、结束后读，**实践安全**；若未来改为后台写 + UI 读则存在理论竞态 → `AT-AUDIT-025 / NEEDS_VALIDATION`

---

## 5. 已核查且确认干净的核心执行项

- ✅ DAG 拓扑排序与依赖检测正确
- ✅ 无 agent 永久挂起 / 无 double-schedule / 无任务永不结束
- ✅ Semaphore 释放正确（当 semaphore 存在时）
- ✅ SKIPPED 传播语义正确、无误用
- ✅ 工具权限在 real-LLM 路径由 `validate_allowed` 强制
- ✅ 空/错误输出不会被写入 artifact 或判成功
- ✅ 超时后协程被取消，无残留执行
- ✅ Retry 有界、状态回写正确、无限重试不存在
- ✅ 上游 context 按传递闭包正确注入，无错配上游

---

## 6. 核心执行问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-001 | HIGH | 核心执行路径未启用并发上限 | CONFIRMED |
| AT-AUDIT-002 | HIGH | ResultStore events 跨 run 累积 + status_of 跨 run 污染 | CONFIRMED |
| AT-AUDIT-003 | HIGH | Replan 为空操作但写入「已重规划」事件 | CONFIRMED |
| AT-AUDIT-005 | MEDIUM | 重规划拓扑即使生成也绝不应用 | CONFIRMED |
| AT-AUDIT-006 | MEDIUM | 重试退避期间持有 Semaphore | CONFIRMED |
| AT-AUDIT-007 | MEDIUM | partial 产物被下游当作完整产物消费 | CONFIRMED |
| AT-AUDIT-012 | MEDIUM | legacy `_run_tools` 绕过工具权限 | CONFIRMED |
| AT-AUDIT-014 | LOW | RUNNING 状态定义但从不赋值 | CONFIRMED |
| AT-AUDIT-015 | LOW | `ReplanEvent.previous/new_topology` 永远为 None | CONFIRMED |
| AT-AUDIT-021 | INFO | `AUTOTEAM_LLM_MAX_TOKENS` 未设置，D1 恢复分支惰性 | DESIGN_LIMITATION |
| AT-AUDIT-025 | INFO | ExecutionTrace 无锁（理论竞态） | NEEDS_VALIDATION |
