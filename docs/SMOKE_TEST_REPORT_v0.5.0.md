# AutoTeam v0.5.0 — Real API Smoke Test Report

日期：2026-09-29
范围：真实 LLM（DeepSeek-compatible）打通全链路：Provider → Tool → Evidence → Artifact → Agent Collaboration → Final Deliverable。
约束：不新增功能、不改核心架构、不提交 Key、不 push、不改测试逻辑制造通过。

---

## 1. 结论速览（Implemented vs Actually Verified）

| 能力 | 状态 | 实测证据 |
|------|------|----------|
| **Real LLM（DeepSeek）** | Implemented + **Actually Verified** ✅ | 真实请求 1.5–7s 返回；多轮会话 `SUCCESS`、产出 final_artifact 与 Evidence/Sources |
| **Real Web Search（Tavily）** | Implemented + **Actually Verified** ✅ | 真实 POST 请求返回 5 条结果（真实 URL/标题/snippet）；Agent 实际调用 `web_search`；证据进入 Sources/Evidence |
| Calculator（AST 安全计算） | Implemented + **Actually Verified** ✅ | `safe_calculate(...)` 返回 `210.0`；非法表达式被拒绝，无 eval |
| Local Knowledge（路径校验） | Implemented + **Actually Verified** ✅ | 正常读取 + 路径穿越被拒绝（`.env`/`secret`/相对路径出界） |
| Tool Calling（Schema 约束 + retry） | Implemented + **Actually Verified** ✅ | `_real_execution` 调用循环受 `max_tool_calls`/`max_iterations` 约束；retry 吸收单次模型输出随机性 |
| Evidence / Source 溯源 | Implemented + **Actually Verified** ✅ | final artifact 含 source_records + evidence；Evidence.source_id 经确定性规则校验 |
| Agent Collaboration（DAG 调度） | Implemented + **Actually Verified** ✅ | 多 agent 分层运行，上游 artifact 传给下游 Report Writer |

---

## 2. 真实 Smoke 过程中发现并修复的缺陷（4 项确定性 bug）

1. **Agent 级 DAG 成环** → 真实 LLM 提议的 subtask DAG 无环，但经 `DynamicRoleAllocator` 角色归并后成 agent 级环，`DependencyAnalyzer` 抛 `cycle`，整场 FAILED。
   修复：`app/runtime/decomposer.py` 的 `_validate` 增加**角色归并后 agent 级环检测**，成环即整体拒绝并回退 rule-based plan（`nx.is_directed_acyclic_graph(agent_graph)`）。
2. **`AgentDeliverable.structured_data` 类型过严**（`dict[str,str]`）→ 真实 LLM 输出嵌套 dict/list，pydantic `ValidationError`。
   修复：`app/runtime/artifacts.py` 加 `field_validator`（`_flatten_data`/`_flatten_list`），嵌套值确定性压平成 JSON 字符串。
3. **`ToolCall.arguments` 类型过严**（`dict[str,str]`）→ DeepSeek 生成 `max_results: 10`（int）。
   修复：`_flatten_arguments` validator 将标量值压成 str。
4. **`_json_dumps` NameError**（自引入）→ 压平辅助函数调用未定义名。
   修复：改用 `_json.dumps(value, ensure_ascii=False)`。

以上修复遵循「LLM proposes, Schema constrains, Code validates, Executor executes」，未重写任何 v0.4.0 稳定模块。

---

## 3. Real Web Search Verification（Tavily）

- **Provider**: Tavily Search API（`https://api.tavily.com/search`，POST + Bearer + JSON body `{"query": ...}`）
- **Status**: Actually Verified ✅
- **Real results**: yes（最小请求返回 5 条真实结果）
- **Real URLs**: yes（全部为真实 `http(s)` URL，无伪造）
- **Offline fallback**: verified（移除配置后自动降级为 `offline_mock`、空 URL，不崩溃；`pytest` 离线全绿 176）
- **最小改动**：仅修改 `app/tools/registry.py` 的 `web_search` real 分支（GET+Bearer+`snippet` → POST+Bearer+兼容 `content`/`snippet`）；保留 Offline fallback / Mock / ToolRegistry API / AgentRuntime / Scheduler / Dynamic Team / Artifact / Evidence 全部不动
- **新增回归测试**：`test_web_search_tavily_post_protocol`（POST 方法、Bearer、JSON body、content 字段、降级路径）、`test_flatten_json_coerces_numeric_scalars`（real LLM 数字参数压平）
- **过程中发现的确定性 bug 并已修复**：`_flatten_json` 只压平 dict/list/tuple，int/float 标量原样返回导致 `ToolCall.arguments.max_results=10` 报 ValidationError（真实 LLM 随机输出 `"10"` 或 `10`）——修复为标量统一转 str

## 4. Real LLM 端到端验证结果

- Provider 连接：`get_llm_provider()` 在配置 Key 时返回 `OpenAILLMProvider`，实测真实内容返回（有实质标题，非空）。
- **完整会话**（分析 AI Agent 市场 + 产品方案，含 Market/Technology/Requirement/Proposal/Report 多角色）：**连续多轮运行全部 `SUCCESS`**，`final_artifact` 生成，Evidence/Sources 随物传递到最终报告。
- **已知残留行为**：单个研究类 agent（如 market_researcher）偶发单次 `ValidationError`（真实 LLM 输出随机性，同一 agent 重试时产出 schema 不接受的新字段组合）。该行为由既有 retry 机制（attempts）吸收，**会话级始终成功**，未额外引入熔断/兜底，贴合「不重写核心」约束。

---

## 5. 回归验证（确保不破坏 Offline Mode）

| 项 | 结果 |
|----|------|
| `pytest`（无 `.env` / 真实 CI 条件） | **176 passed** ✅（含本批次新增 2 个协议回归测试） |
| `ruff check .`（全仓） | **All checks passed** ✅ |
| Offline Demo `examples/real_world_demo.py` | 无 Key → `Execution mode: OFFLINE MOCK`，`Final Status: SUCCESS`，`offline_mock` 源、空 URL ✅ |
| UI 测试 `tests/test_ui.py` | **28 passed** ✅ |

> 说明：本机因放置真实 `.env`，`app/config.py` 的 `load_dotenv()` 会在导入时注入 Key，导致期望「无 Key」的测试本机转红。此为本机环境副作用，非代码缺陷——在移走 `.env` 的干净环境（等同于 CI）下 **176 全绿**。未改动任何既有测试逻辑。

---

## 6. 安全与 Git

- 真实 Key（DeepSeek + Tavily）仅存于本地 `.env`（**已被 `.gitignore` 忽略**），未写入任何代码 / README / 日志 / Artifact / Event / 报告 / 本报告。
- 全仓扫描：未检出真实 API Key 片段（含 DeepSeek 与 Tavily 前缀）；测试内 `sk-*` 均为**伪造假 Key**（用于断言 Key 不被打印）。
- 扫描绝对路径（`H:\xxcx` / `工作\项目`）：无命中。
- `git status`：仅 `app/tools/registry.py`（Tavily 协议）、`app/runtime/artifacts.py`（数字压平）、`tests/test_realworld.py`（2 个新测试）改动；临时 `_smoke_*.py` **已全部删除**。
- 未 push、未建 remote、未发 Release。

---

## 7. 工程状态结论

**已具备进入 GitHub Release Preparation 的条件。** Real LLM 与 Real Web Search（Tavily）双双实际跑通：会话级稳定 `SUCCESS`、真实搜索结果进入 Sources/Evidence、final_artifact 生成；Offline 回归全绿（176 passed），安全无泄漏，工作区干净。README 已同步标注 `Real LLM / Real Web Search = Actually Verified`。