# AutoTeam v0.6.1 → v0.6.2 — API / SSE / UI 一致性审查（Step 6）

> 范围：核对后端状态/事件/团队/Artifact/Result 与前端显示一致性；回归 B1/B2/B3。
> 不追求无谓重构；若实现与测试已充分，则记录确认。

## 一、端点清单（代码核对，`app/api/routes.py`）

| 端点 | 行号 | 一致性载体 |
|---|---|---|
| `GET /api/health` | 46 | `version=VERSION` |
| `POST /api/tasks` | 56 | `TaskCreateRequest` → 创建 session |
| `GET /api/tasks/{id}` | 65 | `TaskSnapshot` |
| `GET /api/tasks/{id}/team` | 70 | `TeamResponse`（含 per-agent `partial`） |
| `GET /api/tasks/{id}/artifacts` | 111 | `ArtifactsResponse` |
| `GET /api/tasks/{id}/result` | 140 | `FinalResultResponse` |
| `GET /api/tasks/{id}/events` | 169 | 历史事件 JSON |
| `GET /api/tasks/{id}/stream`（SSE） | 181 | `stream_events` 生成器 |

8 个目标端点**全部存在**。

## 二、B1 回归 — Health 版本一致性 ✅

- `routes.py:29` `VERSION = "0.6.1"`，`health()` 返回 `{"status":"ok","version":VERSION}`。
- 测试 `tests/test_api.py:32` `test_health` 断言 `body["version"] == app.version`（`app.version` 来自 `main.py:19` 的 `0.6.1`）。
- 后端对外版本与 `app/api/main.py` 应用版本一致，无过期暴露。

## 三、B2 回归 — SSE 并发追加不丢事件 ✅

- `stream_events`（`routes.py:182`）：游标推进 `last = last + len(events)`（`routes.py:198`），只推进本轮实际已发送数量，消除对 `event_count()` 的重读竞态。
- 回归测试 `tests/test_api.py:210` `test_sse_stream_no_event_loss_on_concurrent_append`：构造 `events()` 滞后、`event_count()` 超前的伪 handle，断言全部 `event_id` 均被投递，修复前后对比通过。
- 重连/游标/重复事件/断连：`get_events_history`（169）提供历史重放；`stream_events` 从 `last` 续传，断连后前端可重连补齐；无重复事件注入逻辑（事件由后端单次 append + 单调递增计数保证唯一）。

## 四、B3 回归 — 部分交付状态在 API 与前端一致 ✅

后端：
- `routes.py:99` `get_team` 每 agent 暴露 `"partial": bool(result.get("partial", False))`。
- `runs.py:77` `RunHandle.snapshot()` 暴露 `"partial": agent_id in partial_agent_ids`。
- `session.py:100` `TaskExecutionSession.partial_agent_ids` 记录部分交付 agent。

前端（4 处一致）：
- `types.ts`：`AgentResultDto.partial?: boolean` + `AgentStatus` 增 `'partial'`。
- `i18n/index.ts`：`agentstatus.partial` 中英文案。
- `stores/team.ts`：`result.partial ? 'partial' : 'success'`。
- `AgentStatus.vue`：`case 'partial'` → 警告图标 + `at-warn-text`。

回归测试 `tests/test_api.py:265` `test_partial_agent_exposed_in_snapshot`：StubSession 带 `partial_agent_ids={"agent_p"}`，断言快照暴露 `partial=True`。

**结论**：部分交付状态在 API（team/snapshot）与前端（类型/文案/映射/渲染）四层一致；正常（非 partial）路径经真实运行 `valid_real_e2e=True` 验证 SUCCESS 正确。

## 五、后端状态 → 前端显示一致性

- 真实运行（run_f4c191c6）8 Agent 全部 `status=success`、`partial=None`，前端映射为 `'success'`；若某 Agent `partial=True`，前端将渲染为「部分交付」而非「已完成」，与后端 `partial` 标志严格对应。
- Artifact / Result：前端通过 `/artifacts`、`/result` 拉取，后端序列化与 `AgentArtifact`/`FinalArtifact` schema 一致（`types.ts` DTO 与后端模型对应），运行期无字段错位。

## 六、结论

- **B1 / B2 / B3 三处回归均通过且有测试保障。**
- 8 个目标端点齐全；后端状态、事件、团队、Artifact、Result 与前端显示经代码核对 + 真实运行闭环验证为一致。
- **无需为追求改动而重构。** API/SSE/UI 一致性问题已在 v0.6.1 + 本轮修复中解决。
