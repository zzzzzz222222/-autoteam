# AutoTeam v0.6.2 — AT-AUDIT-005 Fix Report

**问题**：Replanner 生成的 topology 未真正应用到 Scheduler 调度循环
**审计记录**：`validation/full_audit/15_FULL_PROJECT_ISSUE_LIST.md:124-134`（MEDIUM / CONFIRMED / latent）
**修复日期**：2026-10-03
**授权范围**：代码检查、复现、最小修复、测试、报告。**不含** 真实 API 调用、真实 E2E/Baseline、git commit/push/tag/release、v0.7.0、其他审计项。

---

## 1. Root Cause

### 实际执行路径

```
AsyncDAGScheduler.run(task, topology, agents)
  ├─ TopologyValidator().validate(topology)
  ├─ agent_map   = self._validate_agents(topology, agents)
  ├─ predecessors = {agent: {edge.source for edge in topology.edges if edge.target == agent}}
  ├─ statuses     = {agent: PENDING}
  ├─ context      = ExecutionContext(task, topology, agent_map, results)   # 持有 topology
  └─ while 仍有 PENDING:
        ├─ 依据 predecessors + statuses 把上游失败/跳过的节点标 SKIPPED
        ├─ ready = 前驱全部 SUCCESS 的 PENDING 节点
        ├─ await asyncio.gather(*[_execute_one(...) for agent in ready])   # 整波收敛
        └─ for result in completed:
              if FAILED:
                 recovery = self.replanner.replan(topology, result.agent_id, results)
                 【旧】TopologyValidator().validate(recovery.topology)  ← 只校验，然后丢弃
```

### 根因

`recovery.topology` 在通过验证后**从未赋回**任何被调度循环实际使用的数据结构：

- `topology`（决定 `context.get_upstream_results` 与下一轮 READY 判定）**不更新**
- `predecessors`（决定 READY 的唯一直接来源）**不重建**
- `context.topology`（`ExecutionContext` 里给 Agent 看的计划）**不更新**

因此无论 Replanner 返回什么，后续 READY 判定始终基于旧边。审计描述与本仓库代码**一致**（差异仅行号：`scheduler.py:86` 现在约在 `:100` 附近）。

### 与 AT-AUDIT-003 的关系

AT-AUDIT-003 修复后，`ReplanEvent.applied=True` 只表示"候选通过应用闸门"，而应用闸门本身并不产生任何调度效果。**更糟的是**：修复前的判定只看"签名不同"，因此一个**删除了节点**的候选（结构上永远无法执行）也会被标记 `applied=True` —— 这是虚假的已应用状态（见第 2 节实测证据）。

---

## 2. Reproduction

### 复现构造（确定性，无需 sleep）

菱形 DAG `A→B, A→C, B→D, C→D`（`root=A`），令 `B` 失败。Replanner 返回**去掉 `B→D` 边**的候选（`A→B, A→C, C→D`）。

判据是可执行的、非主观的：

| 观察 | 含义 |
|---|---|
| `D == SKIPPED` | 旧边仍然生效 → 候选**未**应用 |
| `D == SUCCESS` | 新边已生效 → 候选**已**应用 |

### 修复前实测（新增测试在修复代码前先跑一次）

```
8 failed, 12 passed
```

关键失败证据：

```
test_valid_candidate_is_applied_to_the_scheduling_loop
  assert <ExecutionStatus.SKIPPED: 'skipped'> is <ExecutionStatus.SUCCESS: 'success'>
  → D 被跳过：候选完全没进调度循环

test_candidate_removing_an_agent_is_refused
  assert True is False   # applied 竟然是 True
  ReplanEvent(failed_agent_id='B',
              previous_topology='agents=A,B,C,D;root=A;edges=A->B,A->C,B->D,C->D',
              new_topology='agents=A,B,C;root=A;edges=A->B,A->C',
              applied=True)
  → 一个删掉了节点 D、结构上永远无法执行的候选，被标记为「已应用」
```

### 修复前后对照（同一脚本，同一构造）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 有效变更（去掉 `B→D`） | `applied=True` 但 `D=SKIPPED` | `applied=True`，`D=SUCCESS` |
| 等价候选 | `applied=False` | `applied=False` + `detail="candidate is identical to the running plan"` |
| 新增节点（`+E`） | **`applied=True`（虚假）** | `applied=False` + `detail="candidate changes the agent set…"` |
| 删除节点（`-D`） | **`applied=True`（虚假）** | `applied=False` + `detail="candidate changes the agent set…"` |
| no-op（`replanned=False`） | `applied=False` | `applied=False` + `detail="replanner produced no candidate plan"` |

---

## 3. Fix

### 修改文件

| 文件 | 改动 |
|---|---|
| `app/scheduler/scheduler.py` | 新增 `_apply_replan()`（候选判定唯一入口）；应用时重建 `topology` / `predecessors` / `context.topology` |
| `app/scheduler/replan.py` | `ReplanEvent` 新增 `detail: str = ""`（记录拒绝原因，拒绝不再静默） |
| `tests/test_replan_topology_application.py` | 新增 20 项定向测试 |

净改动：生产代码约 **+41/-4**（`scheduler.py` +37/-0、`replan.py` +4/-0）。

### 关键实现

```python
# app/scheduler/scheduler.py — 判定（唯一入口，复用既有验证器）
def _apply_replan(self, topology, recovery) -> tuple[bool, str | None, str]:
    if not recovery.replanned or recovery.topology is None:
        return False, None, "replanner produced no candidate plan"
    candidate = recovery.topology
    TopologyValidator().validate(candidate)          # 既有闸门，失败照旧抛出
    new = topology_signature(candidate)
    if new == topology_signature(topology):
        return False, None, "candidate is identical to the running plan"
    if set(candidate.agents) != set(topology.agents):
        return False, None, "candidate changes the agent set, which this scheduler cannot execute"
    return True, new, ""

# 应用：只更新调度循环真正使用的结构
if applied and recovery.topology is not None:
    topology = recovery.topology
    predecessors = {agent_id: {e.source for e in topology.edges if e.target == agent_id}
                    for agent_id in topology.agents}
    context.topology = topology          # Agent 侧 get_upstream_results 也看到新计划
```

`statuses` **一行未动** —— 这是"已完成/运行中 Agent 不被破坏"的实现级保证，而非靠额外检查。

---

## 4. Topology Application Semantics

| 字段/状态 | 含义（修复后） |
|---|---|
| `replanned=False` | Replanner 未提供有效重规划结果 → `applied=False` |
| `replanned=True` | 提供了候选结果，**不代表**已应用 |
| `applied=False` | 未通过校验 / 与当前计划等价 / 当前调度模型无法安全应用 → `detail` 说明原因 |
| **`applied=True`** | ① 通过 `TopologyValidator`；② 与运行中计划**签名不同**；③ agent 集合一致；④ **`topology`、`predecessors`、`context.topology` 已实际更新**，后续 READY 判定基于新计划 |

**何时允许发出 `AGENT_REPLANNED`**：仅当 `applied=True`。判定逻辑未退回旧版 —— AT-AUDIT-003 的过滤（`session.py` 中 `if not event.applied: continue`）保持不变，只是 `applied` 现在名副其实。

`previous_topology` / `new_topology`：仅在实际应用后填充，分别对应**应用前/应用后**的 `topology_signature()`。未应用时两者均为 `None`。

`detail` 为新增的诊断字段（默认空字符串，向后兼容）：`applied=False` 时必带原因，杜绝"静默拒绝"。

---

## 5. Scheduler State Consistency

### 应用时更新了什么

| 结构 | 是否更新 | 为什么 |
|---|---|---|
| `topology` | ✅ | 下一轮 READY 判定与 `context` 的数据源 |
| `predecessors` | ✅ | READY 判定的**直接**来源，不更新则新边无效 |
| `context.topology` | ✅ | `ExecutionContext.get_upstream_results()` 读它，Agent 必须看到真实计划 |
| `statuses` | ❌ **刻意不动** | 见下 |
| `results` / artifacts / evidence / sources | ❌ 不动 | 已产生的结果不允许被拓扑切换抹掉 |

### 如何保护已完成与运行中的 Agent

1. **运行中**：`_apply_replan` 只在 `await asyncio.gather(...)` **整波收敛后**的结果处理段被调用。层级同步调度下此处**没有任何 Agent 在执行**。测试 `test_replan_runs_at_a_quiescent_point` 与 `test_application_does_not_disturb_a_running_wave` 直接断言这一点：Replanner 被调用时 `executor.active_count == 0`（两次失败均为 `[0, 0]`）。因此不存在"并发执行期间改共享拓扑"的问题，也就不需要加锁或延迟应用。
2. **已完成**：`statuses` 不写，`SUCCESS` 不会退回 `PENDING`，`results` 不覆盖 → 不重复执行、不丢结果。测试断言 `call_counts["A"] == 1`、`call_counts["C"] == 1`（`B` 为 `2` = 1 次尝试 + 1 次 retry，属既有 Retry 行为）。
3. **SKIPPED**：不"复活"。已跳过节点的 `AgentResult` 已写入 `results`，重新调度会造成结果不一致。这是明确的设计取舍（见第 12 节）。
4. **下游**：下一轮 `while` 用新 `predecessors` 重算 → 未完成节点的依赖按**新边**判断；依赖落到 FAILED/SKIPPED 的节点照旧被标 SKIPPED（既有 skip 传播逻辑，未改）；DAG 由验证器保证无环，不会死锁。

### 安全限制（显式拒绝，不静默）

候选 agent 集合必须与运行中计划**完全一致**。原因：

- **新增节点**：没有对应 `AgentSpec`，`agent_map[agent_id]` 会 KeyError。
- **删除节点**：被删节点永远停在 `PENDING` → `while any(PENDING)` 且无 ready → `RuntimeError("No runnable agents remain…")`。

二者都被 `_apply_replan` 显式拒绝并返回 `detail`，调度计划保持不变，运行正常收敛（有测试覆盖）。

---

## 6. Test Coverage

新增 `tests/test_replan_topology_application.py`，**20 项，全部通过**（3.33s）。真实 `AsyncDAGScheduler` + 真实 `MockAgentExecutor` + 真实 `execute_task`/`ExecutionTrace`；只把 Replanner 换成确定性替身。无真实 LLM / 搜索，无 sleep 断言。

| 组 | 测试 | 断言要点 |
|---|---|---|
| **A 有效变更** | `test_valid_candidate_is_applied_to_the_scheduling_loop` | `D == SUCCESS`（旧计划下必为 SKIPPED）、`applied=True` |
| | `test_applied_topology_changes_the_downstream_ready_decision` | `call_counts["D"] == 1`；A/C SUCCESS、B FAILED |
| | `test_previous_and_new_topology_match_the_real_plans` | `previous/new_topology` 分别等于前后真实计划签名，且 `detail == ""` |
| | `test_applied_candidate_emits_exactly_one_replan_event` | session 级：恰好 1 条 `AGENT_REPLANNED`，`agent_id`/`run_id` 对应真实变更 |
| **B No-op** | `test_equivalent_candidate_is_not_applied` | `applied=False`、detail 含 `identical`、`D` 仍 SKIPPED、未执行 |
| | `test_noop_candidate_is_not_applied_and_keeps_failure_visible` | 0 事件；`AGENT_FAILED` 仍覆盖 `data_analyst` |
| **C 非法拓扑** | `test_cyclic_candidate_is_rejected_and_changes_nothing` | 抛 `TopologyValidationError`（既有错误处理不变） |
| | `test_unknown_node_is_rejected_by_the_topology_schema` | Schema 层拒绝（边端点不在 `agents`） |
| | `test_invalid_candidate_emits_no_replan_event` | session 落 `failed`、error 含 `Topology`、0 事件 |
| **D 不支持的变更** | `test_candidate_adding_an_agent_is_refused` | `applied=False`、detail 含 `agent set`、无幽灵节点被执行、旧计划不变 |
| | `test_candidate_removing_an_agent_is_refused` | 同上；`D` 未被静默丢弃（仍 resolved） |
| | `test_refused_candidate_leaves_the_scheduler_in_a_terminal_state` | 拒绝后无 PENDING 残留、无死锁 |
| **E 已完成保护** | `test_completed_agents_are_not_reexecuted` | `A`/`C` 各执行 1 次；`B` 仅 retry 不重跑 |
| | `test_results_of_finished_agents_are_preserved` | 已完成节点状态与结果不变 |
| **F 并发** | `test_replan_runs_at_a_quiescent_point` | Replanner 调用时 `active_count == 0` |
| | `test_application_does_not_disturb_a_running_wave` | 一波两失败：`[0, 0]`、`A` 只跑 1 次、无重复调度 |
| | `test_application_respects_the_concurrency_cap` | `max_concurrency=2` 下 `max_concurrent <= 2` 且应用成功 |
| **G AT-AUDIT-003 回归** | `test_noop_still_emits_no_event_after_the_application_fix` | no-op `applied=False`、0 事件（scheduler 级 + session 级） |
| **H AT-AUDIT-001/002 回归** | `test_result_store_run_isolation_still_holds` | `store.runs() == 2`，两 run 事件互不污染 |
| | `test_max_concurrency_is_still_forwarded_alongside_the_fix` | `max_concurrency=3` 正常；`1.5` 仍抛 `TypeError` |

**既有测试文件回归（未删除、未跳过、未降低断言强度）**

| 文件 | 结果 |
|---|---|
| `tests/test_replanner_event_truthfulness.py`（AT-AUDIT-003，16 项） | ✅ 全过 |
| `tests/test_max_concurrency.py`（AT-AUDIT-001，27 项） | ✅ 全过 |
| `tests/test_result_store_isolation.py`（AT-AUDIT-002，16 项） | ✅ 全过 |
| `tests/test_replan.py` / `test_scheduler.py` / `test_autonomous.py` / `test_ui.py` | ✅ 全过（合计 126 项，一次跑通） |

---

## 7. Test Results（本次实际执行）

| 命令 | 真实退出码 | 结果 |
|---|---|---|
| `python -m pytest -q` | **0** | **598 passed** in 17.53s（0 failed / 0 skipped） |
| `python -m ruff check .` | **0** | **All checks passed!** |
| `cd frontend && npm run build` | **0** | `✓ built in 2.26s` |

**与历史基准的差异**

| 项 | 上一份报告（AT-AUDIT-003 后） | 本次 |
|---|---|---|
| pytest | 578 passed | **598 passed（+20）** |
| ruff | All checks passed | All checks passed |
| npm run build | exit 0 | exit 0 |

**过程记录（未隐瞒失败）**

1. 新测试文件在**修复前**先跑一次：`8 failed, 12 passed`（第 2 节证据）。
2. 修复后首跑：`1 failed, 19 passed` —— `test_applied_candidate_emits_exactly_one_replan_event` 失败。原因：该测试用了硬编码 `A/B/C/D` 边的候选，而 session 级 DAG 是 5 个真实 agent id，候选构造时 `root_agent` 默认值 `"A"` 不在 agent 集合内 → Schema 拒绝。属**测试构造错误**（非生产代码问题），改为按运行时拓扑生成链式候选后通过。
3. 首次 `ruff check .` **退出码 1**，2 处 I001（import 排序）：`app/scheduler/scheduler.py`、`tests/test_replan_topology_application.py` 中 `ReplanResult` 排序。修正后复跑 → 退出码 0。
4. 前端：本次**未**改动事件契约、API 响应或前端类型（trace metadata 结构沿用 AT-AUDIT-003 的字段）。仍执行构建确认无需改动。

---

## 8. Core Safety

| 项 | 结论 |
|---|---|
| 是否重写 Scheduler | **否**。只新增 `_apply_replan()` 与一段应用赋值，调度循环、`asyncio.gather`、Semaphore、Retry/Replan 策略、skip 传播逻辑一行未改 |
| 是否重写 Dynamic Team / AgentRuntime / Session / ResultStore | **否**，均未触碰 |
| 是否影响现有编排行为 | 默认路径（`Replanner` 恒 no-op）行为**完全不变**：no-op 仍 `applied=False`，不应用、不发事件。已由 598 项测试确认 |
| 并发安全 | 应用点位于 `asyncio.gather` 整波收敛后，实测 `active_count == 0`；无共享状态竞争，未引入锁 |
| 并发上限 | `max_concurrency` 语义与限制不受影响（测试断言 `max_concurrent <= 2`） |
| 动态节点支持限制 | **不支持**增删节点，候选被显式拒绝（`detail` 记录），不静默忽略、不死锁 |
| 已完成 Agent | 不重跑、结果不丢；`SKIPPED` 不复活（有意为之） |

---

## 9. Security

| 项 | 结果 |
|---|---|
| 真实 LLM / Tavily / 付费 API 调用 | **0 次**（全部离线 mock） |
| `REAL_EXECUTION_ENABLED` | **`False`**，未修改（`validation/run_scenario.py:64` 复核确认） |
| `.env` / API Key / Secret | 未读取、未修改、未输出 |
| 密钥扫描 | 对 `git diff -U0` 执行 `sk-…` / `api_key="…"` / `Bearer …` / `tvly-…` 正则扫描 → **0 命中** |
| 报告与测试输出 | 不含任何凭据、真实 URL 或用户数据 |
| 新增依赖 / 基础设施 | 无 |

---

## 10. Changed Files

### 本次新增/修改（AT-AUDIT-005 及其直接测试、报告）

| 文件 | 状态 |
|---|---|
| `app/scheduler/scheduler.py` | **M**（本次新增 `_apply_replan` + 应用赋值；文件内另有 AT-AUDIT-001 / AT-AUDIT-003 的既有未提交改动） |
| `app/scheduler/replan.py` | **M**（本次新增 `detail` 字段；文件内另有 AT-AUDIT-003 的 `topology_signature` / `applied`） |
| `tests/test_replan_topology_application.py` | **?? 新增**（20 项） |
| `validation/AT-AUDIT-005-fix-report.md` | **?? 新增**（本报告） |

### 工作区中原有的未提交改动（本次未触碰、未清理、未覆盖）

| 文件 | 归属 |
|---|---|
| `app/runtime/result_store.py` | AT-AUDIT-002 |
| `app/runtime/agent_runtime.py` | AT-AUDIT-002（`run_id` 透传） |
| `app/runtime/orchestrator.py` | AT-AUDIT-002 + AT-AUDIT-001 |
| `app/runtime/session.py` | B3 + AT-AUDIT-001 + AT-AUDIT-003 |
| `app/runtime/dynamic_team.py`、`app/api/routes.py`、`app/api/runs.py` | B1 / B2 / AT-AUDIT-001 |
| `frontend/src/*`（4 个文件）、`tests/test_api.py` | B2 / B3 相关 |
| `tests/test_autonomous.py` | AT-AUDIT-003 时更新 |
| `tests/test_max_concurrency.py`、`tests/test_result_store_isolation.py`、`tests/test_replanner_event_truthfulness.py` | 前三次修复的新增测试 |
| `validation/` 下其余报告、`validation/full_audit/` | 历史产物 |

`git diff --check` 退出码 0（无空白/冲突标记问题）。

---

## 11. Git Status

| 项 | 值 |
|---|---|
| 分支 | `master` |
| HEAD | `f3f7330 release: prepare AutoTeam v0.6.1` |
| 工作树 | 15 个已修改文件 + 若干未跟踪文件/目录（含本次新增 2 个） |
| `git diff --stat` | 16 个已跟踪文件有改动；本次相关为 `app/scheduler/scheduler.py`（+71/-7，含前两次修复）、`app/scheduler/replan.py`（+23/-0，含 AT-AUDIT-003） |

**确认：未执行 `git commit`、`git push`、`git tag`、`git release`；未创建、修改或删除任何 Git remote。**

---

## 12. Known Limitations（均经代码或测试确认，非猜测）

1. **内建 `Replanner` 仍是 no-op**（`app/scheduler/replan.py`，本次未改）：恒返回 `replanned=False`。因此**真实运行中仍不会触发应用路径**——本次修的是"一旦 Replanner 给出有效候选，它必须真的生效"，latent 性质未变。
2. **`SKIPPED` 节点不会因新拓扑被复活**：`statuses` 不重写，已跳过节点不会重新进入 READY。取舍理由：其 `AgentResult` 已写入 `results`，重跑会造成结果不一致。代价是"绕开失败上游"的候选无法救回**已被跳过**的节点（只能救回仍处于 `PENDING` 的节点）。
3. **应用时机固定为整波收敛后**：层级同步调度决定了无法在 Agent 运行中改拓扑。这既是不支持"运行中热切换"的限制，也正是本次能安全应用的前提。
4. **候选只能重排边，不能增删节点**：无 `AgentSpec` 的新节点无法执行，被删节点会永久 `PENDING`。二者均被显式拒绝。
5. **并发上限仅在同一 wave 内生效**（既有设计，非本次引入）。
6. **`applied=True` 表示"后续执行计划已更新"**，不保证"该重规划在业务上更优"——项目没有、也不应有 LLM Judge 来评估方案质量。

---

## 13. Conclusion

### AT-AUDIT-005：**FIXED**

判定依据（全部为本次实测）：

| 验收标准 | 结果 |
|---|---|
| `applied=True` 意味着 Scheduler 的实际后续执行计划已更新 | ✅ 应用时同步重建 `topology` / `predecessors` / `context.topology` |
| 有可执行的证据证明计划真的变了 | ✅ 菱形 DAG 中 `D` 由**修复前的 `SKIPPED`** 变为**修复后的 `SUCCESS`** |
| 无法安全应用时必须明确保持未应用 | ✅ 等价候选 / 增删节点候选 / no-op 均 `applied=False` 且带 `detail`；无虚假成功事件 |
| 不得产生虚假的重规划成功事件 | ✅ 修复前"删节点候选被标 `applied=True`"已消除 |
| 真实有效变更仍能发事件 | ✅ session 级恰好 1 条 `AGENT_REPLANNED`，字段与真实变更对应 |
| AT-AUDIT-003 / 001 / 002 不回归 | ✅ 三个测试文件 59 项 + 相关既有文件合计 126 项全过；`test_autonomous.py` / `test_ui.py` / `test_replan.py` / `test_scheduler.py` 未改动即通过 |
| 全量回归 | ✅ `pytest -q` **598 passed**（exit 0）、`ruff check .` exit 0、`npm run build` exit 0 |

**本次停止开发。未处理 AT-AUDIT-004 或其他审计项，未启动新一轮全项目审计，未开始 v0.7.0，未 commit / push / tag / release。等待用户下一步指示。**
