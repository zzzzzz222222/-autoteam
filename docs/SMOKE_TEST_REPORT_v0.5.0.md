# AutoTeam v0.5.0 — Real API Smoke Test Report

日期：2026-09-29
范围：真实 LLM（DeepSeek-compatible）打通全链路：Provider → Tool → Evidence → Artifact → Agent Collaboration → Final Deliverable。
约束：不新增功能、不改核心架构、不提交 Key、不 push、不改测试逻辑制造通过。

---

## 1. 结论速览（Implemented vs Actually Verified）

| 能力 | 状态 | 实测证据 |
|------|------|----------|
| **Real LLM（DeepSeek）** | Implemented + **Actually Verified** ✅ | 真实请求 1.5–7s 返回；多轮会话 `SUCCESS`、产出 final_artifact 与 Evidence/Sources |
| **Real Web Search** | Implemented + **Not Verified** ⚠️ | 无 Web Search API Key 可配置，仅验证离线降级路径（`offline_mock`，空 URL，不伪造） |
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

## 3. Real LLM 端到端验证结果

- Provider 连接：`get_llm_provider()` 在配置 Key 时返回 `OpenAILLMProvider`，实测真实内容返回（有实质标题，非空）。
- **完整会话**（分析 AI Agent 市场 + 产品方案，含 Market/Technology/Requirement/Proposal/Report 多角色）：**连续多轮运行全部 `SUCCESS`**，`final_artifact` 生成，Evidence/Sources 随物传递到最终报告。
- **已知残留行为**：单个研究类 agent（如 market_researcher）偶发单次 `ValidationError`（真实 LLM 输出随机性，同一 agent 重试时产出 schema 不接受的新字段组合）。该行为由既有 retry 机制（attempts）吸收，**会话级始终成功**，未额外引入熔断/兜底，贴合「不重写核心」约束。

---

## 4. 回归验证（确保不破坏 Offline Mode）

| 项 | 结果 |
|----|------|
| `pytest`（无 `.env` / 真实 CI 条件） | **174 passed** ✅ |
| `ruff check .`（全仓） | **All checks passed** ✅ |
| Offline Demo `examples/real_world_demo.py` | 无 Key → `Execution mode: OFFLINE MOCK`，`Final Status: SUCCESS`，`offline_mock` 源、空 URL ✅ |
| UI 测试 `tests/test_ui.py` | **28 passed** ✅ |

> 说明：本机因放置真实 `.env`，`app/config.py` 的 `load_dotenv()` 会在导入时注入 Key，导致两个期望「无 Key」的测试本机转红。此为本机环境副作用，非代码缺陷——在移走 `.env` 的干净环境（等同于 CI）下 **174 全绿**。未改动任何测试逻辑。

---

## 5. 安全与 Git

- 真实 Key 仅存于 `.env`（**已被 `.gitignore` 忽略**），未写入任何代码 / README / 日志 / Artifact / Event / 报告。
- 全仓扫描：未检出真实 API Key 片段（仅以"前缀未落盘"方式核对，未在报告中重现任何真实字符）；`sk-*` 命中仅为测试内**伪造假 Key**（用于断言 Key 不被打印）与一处 docstring 误报。
- 扫描绝对路径（`H:\xxcx` / `工作\项目`）：无命中。
- `git status`：仅 `app/runtime/artifacts.py`、`app/runtime/decomposer.py` 两个修复文件改动；临时 `_smoke_*.py` **已全部删除**；`.env.example` 已恢复。
- 未 push、未建 remote、未发 Release。

---

## 6. 工程状态结论

**已具备进入 GitHub Release Preparation 的条件。** Real LLM 全链路已实际跑通（会话级稳定 `SUCCESS`），Offline 回归全绿，安全无泄漏，工作区干净。唯一未实测的是 Real Web Search（缺厂商 Key），但离线降级路径已验证正确（不伪造 URL/数据），发布不阻塞——README 中相应标记为 `Not Verified` 即可，确保如实标注验证边界。