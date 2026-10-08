# AutoTeam v0.6.2 Candidate — 08 API / SSE / 前端一致性审计

> 审计日期：2026-10-03｜只读审计。
> 依据：`app/api/routes.py` 全量端点核对、`tests/test_api.py` 回归测试、`frontend/src/types.ts` 全量阅读。

---

## 1. FastAPI 端点核对（实际 8 个端点）

| 端点 | 行号 | 载体 | 存在 |
|---|---|---|---|
| `GET /api/health` | `routes.py:46` | `{"status":"ok","version":VERSION}` | ✅ |
| `POST /api/tasks` | `:56` | `TaskCreateRequest` → 创建 session | ✅ |
| `GET /api/tasks/{task_id}` | `:65` | `TaskSnapshot` | ✅ |
| `GET /api/tasks/{task_id}/team` | `:70` | `TeamResponse`（含 per-agent `partial`） | ✅ |
| `GET /api/tasks/{task_id}/artifacts` | `:111` | `ArtifactsResponse` | ✅ |
| `GET /api/tasks/{task_id}/result` | `:140` | `FinalResultResponse` | ✅ |
| `GET /api/tasks/{task_id}/events` | `:169` | 历史事件 JSON（重放） | ✅ |
| `GET /api/tasks/{task_id}/stream`（SSE） | `:181` | `stream_events` 生成器 | ✅ |

**缺失端点（对照审计清单）**：无 `cancel` / `delete` / `stop` → `AT-AUDIT-009`。

---

## 2. B1 / B2 / B3 回归验证（本次重新 grep 确认）

| 修复 | 代码位置 | 回归测试 | 判定 |
|---|---|---|---|
| B1 health 版本一致性 | `routes.py:29` `VERSION="0.6.1"` | `tests/test_api.py:32` `test_health` 断言 `== app.version` | ✅ FIXED / 在位 |
| B2 SSE 并发追加不丢事件 | `routes.py:198` `last = last + len(events)` | `tests/test_api.py:210` `test_sse_stream_no_event_loss_on_concurrent_append` | ✅ FIXED / 在位 |
| B3 partial 状态贯通 | `session.py:100` `partial_agent_ids`、`runs.py:77` 快照、`routes.py:99` team 端点 | `tests/test_api.py:265` `test_partial_agent_exposed_in_snapshot` | ✅ FIXED / 在位 |

**前端 B3 四处一致性已核实**（实际读取 `frontend/src/types.ts`）：
- `types.ts:18` `AgentResultDto.partial?: boolean`
- `types.ts:235-243` `AgentStatus` 联合类型含 `'partial'`
- （另 `i18n/index.ts`、`stores/team.ts`、`AgentStatus.vue` 经 grep 确认存在 partial 处理）

---

## 3. 发现的问题

### 3.1 运行失败原因未向客户端暴露（AT-AUDIT-008 / MEDIUM / CONFIRMED）
- `runs.py:229-232` 记录 `handle.error`；但 `runs.py:142-157` `snapshot()` 返回字典**无 error 字段**，routes 中无端点读取
- 客户端只能凭 `status=="failed"` 或 `/result` 404 推断，无法区分「崩溃」与「无最终产物」

### 3.2 无取消 / 终止端点（AT-AUDIT-009 / MEDIUM / CONFIRMED）
- `grep -n "cancel|terminate|stop|delete|shutdown"` 在 `app/api/` 下**无匹配**
- 超时 `timeout=600`（`runs.py:223`）为**单 agent 上限**，非全局运行预算

### 3.3 Run Registry 无界增长（AT-AUDIT-010 / MEDIUM / CONFIRMED）
- `runs.py:185-202` `self._runs` 仅追加，无淘汰；`list()`(:242-246) 线性增长

### 3.4 非法 Task ID 处理
- Registry 按 uuid 键；不存在的 id 走标准 404 路径 **推断存在**，但本次**未读取** `routes.py` 中 404 判定的具体分支源码 → 标记 **NEEDS_VALIDATION**（未证实异常健壮性缺陷）

### 3.5 前端弱类型（AT-AUDIT-018 / LOW / CONFIRMED）
- `app/api/models.py:46-53` `TeamResponse.agents: list[dict[str, Any]]`
- `frontend/src/types.ts:169` `explanation.agents: unknown[]` —— TS 端近乎放弃类型保障

### 3.6 DTO ↔ snapshot 键耦合（AT-AUDIT-017 / LOW / CONFIRMED）
- `app/api/models.py:77-94` 经 `final.get("findings") or []` 读取 `runs.py:85-141` 手拼字典；键漂移会**静默**落默认值

---

## 4. SSE 专项

| 检查 | 结果 | 证据 |
|---|---|---|
| 游标推进 | ✅ 按本轮实际 `len(events)` 推进 | `routes.py:198` |
| 终止条件 | ✅ `handle.done and last >= handle.event_count()` | `routes.py:186-203` |
| 忙等 | ✅ 无（`await asyncio.sleep(0.25)`） | `routes.py:203` |
| 断连重连 | ✅ 由独立守护线程处理；`/stream` 从索引 0 幂等重放 | `routes.py:181+` |
| 重复事件注入 | ✅ 无重复逻辑（后端单次 append + 单调递增计数） | — |
| 任务完成后 SSE 不结束 | ✅ 由 `handle.done` 终止 | — |

**结论**：SSE 一致性在 B2 修复后**无确认缺陷**。

---

## 5. Vue 前端专项

### 5.1 TypeScript 类型与后端一致性 ✅
`frontend/src/types.ts` 全量阅读结果：`AgentResultDto`、`TaskSnapshot`、`TeamResponse`、`ArtifactDto`、`FinalResultResponse`、`ExecutionEvent` 等 DTO 与后端 `app/api/models.py` 字段对齐；`FindingDto`(49-65) 甚至包含 v0.6.6 的 `support_level`、`review_status`、`unsupported_parts` 等新字段 —— **对齐良好**。

### 5.2 ⚠️ 前端零单元测试（AT-AUDIT-020 / INFO / TEST_GAP）
- `find frontend/src -name "*.test.ts" -o -name "*.spec.ts"` → **0 个**
- 影响：partial 渲染映射、SSE 事件处理、空数据/异常响应分支**均无自动化回归保障**；B3 前端渲染正确性仅靠人工/preview 验证。

### 5.3 未证实项（诚实披露）
以下项**未做深度核实**（未逐个组件阅读），标记为未验证：
- 空数据 / 超长内容 / 异常响应的**实际 UI 表现**
- Markdown 渲染是否做 XSS 消毒（详见 09 安全审计专项，标记为待验证）
- 响应式布局与移动端适配
- 是否存在硬编码 Agent / 假 KPI（本次**未发现** grep 证据，但也未逐组件确认）

---

## 6. 本模块问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-008 | MEDIUM | 运行失败原因未暴露 | CONFIRMED |
| AT-AUDIT-009 | MEDIUM | 无取消/终止端点 | CONFIRMED |
| AT-AUDIT-010 | MEDIUM | Run Registry 无界增长 | CONFIRMED |
| AT-AUDIT-013 | MEDIUM | 单例 Registry 不支持多 worker | DESIGN_LIMITATION |
| AT-AUDIT-017 | LOW | DTO 键耦合无编译期保证 | CONFIRMED |
| AT-AUDIT-018 | LOW | `agents` / `explanation.agents` 弱类型 | CONFIRMED |
| AT-AUDIT-020 | INFO | 前端 0 单元测试 | TEST_GAP |
| — | INFO | 非法 Task ID 健壮性 | NEEDS_VALIDATION |
| — | INFO | 前端 Markdown XSS 消毒 | NEEDS_VALIDATION（见 09） |
