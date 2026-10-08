# AutoTeam v0.6.2 Candidate — 10 测试质量与静态检查审计

> 审计日期：2026-10-03
> **本次实际执行结果**（非历史结果）：pytest / ruff / 前端构建均在本审计内真实重跑。

---

## 1. 本次实际执行的静态检查与构建（真实输出）

| 项 | 命令 | 本次实际结果 | 退出码 |
|---|---|---|---|
| 后端测试 | `python -m pytest -q` | **519 passed**（16.44s），0 failed，0 error | 0 |
| 静态检查 | `python -m ruff check .` | **All checks passed!** | 0 |
| 前端构建 | `cd frontend && npm run build` | 构建成功（见 §1.3） | 0 |

> 执行环境说明：ruff 由系统 Python 3.11.4 提供（托管 venv 未安装 ruff）；pytest 同一解释器。
> **安全边界**：pytest 全程在 `REAL_EXECUTION_ENABLED=False`（`validation/run_scenario.py:64`）下运行，**未产生任何真实 API 调用**。

### 1.3 前端构建
- 本次实际执行：`cd frontend && npm run build`
- 实际输出：`✓ built in 3.46s`，产出 `dist/assets/`（含 `index-BObNsLKJ.js` 135.58 kB / gzip 51.70 kB 等）
- **BUILD_EXIT=0**，无 TypeScript 或构建错误。

---

## 2. 测试资产盘点

- 测试文件：**29 个**（`tests/*.py`）
- 覆盖域（按文件名）：allocator / analyzer / api / autonomous / dynamic_team / evaluation / evaluation_metrics / final_hardening_r1_r2 / models / phase611_tool_execution / phase612_capability_tools / phase66_repair / phase69_source_identity / provenance / realworld / replan / research / retry / scheduler / synthesis / synthesis_reliability / synthesis_scaling / targeted_hardening_d1_d4 / topology / ui / validation / validation_budget / validator

**覆盖广度评价**：✅ 核心域（scheduler / retry / replan / synthesis / tools / provenance / dynamic team / api）均有对应测试文件，覆盖面较完整。

---

## 3. 测试质量评估（不只看通过率）

### 3.1 已覆盖且验证有效 ✅
- B1/B2/B3 三项修复均有针对性回归测试（`tests/test_api.py:32/210/265`）
- D1–D4 专项测试存在（`tests/test_targeted_hardening_d1_d4.py`）
- 工具权限（phase611/612）、来源身份（phase69）、溯源（provenance）、预算（validation_budget）均有测试

### 3.2 ⚠️ 关键 gaps（这些是本次发现 HIGH/MEDIUM 问题仍能潜伏的直接原因）

| 缺口 | 证据 | 关联问题 |
|---|---|---|
| **无测试断言核心执行路径设置了并发上限** | `grep -rl max_concurrency tests/` 命中 4 个文件，但均为**显式传值后**测试 Scheduler 机制本身；**没有任何测试断言** `execute_task` / `ResearchOrchestrator` / `build_dynamic_team` 传入并发上限 | `AT-AUDIT-001`（HIGH）得以潜伏 |
| **ResultStore 跨 run 行为无专项回归** | `grep -rl ResultStore tests/` 仅命中 `tests/test_research.py`（1 个文件），无「跨 run 复用 + events 累积」场景测试 | `AT-AUDIT-002`（HIGH）得以潜伏 |
| **Replan no-op 的“误导性事件”无断言** | `tests/test_replan.py` 存在，但 Replanner 恒返回 `replanned=False`；未见测试断言「不应产生 AGENT_REPLANNED 事件」 | `AT-AUDIT-003`（HIGH） |
| **partial 产物下游消费无测试** | 无测试覆盖 partial artifact 注入下游 context 的行为 | `AT-AUDIT-007`（MEDIUM） |
| **前端无自动化测试** | `frontend/src` 下 `*.test.ts` / `*.spec.ts` = **0** | `AT-AUDIT-020` |
| **无性能/并发压测** | 未见 concurrency stress / 大规模 evidence 的性能测试 | `AT-AUDIT-026` |
| **failure-reason 暴露无测试** | 无测试断言 snapshot 应含 error | `AT-AUDIT-008` |

### 3.3 弱测试 / 过度 Mock 风险（抽查结论）
- 存在 Mock LLM Provider（`MockLLMProvider`），离线全链路依赖它；这是**设计需要**（离线可跑），但意味着**离线测试通过 ≠ 真实 LLM 行为正确**
- 本次**未逐文件审查**断言强度（如仅 `assert result` 这类非空弱断言的比例）→ 标记为 **NEEDS_VALIDATION**，不作结论

---

## 4. 「测试通过」不等于「系统可靠」——本次实证

519 passed 与本次发现的 **4 个 HIGH 问题**并存，直接证明：
- 并发上限缺失（001）→ 无测试守护
- ResultStore 跨 run 污染（002）→ 无测试守护
- Replan 误导事件（003）→ 无测试守护
- headline 计数口径（004）→ 无测试守护.

**这正是「不以测试通过代替系统绝对可靠」原则的现实例证。**

---

## 5. 本模块问题清单

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-020 | INFO | 前端 0 单元测试 | TEST_GAP |
| AT-AUDIT-024 | INFO | 真实运行样本不足（partial/failure 真实路径无样本） | TEST_GAP |
| AT-AUDIT-026 | INFO | 无性能/并发压测 | TEST_GAP |
| — | INFO | 断言强度（弱断言/过度 Mock 比例）未逐文件核实 | NEEDS_VALIDATION |

---

## 6. 建议新增的回归测试（对应本次发现）

1. `test_core_paths_set_concurrency_cap` —— 断言 session/orchestrator/dynamic_team 传入非 None 的 `max_concurrency`
2. `test_result_store_isolated_per_run` —— 断言两次 `run()` 后 `store.events` 不含上一次 run 的事件；`status_of` 不返回历史 run 状态
3. `test_replan_noop_emits_no_replan_event` —— 断言未真正重规划时不产生 `AGENT_REPLANNED`
4. `test_partial_artifact_not_injected_as_complete` —— 断言 partial upstream 被下游标注或隔离
5. `test_snapshot_exposes_failure_reason` —— 断言 `TaskSnapshot.error` 非空
6. 前端引入 Vitest，至少覆盖：partial 渲染映射、SSE 事件处理、空/异常响应分支
