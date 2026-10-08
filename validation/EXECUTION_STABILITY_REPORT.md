# AutoTeam v0.6.1 → v0.6.2 — 真实执行与异常恢复审查（Step 5）

> 范围：基于现有代码走查 + 历史/本次真实运行日志，**不新增真实 API 调用、不进行压测**。
> 约束：内存态 Registry 重启丢历史为设计限制，不引入数据库；不得为此扩大架构改造。

## 一、LLM Provider 调用结果处理 ✅

- `app/llm/provider.py`：`OpenAILLMProvider.structured_completion` 对 transport / auth / rate-limit / 解析失败统一抛 `ProviderError`，携带 `category`（provider_error / structured_parse）、`retryable`、`diagnostics`。
- **敏感信息隔离**：`ProviderError` 明确「never contains the API key, request headers or the raw response」；`last_response_meta` 仅含 `finish_reason` / 聚合 `usage`，无 key/header/原文（`provider.py:33-58`）。
- 解析失败区分 length（`finish_reason=length`）与 delimiter，给出分类 `diagnostics`（`provider.py:144-164`）。

## 二、Web Search 调用结果处理 ✅

- `app/tools/registry.py:168` `web_search` 双模式：有 `AUTOTEAM_WEB_SEARCH_URL + KEY` 走真实 POST；失败（超时/坏响应/校验）**降级**为 `_offline_web_results` 并回填 `error="web search failed: <type>"`，**不崩溃、不泄漏 key**。
- 本次真实运行 9 次真实检索、0 offline 回退，证明真实路径可用。

## 三、Timeout / 异常 / 空输出 ✅

- 执行器接受 `timeout`（真实运行 300s），`validation/run_scenario.py` 以守护线程 + 预算 deadline 协作取消；在途同步 HTTP 无法中断属已知约束，已显式记录（`run_scenario.py:288-301`）。
- 空输出：mock 与 real 两条路径均有结构化兜底（mock 返回 stub；real 解析失败抛 typed error）。

## 四、Retry / Replan 状态与恢复 ✅

- 本次真实运行 2 次重试（`competitor_analyst`、`data_analyst` 各 `attempt=2`）后成功，`agent_results` 状态/attempt 正确回写，无状态错乱。
- 未发现 Replan 误触发；DAG 在重试后仍按原拓扑完成（8/0/0）。

## 五、长输出 / 长度限制 / 截断 ⚠️（已知稳健性缺口，非缺陷）

- D1 修复 `_complete_with_length_recovery`（agent_runtime.py:327，真实运行经 `_real_execution` 接入）仅对确认的 `length_limit` 做有界自适应（×1.5/次、上限 8192、≤2 次、finally 还原）。
- **现状**：`AUTOTEAM_LLM_MAX_TOKENS` 未设置 ⇒ token 增长分支惰性，真实环境从未触发 length_limit；D1 证据来自离线 12 项测试。属稳健性缺口（O2），不阻塞 v0.6.2。

## 六、SSE 客户端断连与重连 ✅

- 断连由独立守护线程处理；`/stream` 重连从索引 0 幂等重放（B2 修复前即如此）。
- **B2 修复**：`stream_events` 游标改为 `last = last + len(events)`，消除并发追加时的事件丢弃窗口；回归测试 `test_sse_stream_no_event_loss_on_concurrent_append` 构造竞态并断言全投递。

## 七、重复执行与运行状态一致性 ✅

- 每次运行拥有隔离 `session`，Run Registry 按 uuid 键（`RunHandle` / `RunRegistry`）。未发现重复执行或状态破坏 Bug。
- 真实运行 2 次重试均在同一 session 内恢复，无重复产物。

## 八、内存 Run Registry 生命周期与限制（设计限制）

- **R8**：Registry 为进程内存态，进程重启丢历史——既定设计边界，不引入 Redis/DB（本次约束）。
- 隐私：Registry 仅存 session 元数据（状态/attempt/计时/partial 集合），不含 key/原始 prompt/响应；sanitize 层（`validation/sanitize.py`）对 trace 文本做脱敏（限长 + 剔除 prompt/response/content）。

## 九、Offline 模式可用性 ✅

- `get_llm_provider()`：无 provider / 无 key → `MockLLMProvider`；`web_search` 无 URL+KEY → `offline_mock`。离线测试 519 passed 证明 Offline 全链路可用。

## 十、是否出现「任务已完成但 API/前端显示未完成」

- 未发现可复现异常状态。B2（丢事件）是唯一的「显示滞后/错位」来源，已修复并由回归测试覆盖；重连重放保证最终一致。

## 十一、结论

- **未发现需要代码修复的异常恢复 Bug。** LLM/WebSearch 失败均被类型化或降级处理且不泄漏密钥；Retry 恢复一致；SSE 断连/重连幂等；Registry 隔离正确。
- **唯一稳健性缺口**：D1 token 增长分支因未配置 `AUTOTEAM_LLM_MAX_TOKENS` 而在真实环境惰性——属 O2，记录为后续增强，不阻塞 v0.6.2。
- 内存 Registry 重启丢历史（R8）按计划保留为设计限制。
