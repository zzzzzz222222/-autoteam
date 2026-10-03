# AutoTeam v0.6.0 — 第一步：全面只读审计 · 问题矩阵

> 审计时间：2026-10-03（续会话）
> 基准状态：`master @ be7be31`，`v0.6.0` tag `f651f73`，真实执行 Gate = `False`（未改动）
> 工作区：19 个已修改文件 + 17 个未跟踪文件（全部保留，不删除、不提交）
> 分类：静态审计 + 代码取证。真实运行结论待 Step 11–14 验证后回填。

## 0. 审计范围与结论摘要

| 模块 | 状态 | 备注 |
|---|---|---|
| Provider（R1） | 捕获+聚合**已存在**，报告层**误报** | `provider.py` 已捕获 `usage`，`counting_provider.py` 已聚合 `token_usage`，但 3 处仍声称"核心丢弃 usage" |
| ToolRegistry / R2 授权 | 健康 | `CAPABILITY_TOOLS` 单一授权源 → `available_for` 广告 → `validate_allowed` 执行前拒绝，双保险 |
| CompletionCriteria（R2/R5） | **缺陷** | 只看 agent 成功数 + artifact 类型，**不**看 `source_gaps` / partial，成功态可能失真 |
| AgentRuntime（R5） | **缺陷** | partial deliverable 无结构化 flag，被调度层记为 SUCCESS |
| Baseline（R3） | harness 已存在，未运行 | `single_agent_baseline.py` 设计合理，待运行 + R1 修正后正确报告成本 |
| Evidence/Source/Synthesis（R4/R6） | 健康 + 待回归 | 已有稳定身份、审计字段、降级不伪造，需全量回归 |
| API / SSE（R7/R8） | 健康 + 设计限制 | SSE 终止态正确；`RunRegistry` 纯内存，重启丢历史（设计限制，可选持久化） |
| 安全/密钥（Step17） | 健康 | `.env` 被 gitignore 忽略，密钥不进日志/结果 |

---

## 1. R1 — Token/Usage 观测：捕获已存在，但报告层系统性误报

| 项 | 内容 |
|---|---|
| 历史来源 | 此前确认 `OpenAILLMProvider` 丢弃 `response.usage`，列为 R1 缺口 |
| 代码证据 | 捕获：`app/llm/provider.py:96-142`（`last_response_meta` 含 `usage`、`usage_available`）。聚合：`validation/counting_provider.py:195-228`（`summary()["token_usage"]` 已按 call 累加 prompt/completion/total）。**误报**：`validation/collect.py:29-39` `UNAVAILABLE_METRICS["token_usage"]` 仍写"核心丢弃"；`validation/single_agent_baseline.py:248-249` `cost_data_available:False` + `cost_data_reason` 错误；`validation/run_scenario.py:63` `REAL_MODE_NOTICE` 声称核心丢弃 usage |
| 是否仍存在 | 部分存在：**捕获与聚合已实现**，但报告/通知/基线仍声称不可用 |
| 影响 | 真实运行的成本与用量被系统性低估/误报，违反"诚实报告"原则 |
| 根因 | 捕获+聚合先于报告层提交；文档与通知未同步更新 |
| 修复方案 | ① `UNAVAILABLE_METRICS["token_usage"]` 改为"仅当无 CountingProvider 观察时 unavailable"；② baseline `cost_data_available` 从 `counting.summary()["token_usage"]` 推导；③ 修正 `REAL_MODE_NOTICE`；④ 新增**可选** pricing 配置（`validation/pricing.py`），仅真实模式且已知价格时计算 cost（不硬编码、不下放离线）；⑤ 新增离线测试：FakeRealProvider 返回 usage → CountingProvider → summary 聚合 → metrics 传播 |
| 可离线测试 | 是（fake real provider，不涉及网络/密钥） |
| 真实环境要求 | 仅"成本金额"字段需真实价格表（可选；缺省 null，绝不编造） |
| 是否阻塞发布 | **否**（捕获已就绪，修正为诚实报告即可） |

---

## 2. R2 — CompletionCriteria 不反映 source_gaps（成功态失真）

| 项 | 内容 |
|---|---|
| 历史来源 | R2：source-need ↔ tool-call 联动；要求"CompletionCriteria 不得将缺口当作成功" |
| 代码证据 | `app/runtime/session.py:54-71` `CompletionCriteria.evaluate` 仅依据 `successful_agents` + `produced_artifact_types`；`app/synthesis/source_policy.py` 已检测 `source_gaps` 并写入 `synthesis_bundle`，但**未回灌** session status |
| 是否仍存在 | **是**（真实模式：若 LLM 未调用已授权 `web_search`，`source_gaps` 非空，但 session 仍可能 `SUCCESS`） |
| 影响 | 真实性/可信度：存在未满足来源需求的产物被标记为成功 |
| 根因 | completion 评估与 source policy 解耦，无回灌路径 |
| 修复方案 | 当 `synthesis_bundle.source_gaps` 非空且 synthesis 可用时，session 状态上限降为 `PARTIAL_SUCCESS`；在 `final_artifact.metadata` 写 `sourcing_gap=True`；新增测试（ScriptedProvider 让 requirement_analyst 不调用 web_search → 断言 status 降为 partial） |
| 可离线测试 | 是（逻辑与运行模式无关，用 ScriptedProvider 即可） |
| 真实环境要求 | 否 |
| 是否阻塞发布 | **是**（真实性硬要求） |

---

## 3. R5 — partial deliverable 在调度层被记为 SUCCESS（成功态失真）

| 项 | 内容 |
|---|---|
| 历史来源 | R5：Agent 不完整交付 & 成功态失真 |
| 代码证据 | `app/runtime/agent_runtime.py:482-489` 预算/迭代耗尽时生成 partial deliverable，但**未**在 `AgentArtifact` 标注 partial；`execute()` 返回 output 后 `session.py:193-198` 仅收集 `result.status is SUCCESS` 的 artifact，调度层将其记为成功 |
| 是否仍存在 | **是**（真实模式预算耗尽 → partial，但 agent 视为成功并计入 `successful_agents`） |
| 影响 | 部分完成被计为完全成功，影响 completion 裁决与 final 质量 |
| 根因 | partial 仅体现在 deliverable 标题/摘要文本，无结构化 flag |
| 修复方案 | 在 `AgentArtifact.metadata` 写 `partial=True`（当 deliverable 为 partial）；`execute_task` 收集时据此将 agent 结果降级/计入 partial 集合；`CompletionCriteria` 据此正确裁决。**离线 mock 不产生 partial，不受影响** |
| 可离线测试 | 是（ScriptedProvider 强制 budget 耗尽） |
| 真实环境要求 | 否 |
| 是否阻塞发布 | **是**（真实性） |

---

## 4. R8 — API 会话内存态（RunRegistry 重启丢历史）+ 不显示丢失任务为 running

| 项 | 内容 |
|---|---|
| 历史来源 | Step8 / Step16：API Session 内存态限制 |
| 代码证据 | `app/api/runs.py:180-241` `RunRegistry` 纯内存；`app/runtime/session.py:5-6` "Purely an in-memory object" |
| 是否仍存在 | 是（重启丢历史，属设计限制） |
| 影响 | UI 重启后任务列表清空；若持久化不当，丢失任务可能显示为 running |
| 根因 | 未持久化（最初的设计选择） |
| 修复方案（可选） | 轻量原子持久化 run 元数据到 `app/api/.run_state.json`；启动时加载并将任何 `"running"` 标记为 `"interrupted"`（**绝不** running/success）；复用文件存储；若不实现则**明确记录为设计限制**（不得谎称"已修复"） |
| 可离线测试 | 是 |
| 真实环境要求 | 否 |
| 是否阻塞发布 | **否**（可记录为设计限制；若实现须保证不显示丢失任务为 running/success） |

---

## 5. R3 — Single-Agent Baseline：harness 已存在，待运行（依赖 R1 修正）

| 项 | 内容 |
|---|---|
| 历史来源 | R3：Baseline 对照未执行 |
| 代码证据 | `validation/single_agent_baseline.py` 已实现，设计为 fair 对照（同 provider/同工具权限/同 task/同预算，仅去掉 DAG+synthesis）；但其 `cost_data_available:False`（依赖 R1 修正） |
| 是否仍存在 | harness 存在，未运行；成本报告复用旧的 unavailable 声明 |
| 影响 | 无法做诚实的 AutoTeam vs 单 agent 对照 |
| 根因 | R3 此前未执行；基线成本报告未随 R1 捕获更新 |
| 修复方案 | R1 修正后，baseline 的 `cost_data_available` 从 counting summary 推导；先跑 **offline** baseline（Scenario A/B）作为对照基线；真实 baseline 在 Gate 临时开启时运行 |
| 可离线测试 | 是（offline baseline 可独立运行） |
| 真实环境要求 | 真实 baseline + 对照需真实 LLM/Search |
| 是否阻塞发布 | **否**（offline baseline 不阻塞；真实 baseline 取决于真实环境可用性） |

---

## 6. R4 / R6 — Evidence / Source / Synthesis 可靠性（已有护栏，待回归）

| 项 | 内容 |
|---|---|
| 历史来源 | R4 Evidence/Source；R6 Synthesis 报告质量 |
| 代码证据 | `app/synthesis/source_identity.py`（稳定身份）、`claim_support.py`（数值/词汇匹配）、`evidence_selection.py`（价值排序+覆盖保证）、`source_policy.py`（声明式缺口）、`pipeline.py`（降级用真实证据，不伪造）均已实现并带审计字段 |
| 是否仍存在 | 审计中未发现新缺陷；主要是回归验证 |
| 影响 | 报告质量可信度 |
| 修复方案 | 全量离线回归 + 真实报告语义审计（Step15） |
| 可离线测试 | 是 |
| 真实环境要求 | 语义审计部分需真实运行产物 |
| 是否阻塞发布 | **否**（回归通过即可） |

---

## 7. R7 — SSE 终止态 / 后台任务状态错变

| 项 | 内容 |
|---|---|
| 历史来源 | R7：SSE 终止态、后台任务不误变状态 |
| 代码证据 | `app/api/routes.py:184-196` 流在 `handle.done` 时发 `event: done` 并关闭——终止态正确；后台线程崩溃走 `_failed_session` 设 `FAILED`——不误变 |
| 是否仍存在 | **未发现缺陷** |
| 影响 | 无 |
| 修复方案 | 维持；R8 若做持久化须保证 done/interrupted 状态正确写入 |
| 可离线测试 | 是 |
| 是否阻塞发布 | **否** |

---

## 8. 安全 / 密钥扫描（Step17 准备）

| 项 | 内容 |
|---|---|
| 历史来源 | 发布前安全扫描 |
| 代码证据 | `.env` 存在（1965 B）且被 `.gitignore` 忽略（**未提交**）；`web_search` 密钥仅在请求头，从不出现在结果/日志；OpenAI client 不记录 key；`counting_provider` 不记录 prompt/response/key |
| 是否仍存在 | 未发现密钥泄漏风险；`.env` 未被跟踪 |
| 影响 | 发布安全 |
| 修复方案 | 正式发布前跑一次密钥扫描（git log + 工作区 + frontend build 产物），确认 `.env` 不进任何产物 |
| 可离线测试 | 是 |
| 是否阻塞发布 | **否** |

---

## 9. 待执行修复优先级（后续步骤）

| 优先级 | 问题 | 是否阻塞 | 离线可验 |
|---|---|---|---|
| P0 | #2 R2 source_gaps → status 降 partial | 阻塞 | 是 |
| P0 | #3 R5 partial flag → status 诚实 | 阻塞 | 是 |
| P1 | #1 R1 报告层误报修正 + 可选 pricing | 不阻塞 | 是 |
| P2 | #4 R8 可选持久化（interrupted 而非 running） | 不阻塞 | 是 |
| P2 | #5 R3 offline baseline 运行 + 真实 baseline | 不阻塞 | 是 |
| — | #6 / #7 / #8 回归 + 语义审计 + 密钥扫描 | 不阻塞 | 是 |

> 注：`REAL_MODE_NOTICE`（`run_scenario.py:63`）提及 `validation/REPORT.md`，该文件当前不存在，属无害的指代残留，随 R1 修正一并清理文案。
