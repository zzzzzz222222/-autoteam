# AutoTeam v0.6.2 Candidate — 04 动态团队审计（Task Understanding / Capability / Role / Team Formation）

> 审计日期：2026-10-03｜只读审计，未修改任何代码。
> **覆盖声明（重要）**：本模块中路 LLM 参与的语义路径（Task Understanding、Role Allocation 的 LLM 分支）受限于环境，**未能逐行深度审查**（详见 §6 未验证区）。以下内容区分「已核实的实施约束」与「需要在真实运行中验证的语义行为」。

---

## 1. Capability Discovery —— 能力到工具的映射（已核实）

### 1.1 `CAPABILITY_TOOLS` 是唯一授权来源 ✅

- **位置**：`app/runtime/tool_selector.py:26-46`
- **设计约束（引自该文件注释 :7-11）**：
  > `CAPABILITY_TOOLS` is the **single authorisation source**: the AgentFactory derives `AgentSpec.tools` from it, the LLM only ever sees those tools, and `AgentRuntime` re-checks them in code before execution (v0.6.11). Anything a capability is not explicitly granted is denied — a missing entry means "no tools", never "all tools".

**判定**：这是优良且关键的约束 —— 能力与工具权限不存在「缺省放行」。

映射表（实际内容）：

| Capability | 授权工具 |
|---|---|
| MARKET/COMPETITOR/TECHNOLOGY/CUSTOMER 研究、FACT_CHECKING、STRATEGY_PLANNING、REQUIREMENT_ANALYSIS | `web_search` |
| DATA_ANALYSIS、FINANCIAL_ANALYSIS | `data_analyzer`, `calculator` |
| DATABASE/API/BACKEND/CODE/TEST 类 | `schema_validator` / `code_analysis`（本地分析） |
| PROPOSAL_WRITING、REPORT_WRITING | **无工具**（设计如此，见下） |

### 1.2 「无工具」能力有显式理由，避免漏配被误认为能力缺失 ✅

- **位置**：`tool_selector.py:51-81` `CAPABILITY_TOOL_RATIONALE`
- 注释明确要求（:48-50）："A capability absent from `CAPABILITY_TOOLS` MUST say here why it is deliberately tool-free, so an omission can never be mistaken for an oversight."
- PROPOSAL_WRITING / REPORT_WRITING 显式标注 tool-free by design（依赖上游 artifact/evidence 而非独立检索）

**判定**：✅ 未发现「虚假能力声明」—— 每个未授权工具的 capability 都有理由。

### 1.3 执行前的二次权限校验 ✅

- **位置**：`app/tools/registry.py:306-324` `validate_allowed`
- 行为：未注册工具 → `ToolNotFound`；已注册但未授权 → `ToolNotAllowed`；两者均在 `execute` **之前**抛出，不产生实际调用。
- `agent.tools is None` → 拒绝（:314-315）

⚠️ **例外**：legacy orchestrator 路径绕过该校验（`agent_runtime.py:880-893`）→ `AT-AUDIT-012`（详见 03 号报告）。

**总结论**：能力 → 工具 → 权限的链条是清晰的：`CAPABILITY_TOOLS` 为单一授权源，`validate_allowed` 提供代码级二次校验。**未发现能力发现环节的确认缺陷。**

---

## 2. Task Understanding / Role Allocation / Team Formation —— 已核实部分

### 2.1 DAG 有效性由代码强制校验（不依赖 LLM 自觉）✅

- `app/topology/validator.py:29` `is_directed_acyclic_graph`；`:37` `compute_parallel_layers`
- `app/runtime/decomposer.py:258-313`、`app/runtime/dependency.py:64-82`：双重校验子任务/agent DAG 无自环、无缺环、无环
- `app/scheduler/scheduler.py:66-69`：`ready` 为空但仍有 PENDING → `raise RuntimeError`（无法执行的计划会显式失败，而非静默挂起）

**判定**：✅ DAG 环路 / 无法执行的计划在代码层已被拦截。

### 2.2 团队由 LLM 动态生成 + Schema 约束

- 核心原则符合项目定位：“LLM proposes, Schema constrains, Code validates, Executor executes”
- 动态团队成员经 `plan.agents` 交由 scheduler 执行（`dynamic_team.py:113-115`）
- Schema 校验失败处理：`session.py:215-226` 对合并前 artifact 二次 `validate_artifact`，拒绝项记录 `ARTIFACT_REJECTED` 且不进报告 ✅

### 2.3 真实运行的实际团队（本次复核样例）

针对复用样例 `run_f4c191c6`（后续第 07 号报告详述）：实际生成 8 个动态 agent（market_researcher、requirement_analyst、competitor_analyst、data_analyst、technology_analyst、backend_developer、proposal_writer、report_writer），DAG 4 层 / 11 条边，与场景 A 语义对应。

**已核实**：
- agent id 唯一、无重复 ✅
- 生成的 Team 与执行的 Team 一致（8/8 全部产出 artifact）✅
- 非根节点均至少有 1 个上游依赖（11 边 × 8 节点），根层 `dependency_count=0` 一致 ✅
- **未发现硬编码 agent**（尤其静态 vs 动态正则：agent 来自 plan.agents）✅

---

## 3. 已识别问题（本模块）

| 编号 | 严重度 | 标题 | 状态 | 说明 |
|---|---|---|---|---|
| AT-AUDIT-012 | MEDIUM | legacy `_run_tools` 绕过 `agent.tools` 权限 | CONFIRMED | 仅影响 orchestrator 旧路径（详见 03 号报告） |
| AT-AUDIT-024 | INFO | 真实任务样本不足，无法验证团队规模的泛化质量 | TEST_GAP | 仅 1 次真实多 Agent 运行（见 07 号报告），不能推断多任务下 Team/Role 质量稳定性 |

**本模块未发现以下现象的可证实证据**：
- 能力与实际执行不一致（除上述 legacy 例外）
- 硬编码 Agent
- DAG 环路通达 🙀 执行
- 能力匹配失败仍继续（除工具为空的能力，已由设计显式说明）

---

## 4. 设计边界（不应误报为 Bug）

- **角色/Agent 数量取决于 LLM 提议**：appears "合理"不等于语义正确；真实验证需要多样本任务对照（本次仅 1 次真实样本 → `AT-AUDIT-024`）。
- **Tool-free 能力无法自主检索**：这是设计，由 `CAPABILITY_TOOL_RATIONALE` 显式记录。
- **要求 `SOURCED` 的能力可能仍不检索**：工具被授权不等于一定会调用（`_sourcing_requirement_note` 只注入提示要求；历史 D4 设计取舍）→ 该现象在真实运行中导致 8 个来源缺口（见 07 号报告 `AT-AUDIT-011` 相关根因）。

---

## 5. 本模块推断项 vs 实证项

| 结论 | 性质 |
|---|---|
| CAPABILITY_TOOLS 为单一授权源、缺省拒绝 | **实证**（代码 + 注释） |
| validate_allowed 执行前校验 | **实证**（`registry.py:306-324`） |
| DAG 无环由代码强制 | **实证**（validator/decomposer/dependency） |
| Tool-free 能力非遗漏 | **实证**（rationed rationale 表） |
| 团队动态生成非硬编码 | **实证**（8/8 与 plan 一致） |
| Role 分配语义质量、约束保留、子任务覆盖完整性 | **未实证**（LLM 语义路径未逐行审查 + 样本不足） |

---

## 6. 未验证区（诚实披露）

以下项**本次未能充分验证**，建议后续补充：

1. **Task Understanding 的 LLM 路径**：`app/runtime/understanding.py`、`app/analyzer/task_analyzer.py` 未逐行审查内部 prompt/解析逻辑 → 是否存在「关键约束丢失」「过度长输入导致信息衰减」无法证实。
2. **Role Allocation 去重/冲突检测**：`app/runtime/role_allocation.py`、`app/allocator/role_allocator.py` 未逐行审查 → 是否存在 Role 重复/缺失的代码级强制，无法证实。
3. **`build_dynamic_team` 阶段的超时保护**：`AsyncDAGScheduler` 的 timeout 仅作用于 agent 执行，**团队构建阶段的 LLM 调用是否有超时尚未验证**；若无，`execute_task` 理论上可能在该阶段长期阻塞 → NEEDS_VALIDATION。
4. **Schema 校验失败的具体回退行为细节**：仅核实到 `ARTIFACT_REJECTED` 记录，未深究降级路径完整性。

> 上述均未作为 Bug 报告，记录为验证缺口。
