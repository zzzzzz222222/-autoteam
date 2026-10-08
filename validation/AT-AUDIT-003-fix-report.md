# AutoTeam v0.6.2 — AT-AUDIT-003 Fix Report

**问题**：Replanner no-op 仍触发 `AGENT_REPLANNED` 事件
**审计记录**：`validation/full_audit/15_FULL_PROJECT_ISSUE_LIST.md:86-99`
**修复日期**：2026-10-03
**授权范围**：代码修改 + 测试 + 本地验证。**不含** 真实 API 调用、git commit / push / tag / release。

---

## 1. Issue Summary

| 项 | 内容 |
|---|---|
| 审计问题 | Replan 为空操作但仍向 trace 写入「已重规划」事件 |
| 原审计严重程度 | **HIGH**｜状态 **CONFIRMED**｜模块 Scheduler / Session |
| 触发条件 | 任一 agent 执行失败 |
| 实际表现 | trace / SSE / UI 显示「已重规划」，但拓扑从未变更、无自愈动作 |
| 预期表现 | 未发生重规划时不应上报重规划事件 |
| 影响 | 状态与 UI 不一致；用户误判系统已自愈 |

**本次处理范围（严格限定）**

- 只修 **事件真值性**：`AGENT_REPLANNED` 必须代表"真实发生并通过应用闸门的有效计划变更"。
- **不修** AT-AUDIT-005（重规划拓扑验证后不回灌调度循环）——那是独立的 MEDIUM 审计项、独立的修复点，本次不动。
- 不重写 Scheduler / Dynamic Team / AgentRuntime / Session / ResultStore；不改 Retry / Replan 策略；不改 API 契约与前端类型。

---

## 2. Root Cause

### 当前 Replanner 调用链

```
AgentRuntime 执行失败
  → AgentResult.status = FAILED
  → AsyncDAGScheduler.run()  (app/scheduler/scheduler.py:92)
        recovery = self.replanner.replan(topology, result.agent_id, results)      ← 每个 FAILED 必调用
        【旧】self.replan_events.append(ReplanEvent(failed_agent_id, reason))      ← 无条件、在验证之前
        【旧】if recovery.replanned and recovery.topology is not None:
                  TopologyValidator().validate(recovery.topology)
  → TaskExecutionSession.execute_task()  (app/runtime/session.py:208)
        for event in scheduler.replan_events:                                     ← 全量、无过滤
            trace.record("AGENT_REPLANNED", agent_id=..., message=event.reason)
  → ExecutionTrace → SSE (app/api/runs.py stream_events) → 前端 ExecutionView.vue
```

### 原事件触发位置

`app/scheduler/scheduler.py`，**在候选计划被验证之前、被应用之前**无条件 append；`app/runtime/session.py` 再把该列表**全量**转成 trace 事件。两层都没有任何"是否真的改了计划"的判据。

### no-op 仍触发事件的真实原因（四条叠加）

1. **事件在验证/应用之前发出，且不带成功标记** → "Replanner 被调用" 被等价成 "重规划成功"。
2. **内建 `Replanner` 恒为 no-op**：`replan.py:37-41` 永远返回 `ReplanResult(replanned=False, reason="no viable recovery plan", topology=None)`。因此**每一次 agent 失败都必然是 no-op，也必然产生一条假的 `AGENT_REPLANNED`** —— 这不是偶发，是必现。
3. **从不比较重规划前后的计划** → 即使未来 `replanned=True` 但返回的拓扑与当前相同，仍会发事件。
4. **`ReplanEvent.previous_topology` / `new_topology` 从未填充**（对应 AT-AUDIT-015）→ 事件本身也无法自证"改了什么"。

### 复现证据（修复前实测，见第 3 节）

```
replanner_invoked          : True ['data_analyst']
recovery.replanned         : [False]
recovery.reason            : ['no viable recovery plan']
recovery.topology is None  : [True]
AGENT_REPLANNED count      : 1
   -> AGENT_REPLANNED data_analyst | no viable recovery plan
data_analyst status        : failed
BUG REPRODUCED             : True
```

---

## 3. Before Fix

复现方式：`execute_task`（离线 mock）中注入一个记录调用次数的 `NoOpReplanner`（继承并调用**真实** `Replanner`），令 `data_analyst` 失败。

### 修复前 no-op 行为与事件记录

| 观察项 | 修复前 |
|---|---|
| Replanner 是否被调用 | 是（1 次） |
| `ReplanResult.replanned` | `False` |
| `ReplanResult.reason` | `no viable recovery plan` |
| `ReplanResult.topology` | `None` |
| `scheduler.replan_events` | 1 条（无条件写入） |
| trace `AGENT_REPLANNED` | **1 条**（`data_analyst` / `no viable recovery plan`） |
| 拓扑是否真的变化 | **否** |

### 旧规则 vs 新规则对照（同一脚本、同一注入方式，逐场景实测）

旧规则的事件数 = Replanner 调用次数（旧代码每次调用必写一条 trace 事件，与返回结果无关）。

| 场景 | 旧规则事件数 | 新规则事件数 | 结论 |
|---|---|---|---|
| no-op（`replanned=False`） | 1 | **0** | 假事件已消除 |
| 等价候选（`replanned=True` 但拓扑相同） | 1 | **0** | 假事件已消除 |
| 未应用候选（`replanned=True` 但 `topology=None`） | 1 | **0** | 假事件已消除 |
| 无效候选（循环图，验证失败） | 1 | **0** | 假事件已消除 |
| **真实有效变更**（不同且合法的链式拓扑） | 1 | **1** | 真实能力保留 |

复现脚本与对照脚本均为临时文件，位于系统临时目录，已删除；仓库内未留下临时文件。

---

## 4. Implementation

### 修改文件清单

| 文件 | 改动性质 |
|---|---|
| `app/scheduler/replan.py` | 新增 `topology_signature()`；`ReplanEvent` 新增 `applied: bool = False` |
| `app/scheduler/scheduler.py` | 计算 `applied`；append 移到验证之后；填充 `previous/new_topology` |
| `app/runtime/session.py` | `AGENT_REPLANNED` 只在 `event.applied` 为真时写入；附带计划签名 metadata |
| `tests/test_replanner_event_truthfulness.py` | 新增 16 项回归测试 |
| `tests/test_autonomous.py` | 更新 1 项断言了缺陷行为的既有测试（见第 7 节） |

净改动：生产代码 `replan.py` +19/-0、`scheduler.py` +34/-7（含 AT-AUDIT-001 部分）、`session.py` +20/-2（含 B3 / AT-AUDIT-001 部分）。AT-AUDIT-003 本身约 **+25/-4**。

### 新的事件触发条件

```python
# app/scheduler/scheduler.py
applied = False
previous = topology_signature(topology)
new: str | None = None
if recovery.replanned and recovery.topology is not None:
    TopologyValidator().validate(recovery.topology)      # 既有闸门，失败照旧抛出
    new = topology_signature(recovery.topology)
    applied = new != previous                            # 必须真的不同
self.replan_events.append(
    ReplanEvent(..., previous_topology=..., new_topology=..., applied=applied)
)

# app/runtime/session.py
for event in scheduler.replan_events:
    if not event.applied:
        continue                                         # no-op / 无效 / 未应用 → 不发事件
    trace.record("AGENT_REPLANNED", agent_id=..., message=event.reason,
                 previous_topology=..., new_topology=...)
```

**`applied = True` 的三个必要条件**：① Replanner 声明 `replanned=True`；② 提供了候选拓扑且通过既有 `TopologyValidator`；③ 候选与当前执行中的计划**签名不同**。

### 有效计划变更的判定方式

`topology_signature(topology)` → `agents=...;root=...;edges=...`，覆盖 agent 集合、root、全部边。签名相同即同一份计划，视为 no-op。

### 计划验证与应用流程（如实说明）

- 验证：`TopologyValidator().validate()` —— **既有逻辑，一行未改**。
- 应用：当前系统定义在 `run()` 里的应用闸门就是上面这条 `if` + `validate`。（与既有错误处理一致：验证失败照旧抛 `TopologyValidationError`，由 `execute_task` 外层 `except` 落成 failed session。）

> ⚠️ **诚实披露**：`applied=True` 表示"候选被当前系统的应用闸门接受"，**不等于**该拓扑重新驱动了调度循环。现有实现在验证后**不会**把 `recovery.topology` 赋回 `topology` / 重建 `predecessors`（`app/scheduler/scheduler.py` 中 `topology` 从不重新赋值）——这正是独立的 **AT-AUDIT-005（MEDIUM / CONFIRMED / latent）**。本次按授权不动它，因此"重规划成功"在调度层面仍有残余落差，见第 10 节。

### 与 AT-AUDIT-001 / 002 的兼容

- **AT-AUDIT-001**：并发闸门（`asyncio.Semaphore`）与本次判定完全正交——`_execute_one` 内获取信号量，replan 判定发生在 wave 结束后的结果处理段，不涉及并发路径。新增测试 15/16 在 `max_concurrency=2` 下验证：no-op → 并发仍 `<= 2` 且 `== 2`（并行能力未丢）；有效变更 → `<= 2` 且 `applied=True`。
- **AT-AUDIT-002**：本次**没有**引入任何新的事件存储。`AGENT_REPLANNED` 仍由 `ExecutionTrace`（按 `run_id` 天然隔离）承载；`ResultStore` 的 per-run 分区（`_events_by_run` / `start_run` / `events_of`）零改动，新增测试 14 复用它验证两个 run 的隔离仍成立。

---

## 5. Regression Tests

新增 `tests/test_replanner_event_truthfulness.py`，**16 项，全部通过**（2.86s）。

测试走**真实** Scheduler、真实 `execute_task`、真实 `ExecutionTrace`；只把 Replanner 依赖换成确定性脚本化替身（`ScriptedReplanner`）。**事件判定逻辑与事件记录逻辑从未被 mock**。无真实 LLM / 搜索，无 sleep 推断事件。

| # | 测试 | 真实断言 |
|---|---|---|
| 1 | `test_noop_replan_emits_no_event` | `invocations == ["data_analyst"]`；所有 `replanned is False`；`reason == "no viable recovery plan"`（既有 no-op 语义保留）；`topology is None`；**`AGENT_REPLANNED == 0`** |
| — | `test_noop_replan_is_still_recorded_for_observability` | no-op 仍留痕：`len(replan_events) == 1`、`applied is False`、`reason` 保留、`previous/new_topology` 为 `None` |
| — | `test_equivalent_candidate_is_treated_as_noop` | `replanned=True` 但拓扑相同 → **0 事件** |
| 2 | `test_effective_change_emits_one_event` | **1 事件**；`agent_id == data_analyst`、`run_id == session.run_id`（无虚假关联）、`previous_topology != new_topology`、且 `new_topology == topology_signature(候选)` |
| — | `test_effective_change_is_flagged_applied_on_the_scheduler` | `applied is True`；`previous != new` 且均非 `None` |
| 3 | `test_invalid_candidate_emits_no_event` | 循环图候选 → `pytest.raises(TopologyValidationError)`（既有错误处理不变）+ **`scheduler.replan_events == []`** |
| — | `test_invalid_candidate_does_not_reach_the_trace` | session 落 `failed`、`error` 含 `Topology`、**trace 中 0 事件** |
| 4 | `test_unapplied_candidate_emits_no_event` / `test_unapplied_candidate_is_flagged_not_applied` | `replanned=True` 但 `topology=None` → `applied is False`、**0 事件** |
| 5 | `test_repeated_noops_emit_no_events` / `test_repeated_noops_on_one_context_emit_no_events` | 同一上下文 2 次 no-op（session 级两个失败 agent + scheduler 级）→ `invocations == 2`、**事件数 0**，不累积 |
| 6 | `test_single_effective_change_is_not_duplicated` | 1 次有效重规划 → **恰好 1 事件**，不重复处理 |
| 7 | `test_replan_event_is_scoped_to_its_own_run` | Run A（有效变更）有 1 条且 `run_id == A.run_id`；Run B（no-op）**0 条**；`A.run_id != B.run_id`；双向无污染 |
| — | `test_result_store_isolation_still_holds_alongside_the_fix` | 复用 AT-AUDIT-002：`store.runs() == 2`，两个 run 的事件各自 `run_id` 纯净 |
| 8 | `test_noop_replan_under_concurrency_cap` / `test_effective_replan_under_concurrency_cap` | `max_concurrency=2` 下：`scheduler.max_concurrency == 2`、`executor.max_concurrent <= 2` 且 `== 2`（并行未丢）；no-op → `applied False`，有效变更 → `applied True` |

**测试 4 的说明**：当前实现**没有**独立的"应用失败"步骤（应用闸门即验证，验证失败直接抛出）。因此用两条**真实存在**的分支替代：`replanned=True` 但 `topology=None`（无可应用的计划）与"等价候选"（无实际差异）。未为测试虚构生产行为。

---

## 6. Full Test Results（本次实测，非复用历史）

| 命令 | 真实退出码 | 结果 |
|---|---|---|
| `python -m pytest -q` | **0** | **578 passed** in 16.97s（0 failed / 0 skipped） |
| `python -m ruff check .` | **0** | **All checks passed!** |
| `cd frontend && npm run build` | **0** | `✓ built in 2.16s` |

**与历史基准的差异**

| 项 | 历史基准（AT-AUDIT-001 报告） | 本次 |
|---|---|---|
| pytest | 562 passed | **578 passed（+16）** |
| ruff | All checks passed | All checks passed |
| npm run build | passed | exit 0 |

**过程记录（未隐瞒失败）**

1. 修复后首次跑受影响测试：`tests/test_autonomous.py::test_replan_integration_skips_downstream` **失败**（`assert [] == ['database_engineer']`）。判定：该既有测试**断言了缺陷行为**，属本次修复必然影响，非无关回归 → 更新其断言（见第 7 节）。
2. 首次 `ruff check .` **退出码 1**，3 处：
   - `app/scheduler/replan.py:22` E501（103 > 100）→ 拆行；
   - `tests/test_replanner_event_truthfulness.py` I001 import 排序 → `Replanner, ReplanResult` 调整顺序；
   - `tests/test_replanner_event_truthfulness.py:304` E501（102 > 100）→ 拆行。
   修正后复跑 → 退出码 0。
3. 前端：本次给 trace 事件新增了 `previous_topology` / `new_topology` 两个 **metadata 键**（事件类型名与结构未变），属事件契约的附加字段，故执行了构建取证。`ExecutionView.vue` 仅按 `event.type` 映射文案，新增 metadata 键不破坏类型。

---

## 7. Scope Verification

### 本次改动文件

| 文件 | 是否本次必要 |
|---|---|
| `app/scheduler/replan.py` | ✅ 事件真值标记 + 计划签名 |
| `app/scheduler/scheduler.py` | ✅ 变更判定与事件生成点（AT-AUDIT-003 部分；文件内另有 AT-AUDIT-001 既有改动） |
| `app/runtime/session.py` | ✅ 事件写入过滤（文件内另有 B3 / AT-AUDIT-001 既有改动） |
| `tests/test_replanner_event_truthfulness.py` | ✅ 新增回归测试 |
| `tests/test_autonomous.py` | ✅ 更新 1 项断言缺陷行为的既有测试 |

### 既有测试的更新（如实记录，非删除/跳过/弱化）

`tests/test_autonomous.py::test_replan_integration_skips_downstream` 原文断言 `AGENT_REPLANNED == ["database_engineer"]`，正是被修复的假事件。更新为：

```python
assert session.trace.of_type("AGENT_REPLANNED") == []          # no-op 不再谎报
failed = session.trace.of_type("AGENT_FAILED")
assert {event.agent_id for event in failed} == {"database_engineer"}   # 失败仍然可见
# 原测试其余断言（backend_developer skipped / final artifact 生成）全部保留
```

测试未删除、未跳过、未改名；断言强度未降低（新增了一条更严格的 `AGENT_FAILED` 断言）。其余 577 项测试零改动。

### 既有修复保护状态（均已复核在位）

| 项 | 状态 |
|---|---|
| AT-AUDIT-002（`result_store.py` per-run 分区、`agent_runtime.py` 三处 `run_id=self.run_id`、`orchestrator._runtime_for` + `start_run`、`tests/test_result_store_isolation.py` 16 项） | ✅ 完整，未被覆盖/回滚 |
| AT-AUDIT-001（`scheduler.py` 正整数校验 + 三入口透传、`tests/test_max_concurrency.py` 27 项） | ✅ 完整 |
| B1（`VERSION = "0.6.1"`） | ✅ |
| B2（SSE `last = last + len(events)`） | ✅ |
| B3（`partial_agent_ids` 透传） | ✅ |
| `REAL_EXECUTION_ENABLED`（`validation/run_scenario.py:64`） | ✅ `False`，未动 |

### 是否影响核心模块

Scheduler / Dynamic Team / AgentRuntime / Session / ResultStore **均未重写**。改动只是在既有调用点内加了判定与过滤，未改调度算法、DAG 语义、Agent 状态机、Retry 策略（`RetryPolicy` / 退避逻辑一行未动）。

### 兼容性风险

- `ReplanEvent` 新增字段 `applied`（默认 `False`）——向后兼容；既有读取方（`demo/service.py:169`、`examples/recovery_demo.py:40`）只取 `failed_agent_id` / `reason`，不受影响，且 `tests/test_replan.py`、`tests/test_ui.py` 仍全绿。
- trace 事件新增 `previous_topology` / `new_topology` metadata 键——纯附加，前端无影响（已构建验证）。
- 真实运行的 `collect.py:720` 统计的 `replan_events` 数量会下降（假事件不再计入）。这是**修复的预期效果**，不是回归。

---

## 8. Security

| 项 | 结果 |
|---|---|
| 真实 API 调用次数 | **0**（全部离线 mock；`REAL_EXECUTION_ENABLED=False` 未动） |
| Secret 修改 | **无**（未触碰 `.env`、API Key、Token） |
| 密钥扫描 | 对 `git diff -U0` 全文执行 `sk-…` / `api_key="…"` / `Bearer …` / `tvly-…` 正则扫描 → **0 命中** |
| 日志 / 报告泄密 | 报告与测试输出中**无**密钥、无真实 URL、无用户数据；仅含代码路径与离线 agent id |
| 新增依赖 | 无 |

---

## 9. Git Status

| 项 | 值 |
|---|---|
| 分支 | `master` |
| HEAD | `f3f7330 release: prepare AutoTeam v0.6.1` |
| 工作树 | 15 个已修改文件 + 4 个未跟踪目录/文件（含本次新增） |

本次新增/修改：

- `app/scheduler/replan.py`（M）
- `app/scheduler/scheduler.py`（M，含 AT-AUDIT-001 既有改动）
- `app/runtime/session.py`（M，含 B3 / AT-AUDIT-001 既有改动）
- `tests/test_autonomous.py`（M）
- `tests/test_replanner_event_truthfulness.py`（?? 新增）
- `validation/AT-AUDIT-003-fix-report.md`（本报告）

其他未提交改动（AT-AUDIT-002 / B1 / B2 / B3 / AT-AUDIT-001 相关）**原样保留**，未被回滚、覆盖或清理。

**明确说明：本次未执行 `git commit`、`git push`、tag、release，未创建/修改/删除任何 Git remote。**

---

## 10. Remaining Limitations

### Bug（已修）

- AT-AUDIT-003：no-op / 等价候选 / 无效候选 / 未应用候选不再发出 `AGENT_REPLANNED`。真实有效变更仍发出恰好 1 条。

### Design Limitation（未修，需单独立项）

1. **AT-AUDIT-005**：验证通过的 `recovery.topology` 不会回灌调度循环（`topology` / `predecessors` 从不重建）。后果：即使本次判定 `applied=True`，实际调度仍按原拓扑走完。⇒ **`AGENT_REPLANNED` 目前表达的是"候选被应用闸门接受"，还不是"调度真的改了"**。要让事件与调度 100% 对齐，必须先修 005。这是本次授权的边界，未动。
2. **no-op 的 `reason` 不再进入 ExecutionTrace**。它仍完整保留在 `scheduler.replan_events`（`applied=False`）与 demo 的 `ExecutionRun.replan_events` 中；失败本身仍由 `AGENT_FAILED`（`agent_runtime.py:919`）记录，实测同一 run 有 3 条 `AGENT_FAILED`，失败可见性没有丢失。仅为避免发明新事件语义，未把 no-op 转成"失败"事件。

### Test Gap（未覆盖）

- 真实 LLM 场景下**不存在**有效重规划路径可测：内建 Replanner 是确定性实现（与 provider 无关），永远返回 no-op。因此"真实运行出现有效重规划"只能通过脚本化 Replanner 验证，本报告的测试 2/6 即属此类。
- `structure / report / done / error` 仍未按 run 分区（AT-AUDIT-002 遗留）。

### Needs Validation（需后续验证）

- 修完 AT-AUDIT-005 后，需补一条集成测试：验证"有效重规划 → 调度真的按新拓扑执行 → 恰好 1 条 `AGENT_REPLANNED`"。当前架构下该断言无法成立。
- 若未来引入非确定性（LLM 驱动的）Replanner，需重新评估"等价候选"判据是否足够（签名相同 vs 语义相同）。

---

## 11. Conclusion

| 问题 | 回答 |
|---|---|
| **AT-AUDIT-003 是否已修复？** | **是。** 事件生成点已从"Replanner 被调用"改为"通过应用闸门的真实有效变更"。 |
| **no-op 是否不再发出 `AGENT_REPLANNED`？** | **是。** 4 类非变更场景（no-op / 等价候选 / 未应用候选 / 无效候选）实测均由旧规则的 1 条降为 **0 条**。 |
| **真实有效变更是否仍能发出事件？** | **是。** 有效且不同的候选实测仍发出**恰好 1 条**，且 `agent_id` / `run_id` / 计划签名与实际变更一一对应。 |
| **测试是否实际通过？** | **是。** `pytest -q` 578 passed（退出码 0）、`ruff check .` All checks passed（退出码 0）、`npm run build` 退出码 0 —— 均为本次重新执行，非历史数据。 |
| **是否存在未解决问题？** | 有 1 项**边界外**的既有缺陷：AT-AUDIT-005（验证后的拓扑不回灌调度）。它使"重规划成功"在调度层面仍有残余落差，属独立审计项，本次按授权未修。另有 1 项取舍：no-op 的 reason 不再进入 trace（仍保留在 scheduler 层）。 |
| **是否达到进入下一项修复的条件？** | **是。** 本次改动范围封闭、既有修复完整、全量回归绿灯，可继续下一项（如 AT-AUDIT-004 或 AT-AUDIT-005）。 |

**核心验收标准达成**：`AGENT_REPLANNED` 现在只代表"真实发生并通过应用闸门的有效计划变更"，不再代表"Replanner 被调用"或"返回了候选结果"。

**本次停止工作。未开始 AT-AUDIT-004 或其他审计项，未 commit / push / tag / release。**
