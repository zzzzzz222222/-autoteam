# AT-AUDIT-001 修复报告：max_concurrency 并发限制未贯通

- **项目**：AutoTeam v0.6.2（工作区基线 `v0.6.1` tag `f3f7330` + 未提交的 B1/B2/B3 与 AT-AUDIT-002 修复）
- **问题编号**：AT-AUDIT-001（严重级别 HIGH）
- **修复日期**：2026-10-03
- **执行范围**：仅 AT-AUDIT-001。未处理 003 / 004，未开发 v0.7.0，未执行任何 git 写操作，未调用任何真实付费 API。
- **结论**：**已修复并通过全量回归**。核心执行路径的并发上限现在真实生效，非法参数被显式拒绝，默认行为零变更。

---

## 1. 结论摘要

| 项 | 结果 |
|---|---|
| 根因 | 并发控制机制**存在但从未在核心路径启用**；另有非整型值使上限静默失效的第二条旁路 |
| 修复方式 | 配置贯通（3 个入口）+ 收紧参数校验（1 处），未新增第二套并发机制 |
| 生产代码改动 | 4 个文件（`git diff --numstat` vs HEAD：`scheduler.py` +14/-3、`session.py` +12/-2、`orchestrator.py` +31/-9、`dynamic_team.py` +4/-1）。改动只分三类：参数声明、透传、校验；Scheduler 调度算法、DAG 语义、Retry/Replan 一行未动 |
| 新增测试 | `tests/test_max_concurrency.py`，27 个用例，全部通过 |
| 全量回归 | `pytest -q` → **562 passed**（真实退出码 0）；`ruff check .` → **All checks passed**（退出码 0）；前端构建 **exit 0** |
| 默认行为 | `None`（不限并发）保持不变；已有调用方零影响 |
| 关联修复保护 | AT-AUDIT-002、B1、B2、B3 全部完整保留 |
| 遗留 | API 层仍未暴露该参数（既有设计，非本次断链），见第 11 节 |

---

## 2. Phase 1：代码现状核对（以当前代码为准）

审计描述与代码现状**基本一致**，但有一处需要更正，以及一处审计未提及的额外缺陷。

| 核对项 | 现状 | 与审计是否一致 |
|---|---|---|
| `max_concurrency` 定义位置 | `app/scheduler/scheduler.py:18`，签名参数，默认 `None` | 一致 |
| 默认值 | `None` = 不限制 | 一致 |
| 范围校验（修复前） | 仅 `if max_concurrency is not None and max_concurrency < 1: raise ValueError`，**无类型校验** | 审计未提及，属**额外发现的缺陷** |
| 全仓库真正传值到 Scheduler 的位置 | 仅 2 处：`app/demo/service.py:163`（Day3 demo）、`app/evaluation/evaluator.py:37`（Day5 评估器） | 一致 |
| 核心路径是否传值 | **3 处全部不传**：`app/runtime/session.py:185`、`app/runtime/orchestrator.py:78`、`app/runtime/dynamic_team.py:113` | 一致 |
| Scheduler 是否已有并发机制 | 有：`asyncio.Semaphore`（`scheduler.py:44`，修复前行号） | 一致 |
| 并发控制生效层 | Scheduler 的 `_execute_one`，`async with semaphore` 包住单次 `executor.execute` 调用 | 一致 |
| Offline / Real 是否共用路径 | **是**。`execute_task` 内同一处构造 Scheduler，`provider=None`（Offline）与 `get_llm_provider()`（Real）只影响 provider | 一致 |
| AT-AUDIT-002 是否影响配置传递 | **否**。`_runtime_for(run_id)` 只替换 Runtime 实例，Scheduler 仍在 `run()` 内部构造，修复点不冲突 | 审计未涉及，本次确认 |
| 现有测试覆盖 | `tests/test_scheduler.py:111` 只覆盖 Scheduler 层；`test_evaluation.py:40`、`test_validation.py:293/305` 只断言**派生指标**；**三条核心路径零覆盖** | 一致 |

**需要更正的一处**：审计未指出 `async with semaphore` 的位置。实际它在 `for attempt_number` 循环**内部**、只包住 `executor.execute`；重试退避 `await asyncio.sleep(retry_delay)`（原 `scheduler.py:152`）在信号量**之外**，不占用并发槽位。这是正确行为，本次未改动。

---

## 3. Root Cause

三级根因，按严重度排序：

**R1（主因）— 配置断链**：`AsyncDAGScheduler` 的并发上限是**可选构造参数**，默认 `None`。三条核心执行路径在构造 Scheduler 时只传 `executor` / `retry_policy` / `timeout`，从不传 `max_concurrency`。于是 `scheduler.py:44`（原行号）：

```python
semaphore = asyncio.Semaphore(self.max_concurrency) if self.max_concurrency else None
```

`self.max_concurrency` 恒为 `None` → `semaphore` 恒为 `None` → `_execute_one` 走 `if semaphore is None` 分支 → 整个 ready wave 经 `asyncio.gather` **完全无上限并行**。

**R2（次因，审计未覆盖）— 非整型值使上限静默失效**：修复前的校验只做 `< 1` 比较，类型不检。`asyncio.Semaphore` 的门禁判据是内部值**等于 0**，而浮点值会一路递减穿过 0 永不相等：

```
Python 3.11.4 实测：Semaphore(1.5) 连续 4 次 acquire 全部立即返回
  value: 1.5 → 0.5 → -0.5 → -1.5 → -2.5
```

实测 `max_concurrency=1.5` 在 4 并行子节点的星型拓扑上跑出 **max_concurrent = 4**，上限彻底失效且不报错。`2.0` 侥幸正确（整数值浮点），`True` 被当成 1，二者都是"能用但语义错误"。

**R3 — 入口无参数**：`execute_task()` 签名中没有 `max_concurrency`，因此 API（`app/api/runs.py:216`）、Streamlit（`app/ui_live.py:41`）、CLI 都无法表达并发意图。

---

## 4. Current Configuration Flow（修复前）

```
app/demo/app.py:310        int(concurrency_option) | None
        ↓
app/demo/service.py:46     RunConfig.max_concurrency          ── 仅 Day3 demo 用
        ↓
app/demo/service.py:163    AsyncDAGScheduler(max_concurrency=…)   ✅ 唯一生效的 demo 路径

app/evaluation/evaluator.py:32   evaluate(max_concurrency=…)
        ↓
app/evaluation/evaluator.py:37   AsyncDAGScheduler(executor, max_concurrency, …)  ✅ 唯一生效的评估路径

────────────────────── 以下为断链区 ──────────────────────

app/api/models.py:10       TaskCreateRequest   ← 无并发字段（既有设计）
        ↓
app/api/runs.py:216        execute_task(task, provider=…, timeout=600, …)
        ↓
app/runtime/session.py:126 execute_task(...)   ← 签名中无 max_concurrency   ❌ 断链
        ↓
app/runtime/session.py:185 AsyncDAGScheduler(executor=runtime, retry_policy=…, timeout=…)   ❌ 不传

app/runtime/orchestrator.py:36   ResearchOrchestrator.__init__   ← 签名中无 max_concurrency   ❌ 断链
        ↓
app/runtime/orchestrator.py:78   AsyncDAGScheduler(executor=runtime, retry_policy=…)   ❌ 不传

app/runtime/dynamic_team.py:91   run_dynamic_team(...)   ← 签名中无 max_concurrency   ❌ 断链
        ↓
app/runtime/dynamic_team.py:113  AsyncDAGScheduler(executor=runtime, retry_policy=…)   ❌ 不传
```

---

## 5. Current Execution Flow（修复前）

```
Task Understanding → Capability Discovery → Role Allocation → Dynamic Team Formation
        ↓
build_dynamic_team() / TaskDecomposer.decompose()   →  ExecutionPlan（topology + agents）
        ↓
AsyncDAGScheduler.run()
        ├─ TopologyValidator().validate(topology)
        ├─ semaphore = Semaphore(max_concurrency) if max_concurrency else None   ← 核心路径恒为 None
        └─ while 有 PENDING 节点:
               ├─ 标记上游失败/跳过的节点为 SKIPPED
               ├─ ready = 所有前驱已 SUCCESS 的 PENDING 节点   （层级同步：一个 wave）
               └─ asyncio.gather(*[_execute_one(agent, …, semaphore) for agent in ready])
                        ↑ 无 semaphore 时，整个 wave 一次性全部起飞 = 无上限
        ↓
AgentRuntime.execute() → Tool 执行 → Artifact → Evidence/Sources → Retry/Replan → Final Deliverable
```

层级同步调度本身决定了**上限只在同一个 wave 内生效**，跨 wave 天然串行——这是设计，不是缺陷，本次未改。

---

## 6. Concurrency Control Location

| 层 | 是否控制并发 | 说明 |
|---|---|---|
| API / `RunRegistry` | 否 | 单 run 一个线程，不涉及 |
| `execute_task` | 否（修复前无参数） | 只做入口编排 |
| `ResearchOrchestrator.run` | 否（修复前无参数） | 只做入口编排 |
| `run_dynamic_team` | 否（修复前无参数） | 只做入口编排 |
| **`AsyncDAGScheduler.run`** | **是** | `asyncio.Semaphore`，在 `_execute_one` 内包住单次执行 |
| `AgentRuntime.execute` | 否 | 单 agent 内部串行 |

**被绕过的分支（修复前）**：
1. 3 条核心构造点不传参 → `semaphore is None` 分支（主旁路）
2. 非整型值 → `Semaphore` 门禁失效（静默旁路）
3. 重试退避 sleep 在信号量之外 —— **非缺陷**，不占槽位是对的

---

## 7. Affected Call Chain

```
FastAPI  POST /tasks  →  app/api/runs.py:216  execute_task(...)                    [受影响]
Streamlit ui_live     →  app/ui_live.py:41    execute_task(task)                   [受影响]
Streamlit ui_dynamic  →  app/ui_dynamic.py:42 run_dynamic_team(plan, …)            [受影响]
ResearchOrchestrator  →  app/runtime/orchestrator.py:78                            [受影响]
validation 场景脚本    →  app/runtime/session.execute_task                          [受影响]
demo Day3             →  app/demo/service.py:163                                  [修复前已正确]
evaluation Day5       →  app/evaluation/evaluator.py:37                            [修复前已正确]
```

Offline 与 Real 共用 `execute_task` 的同一构造点，因此两者**同时**受影响、**同时**被修复。

---

## 8. Required Minimal Fix → 实际实施内容

原则：**修复断链，不新增重复配置；修好已有的 Semaphore，不引入第二套机制。**

### 8.1 `app/scheduler/scheduler.py` — 参数校验（唯一校验点）

```python
# 修复前
if max_concurrency is not None and max_concurrency < 1:
    raise ValueError("max_concurrency must be at least 1.")

# 修复后
if max_concurrency is not None:
    if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
        raise TypeError(
            f"max_concurrency must be a positive integer or None, got {max_concurrency!r}."
        )
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1.")
```

```python
# 修复前
semaphore = asyncio.Semaphore(self.max_concurrency) if self.max_concurrency else None
# 修复后（语义等价，但显式化）
semaphore = (
    asyncio.Semaphore(self.max_concurrency) if self.max_concurrency is not None else None
)
```

`None` 仍表示"不限"，默认行为零变更。

### 8.2 `app/runtime/session.py` — `execute_task` 贯通

- 新增关键字参数 `max_concurrency: int | None = None`
- 传给 `AsyncDAGScheduler`（`session.py:185` 附近）
- 同步传给 `provider_fallback` 的兜底重跑调用，保证降级路径上限一致

### 8.3 `app/runtime/orchestrator.py` — `ResearchOrchestrator` 贯通

- 新增关键字参数 `max_concurrency: int | None = None`，存为 `self.max_concurrency`
- `run()` 内构造 Scheduler 时传入

### 8.4 `app/runtime/dynamic_team.py` — `run_dynamic_team` 贯通

- 新增关键字参数 `max_concurrency: int | None = None`
- 构造 Scheduler 时传入

### 8.5 未做的事（明确记录）

- 未新增任何第二套并发机制（无计数器、无队列、无锁替代 Semaphore）
- 未绕过 Scheduler，未把所有执行串行化
- 未重写 Scheduler / Dynamic Team / AgentRuntime / Session / ResultStore
- 未新增 API 字段（见第 11 节）
- 未新增配置文件或环境变量

---

## 9. 新增回归测试（`tests/test_max_concurrency.py`）

27 个用例，全部通过。测量的是**实际并发数**，不是配置值。

**测量方法**：`GateExecutor` 让每个 agent 停在门闩上，测试先记录"同时在飞的数量"，再释放门闩。不依赖固定 sleep 断言并发数；`ConcurrencyTracker` 用 `threading.Lock` 保护计数器。

| 要求 | 对应用例 | 断言要点 |
|---|---|---|
| ① 并发 ≤ 1 | `test_cap_one_never_exceeds_one` | 停在门上时峰值 == 1，全程峰值 == 1 |
| ② 并发 ≤ 2 | `test_cap_two_runs_exactly_two_in_parallel` | 峰值 **== 2**（等于而非小于 → 证明 >1 时并行能力保留） |
| ③ 并发 ≤ 4 | `test_cap_four_runs_exactly_four_in_parallel` | 6 节点 / cap 4 → 峰值 == 4 |
| ④ DAG 依赖顺序不被破坏 | `test_dag_dependency_order_is_preserved_under_cap`（cap=1、2 参数化）<br>`test_parallel_children_still_parallel_when_cap_exceeds_wave` | 菱形 A→B,C→D：A 第一、D 在 B/C 之后；`max_concurrent <= cap`；cap 4 > wave 2 时并行度仍为 2 |
| ⑤ 失败 + 重试不超上限 | `test_failure_and_retry_stay_within_cap` | `failures_before_success={"B": 2}` + `max_retries=2`，`max_concurrent <= 2`，B 第 3 次尝试成功 |
| ⑥ 非法参数被拒绝而非静默忽略 | `test_non_positive_integers_are_rejected`（0/-1/-10）<br>`test_illegal_types_are_rejected_not_silently_accepted`（"2"/"4"/1.5/2.0/True/[2]/{n:2}）<br>`test_fractional_cap_used_to_silently_disable_the_limit`（1.5 回归）<br>`test_invalid_cap_is_not_swallowed_by_execute_task` | ValueError / TypeError 明确抛出；`execute_task(max_concurrency=0)` → session 明确 failed 且 error 含 `max_concurrency` |
| ⑦ 默认配置向后兼容 | `test_default_none_stays_unbounded`<br>`test_none_is_still_an_explicitly_valid_no_limit_value`<br>`test_legacy_positional_construction_still_works` | `None` → 4 节点全并行（峰值 4）；旧式位置参数 `AsyncDAGScheduler(exec, 2, None, RetryPolicy(...))` 仍可用 |
| ⑧ 与 AT-AUDIT-002 任务隔离兼容 | `test_capped_orchestrator_keeps_runs_isolated` | cap=1 下连跑两次，`store.runs()` == 2，两次事件各自 `run_id` 纯净，第一次 run 的结果仍完整可读 |

**额外：三条核心入口的贯通验证**（证明修复的不是配置值而是真实断链）

| 用例 | 断言 |
|---|---|
| `test_execute_task_forwards_max_concurrency` | scheduler 实际收到 `[2]` |
| `test_execute_task_default_forwards_none` | 默认收到 `[None]` |
| `test_orchestrator_forwards_max_concurrency` | 收到 `[1]` |
| `test_run_dynamic_team_forwards_max_concurrency` | 收到 `[2]` |

**反向验证（证明这些用例在修复前会失败）**：模拟修复前的"入口丢弃参数"行为，三个入口实测均得到 `[None]`，与修复后断言的 `[2]` / `[1]` 不符 → 用例具备真实检出能力。

---

## 10. 全量回归与环境证据（本次实测，非复用历史数据）

| 命令 | 真实退出码 | 结果 |
|---|---|---|
| `python -m pytest -q` | `0` | **562 passed** in 16.72s |
| `python -m ruff check .` | `0` | **All checks passed!** |
| `npm run build`（frontend） | `0` | `✓ built in 2.09s` |

- 基线 535 passed → 现 562 passed，**净增 27 项**，无删除、无跳过、无弱化任何既有测试。
- ruff 首次报 `E501`（`tests/test_max_concurrency.py:287` 行长 108 > 100），已修正后复跑通过。
- 前端本不涉及数据结构变化（`frontend/src` 全文无 `concurrency` 引用，API 模型未改），仍完整构建一次以取证。
- 运行环境：系统 Python `3.11.4`（`C:\Users\23746\AppData\Local\Programs\Python\Python311\python.exe`），Node 22.22.2。

**修复前后实测对照（5 节点星型拓扑，4 个并行子节点）**

| `max_concurrency` | 修复前 max_concurrent | 修复后 max_concurrent |
|---|---|---|
| `None`（核心路径现状） | 4 —— 无上限 | 4（默认不变） |
| `1` | 1 | 1 |
| `2` | 2 | 2 |
| `3` | 3 | 3 |
| `4` | 4 | 4 |
| `5` | 4（wave 上限） | 4 |
| `1.5` | **4 —— 静默失效** | `TypeError` |
| `2.0` | 2（侥幸正确） | `TypeError` |
| `True` | 1（语义错误） | `TypeError` |
| `"2"` | `TypeError`（信息不明） | `TypeError`（信息明确） |
| `0` / `-1` | `ValueError` | `ValueError` |

**关联修复与闸门保护状态**

| 项 | 状态 |
|---|---|
| AT-AUDIT-002（`result_store.py` 按 run 分区、`agent_runtime.py` 三处 `run_id=self.run_id`、`orchestrator._runtime_for` + `start_run`） | 完整保留，`tests/test_result_store_isolation.py` 16 项通过 |
| B1（`VERSION = "0.6.1"`） | 完整 |
| B2（SSE `last = last + len(events)`） | 完整 |
| B3（`partial_agent_ids` 透传） | 完整 |
| `REAL_EXECUTION_ENABLED`（`validation/run_scenario.py:64`） | **`False`**，未改动 |
| 真实付费 API 调用 | **0 次**，全部离线 mock |
| git 写操作（commit / push / tag / release / remote） | **0 次** |

**本次改动文件清单**

| 文件 | 性质 |
|---|---|
| `app/scheduler/scheduler.py` | 生产代码：参数校验 + 信号量显式化 |
| `app/runtime/session.py` | 生产代码：新增参数 + 2 处透传 |
| `app/runtime/orchestrator.py` | 生产代码：新增参数 + 1 处透传 |
| `app/runtime/dynamic_team.py` | 生产代码：新增参数 + 1 处透传 |
| `tests/test_max_concurrency.py` | 新增测试 |

---

## 11. 遗留问题与建议（不在本次范围，不做处理）

1. **API 层仍未暴露并发参数**（建议 v0.7 评估）。`TaskCreateRequest`（`app/api/models.py:10`）与 `RunRegistry.start`（`app/api/runs.py:204`）都没有并发字段，因此 API 触发的 run 仍是 `None`（不限并发）。这是**既有设计**——API 从未提供过该参数，本次属"修复断链"，暴露新字段属新增功能，故未做。若要在 API 层限流，需同步改 API 模型与前端类型，建议单独立项。

2. **`execute_task` 对非法 `max_concurrency` 不抛出**。Scheduler 构造抛出的异常会被 `execute_task` 的整体 `except Exception` 捕获，落成 `session.status = failed` 且 `session.error` 携带完整错误信息。可追溯、不静默，但也不会提前中断。是否要在入口前置校验并直接抛出，属行为变更，留给维护者决定。

3. **上限只在单个 wave 内生效**。层级同步调度下，跨 wave 天然串行，因此"最多 N 个 agent 同时执行"只对同一层成立。这是设计语义，不是缺陷。

4. **AT-AUDIT-003 / 004 未处理**（本次授权仅限 AT-AUDIT-001）。

5. **未执行任何 git 提交 / tag / Release**。工作区当前含 13 个已修改文件 + 本批未跟踪产物，`HEAD` 仍为 `f3f7330`。是否提交发布由维护者决定。
