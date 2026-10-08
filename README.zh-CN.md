[简体中文](README.zh-CN.md) | [English](README.md)

# AutoTeam

### 自适应多智能体编排

> ⚠️ **本中文说明暂未同步到 v0.6.2。** 最新的架构、能力、测试结果与限制请以
> [README.md](README.md) 和 [RELEASE_NOTES_v0.6.2.md](RELEASE_NOTES_v0.6.2.md) 为准；
> 以下内容描述的是早期版本，可能已过时。

> AutoTeam 动态组建智能体团队、生成经过校验的协作拓扑、异步执行、从故障中恢复，并评估拓扑行为。

**状态：v0.1.0 已发布；v0.2.0（AutoTeam Research）、v0.3.0（Dynamic Team Intelligence）与 v0.4.0（Autonomous Task Completion）叠加于其上。** AutoTeam 是一个离线、确定性的演示，目的是让多智能体编排的结构变得可见、可测试。它不是生产级智能体运行时，不是托管服务，也不是真实世界的 LLM 基准。详见 [局限性](#局限性)。

### 一段话讲清楚

一个任务被分析为**能力** → 能力被归类为**角色** → 角色组成**智能体团队** → 生成三种**候选拓扑** → 每种都**作为 DAG 校验** → 由异步调度器**执行**（含**重试 / 重规划**）→ 结果**按指标对比** → 全部在 **Streamlit UI** 中呈现。

---

## AutoTeam 是什么？

AutoTeam 探索一个 AI 系统如何**动态构建并执行多智能体团队**，而不是依赖一套写死的工作流。

你给它一个任务。它决定这个任务需要哪些能力、哪些角色覆盖这些能力、这些角色应如何协作、这张协作图是否真的合法，以及哪个候选拓扑在真正跑完之后表现更好。

核心能力：

- **动态团队组建** —— 智能体团队按任务分配，而非硬编码
- **动态协作拓扑** —— 每个团队生成 Chain / Star / Hierarchical 三种候选
- **DAG 校验** —— 每个候选在调度前都作为有向无环图被检查
- **异步执行** —— 异步 DAG 调度器并发运行相互独立的智能体
- **重试 / 重规划** —— 失败先本地重试，再回退到受校验器约束的恢复
- **拓扑评估** —— 候选拓扑各自独立执行，并按指标对比
- **Streamlit 可视化** —— 整条流水线在一屏内可见

它完全离线运行。无需 API key、无需数据库、无需外部服务。

---

## 为什么需要 AutoTeam？

传统的多智能体系统通常是这样的：

```
任务 → 固定智能体 → 固定工作流 → 固定图
```

协作结构是一个由人在最开始一次性决定的实现细节。

AutoTeam 把它当作问题的一部分：

```
任务 → 分析能力 → 分配角色 → 组建智能体团队
     → 生成候选拓扑 → 校验 DAG → 执行 → 恢复 → 评估
```

> **协作结构被当作问题的一部分，而不是固定的实现细节。**

| | 传统多智能体演示 | AutoTeam |
|---|---|---|
| 团队 | 硬编码的智能体列表 | 按任务从所需能力分配 |
| 协作 | 固定的链 / 静态图 | 每个团队生成三种候选拓扑 |
| 图的正确性 | 假设成立 | 作为 DAG 校验（无环、可达、无自环） |
| 执行 | 顺序或框架托管 | 带并发限制与超时的异步 DAG 调度器 |
| 失败 | 崩溃或静默重试 | 重试 → 确定性重规划 → 下游跳过 |
| 对比 | "能跑就行" | 每个拓扑的原始指标，仅按指标分别报告 |

---

## 架构

```
用户任务
   │
   ▼
任务分析器                基于规则的离线检测，可选 LLM
   │
   ▼
能力
   │
   ▼
角色分配器                能力覆盖 → AgentSpec[]
   │
   ▼
智能体团队
   │
   ▼
拓扑生成器
   ├── Chain
   ├── Star
   └── Hierarchical
   │
   ▼
DAG 校验器                 无环 / 可达 / 无自环 → 并行层
   │
   ▼
异步 DAG 调度器
   ├── 重试                  仅重跑失败的智能体
   └── 重规划                重试耗尽后记录恢复状态
   │
   ▼
执行结果                    PENDING / READY / RUNNING / SUCCESS / FAILED / SKIPPED
   │
   ▼
拓扑评估                    指标 → 各指标领先者
   │
   ▼
Streamlit UI
```

---

## 核心设计原则

> **LLM 提议，Schema 约束，代码校验，执行器执行。**

| 层 | 职责 |
|---|---|
| **LLM** | 提议分析结果或结构化建议 |
| **Schema** | 约束数据形态（Pydantic 模型） |
| **代码** | 校验拓扑、依赖与执行条件 |
| **执行器** | 真正运行智能体 |

LLM 绝不会被信任去改动图。任何拓扑变更都必须通过同一个 DAG 校验器。

**离线模式无需 API key。** 没有 `LLM_API_KEY` 时，分析器保持完全基于规则且确定性。LLM 是可选能力，而非必需项。

---

## 能力 → 角色 → 智能体

这三者并不相同，且这种区分是刻意为之的设计点：

- **能力** —— 系统需要能够做到什么
- **角色** —— 一组相关能力的 coherent 聚合
- **智能体** —— 承载某个角色的可执行单元

```
能力：
  competitor_analysis
  market_research
        ↓
角色：
  Competitor Analyst
        ↓
智能体：
  Competitor Analyst Agent
```

`能力 ≠ 角色 ≠ 智能体。` 分配器用角色模板覆盖所需能力，对未被覆盖的部分回退到通用智能体（General Agent）—— 因此智能体的数量是**结果**，而不是一项配置。

---

## 拓扑

拓扑是智能体 ID 之上的一个 DAG。AutoTeam 为每个团队生成三种候选。

**Chain** —— `A → B → C → D`

- 顺序执行
- 结构并行度低
- 依赖关系简单

**Star**

```
      B
      ↑
C  ←  A  →  D
```

- 潜在并行度高
- 以中心根节点为依赖

**Hierarchical**

```
      A
     / \
    B   C
    |
    D
```

- 多层依赖
- 并行度适中

不同拓扑暴露不同的执行特征。AutoTeam 不假设某一种永远更好——它实测它们。

---

## 执行与恢复

调度器跟踪六种状态：`PENDING`、`READY`、`RUNNING`、`SUCCESS`、`FAILED`、`SKIPPED`。

**Day 4 的恢复分为两层：**

- **重试** —— 重新执行当前智能体。*重试不改变 DAG。*
- **重规划** —— 在重试耗尽后运行。*重规划受校验器约束。*

当不存在可行的恢复路径时，重规划器会记录这一事实，失败节点的每个后代都变为 `SKIPPED` 并附带明确原因。绝不会执行任意的图重写。

---

## 评估

每个候选各自独立执行，再按原始指标对比：

| 指标 | 含义 |
|---|---|
| 耗时 | 整次运行的墙钟时间 |
| 成功率 | 成功完成的智能体占比 |
| 失败率 | 所有重试后仍失败的智能体占比 |
| 跳过 | 因上游依赖失败而被跳过的智能体 |
| 恢复 | 仅在重试后才成功的智能体 |
| 最大并发 | 观测到同时运行的最大智能体数 |
| 结构并行度 | 最宽并行层相对团队规模的比例 |

AutoTeam **不使用**：

- 加权合成评分
- LLM 裁判
- 黑盒排名

它报告的是**透明、按指标的对比**——包括确定性的平局，因此成功率上的三方平局会如实地显示为三方平局。

---

## 演示

```bash
streamlit run app/ui.py
```

UI 在一屏内走完整条流水线：

1. **任务** —— 选择预设或自行输入，然后点击 `分析并组建团队`
2. **团队组建** —— 左侧是能力，右侧是分配出的智能体卡片
3. **候选拓扑** —— 每个候选的智能体 / 边 / 层数 / 结构并行度
4. **拓扑图** —— 所选 DAG 的分层 SVG
5. **执行** —— `运行全部拓扑`，可选故障模拟
6. **执行结果** —— 每个智能体的状态、尝试次数、重试明细、跳过原因、时间线
7. **评估** —— 完整指标表
8. **对比** —— 耗时最短、成功率最高、并行度最高、最可靠

**故障模拟** 原样复用 Day 4。可选两种场景：

- *重试后成功* —— `第 1 次：FAILED → 第 2 次：SUCCESS`，计为一个已恢复智能体
- *重试耗尽* —— 该智能体以 `FAILED` 结束，每个后代变为 `SKIPPED` 并附带明确原因

---

## 演示结果

任务：*"研究 AI Agent 市场，分析竞争对手与财务数据，并撰写市场报告。"*

组建团队：`Market Researcher`、`Competitor Analyst`、`Financial Analyst`、`Report Writer` —— 由 5 个被识别出的能力组成的 4 智能体团队。Mock 执行器，延迟 `0.05s`。

| 指标 | Chain | Star | Hierarchical |
|---|---|---|---|
| 耗时 | ~0.251s | ~0.123s | ~0.187s |
| 最大并发 | 1 | 3 | 2 |
| 结构并行度 | 25% | 75% | 50% |

各指标领先者：耗时最短 `star`、并行度最高 `star`、成功率最高与最可靠——三方平局。

> 这些数字由确定性的本地 mock 执行器产生，仅用于演示拓扑行为。它们不是真实世界的 LLM 性能基准。

演示任务的结果取决于当前的能力词表与基于规则的离线分析器——不同的任务会产生不同规模的团队。

---

## AutoTeam Research（v0.2.0）

v0.2.0 是在稳定的 v0.1.0 引擎之上叠加的**杀手级演示层**。它没有重写编排引擎，而是在 `AsyncDAGScheduler` 之上新增了真实智能体运行时、任务拆解、研究工具与结果聚合。

核心原则不变：**LLM 提议，Schema 约束，代码校验，调度器执行。**

### 它做什么

给一个研究任务，它会：

1. **拆解**任务为受 Schema 约束的 `SubtaskPlan`（规划者角色）
2. **组建团队**——每个子任务一个智能体（研究 Agent / 竞品分析师 / 技术分析师 / 报告撰写者），直接由计划派生
3. **构建协作 DAG**——边遵循每个子任务的 `depends_on`；计划的扇入结构变成并行层
4. **执行**——通过**未改动**的 `AsyncDAGScheduler` 与新 `AgentRuntime` 执行器（重试 / 重规划 / 评估自动生效）
5. **智能体间传递结果**——每个智能体通过 `ExecutionContext.get_upstream_results` 读取上游
6. **聚合**为最终的 `ResearchReport`

### 运行实时视图

```bash
streamlit run app/ui_live.py
```

页面呈现拆解结果、团队/拓扑、智能体**实时状态**（pending → running → success/failed/skipped）以及最终报告。默认**完全离线**运行，无需 API Key。

### 默认离线，真实 LLM 可选

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `AUTOTEAM_LLM_PROVIDER` | `mock`（离线）或 `openai` / `deepseek` | `mock` |
| `AUTOTEAM_API_KEY` | 真实提供方的 API Key | _无 → 回退到 mock_ |
| `AUTOTEAM_LLM_MODEL` | 模型 id（如 `deepseek-chat`） | 提供方默认 |
| `AUTOTEAM_LLM_BASE_URL` | OpenAI 兼容 base URL | DeepSeek 端点 |
| `AUTOTEAM_WEB_SEARCH_URL` / `AUTOTEAM_WEB_SEARCH_API_KEY` | 真实网页搜索后端（Tavily 兼容，POST + Bearer） | _无 → 离线 mock 搜索_ |

无任何 Key 时，演示使用 `MockLLMProvider`（确定性结构化桩）与 `mock_search`，整个研究管线无需联网即可运行。

### 离线示例输出

对 *"分析中国跨境电商 SaaS 市场的竞争格局与技术趋势"* 这类任务，离线管线会产出：

- **团队：** `research_agent`、`competitor_analyst`、`technology_analyst`、`report_writer`
- **拓扑：** 2 个并行层——`[research, competitor, technology]` → `[report_writer]`
- **报告：** 聚合的 `market_overview` / `competitors` / `technology` 章节以及收集的 `sources`

> 离线模式下的数字与文本均为确定性桩，用于证明编排、结果传递与聚合机制——而非真实研究质量。

---

## 动态团队智能（v0.3.0）

v0.3.0 证明核心命题：**AutoTeam 不是"固定几个 Agent 跑固定流程"。** 一个任务会被动态转换为：

```
Task → 任务理解 → 能力发现 → 任务拆解
     → 角色分配 → 动态 Agent 生成 → 工具选择
     → 依赖分析 → 执行计划 → 现有 Scheduler → 现有 Runtime
```

不同任务产生**明显不同的团队**——能力、角色、智能体、工具、依赖、执行分层全部不同。没有任何写死：团队是任务的**结果**，不是配置。

### 新增模块

| 模块 | 职责 |
|---|---|
| `app/runtime/understanding.py` | `TaskUnderstanding`——领域、目标、预期产出、能力集合 |
| `app/runtime/capability_discovery.py` | 确定性关键词规则（+ 可选 LLM 增强，按能力词表校验） |
| `app/runtime/decomposer.py` → `DynamicDecomposer` | 按 stage 拆解为 `DynamicSubtask`，依赖为**结构化 id**（与 v0.2.0 `TaskDecomposer` 向后兼容） |
| `app/runtime/role_allocation.py` | 子任务合并为角色——一个角色可承担多个子任务（如 Backend Developer = API 设计 + 实现） |
| `app/runtime/agent_factory.py` | `DynamicAgentSpec`（继承 `AgentSpec`）：system prompt、工具、输入/输出 schema、结构化创建理由 |
| `app/runtime/tool_selector.py` | 能力 → 工具映射，按 `ToolRegistry` 过滤——工具不可能被凭空创造 |
| `app/runtime/dependency.py` | 校验依赖 DAG（缺失/自依赖/环），映射到智能体图，用现有 validator 计算分层 |
| `app/runtime/dynamic_team.py` | `build_dynamic_team(task)` → `ExecutionPlan`（含 `TeamFormationExplanation`）；`run_dynamic_team(plan)` 经现有调度器执行 |

"Why this team?" 解释只保存结构化、可展示的理由——不记录 LLM 隐藏推理。

### 三个离线 Demo，三个不同团队

| | Demo A · AI Agent 市场分析 | Demo B · FastAPI 电商后端 | Demo C · SaaS 市场进入策略 |
|---|---|---|---|
| 领域 | market_research | software_engineering | business_strategy |
| 能力 | 市场、竞品、技术、数据、报告 | 需求、架构、API、数据库、后端、测试 | 市场、策略、客户、财务、方案 |
| 角色 | Market Researcher · Competitor Analyst · Data Analyst · Technology Analyst · Report Writer | Requirement Analyst · System Architect · Backend Developer · Database Engineer · Test Engineer | Customer Researcher · Market Researcher · Strategy Planner · Financial Analyst · Proposal Writer |
| 工具 | web_search · data_analyzer · calculator | schema_validator · code_analysis | web_search · data_analyzer · calculator |
| 分层 | 3 | 5 | 4 |

运行：

```bash
python examples/dynamic_team_demo.py
streamlit run app/ui_dynamic.py   # 动态团队视图（含 "Why this team?"）
```

离线模式使用确定性规则发现与 mock provider。真实 LLM 模式（配置 `AUTOTEAM_API_KEY`）由 LLM 提议理解与计划——代码仍然校验能力、依赖与 DAG，任何违例都回退到确定性规则。全文不声称任何真实研究质量基准。

---

## 自主任务完成（v0.4.0）

v0.3.0 证明了不同任务产生不同团队。v0.4.0 证明下一个命题：**这些团队能真正协作完成复杂任务，并交付可阅读的成果。**

```
Task → 理解 → 能力 → 角色 → Agent → 工具 → 依赖
     → 执行 → 协作（上游 Artifact）→ 失败/重试/重规划
     → Artifact 组装 → 最终成果（可读 Markdown）
```

### 新增能力

| 模块 | 职责 |
|---|---|
| `app/runtime/session.py` | `TaskExecutionSession`——运行生命周期（PENDING/RUNNING/SUCCESS/FAILED/PARTIAL_SUCCESS）、确定性 `CompletionCriteria`（无 LLM Judge、无评分） |
| `app/runtime/artifacts.py` | 统一 `AgentArtifact`——id、类型、内容、`structured_data`、**依赖**（上游 artifact id）、`source_type: offline_mock / llm` |
| `app/runtime/context.py` | 上下文装配——每个 Agent 只获得**传递性上游 Artifact** 与自身子任务信息，绝不塞入整个系统状态 |
| `app/runtime/assembler.py` | `ArtifactAssembler` → `FinalArtifact.to_markdown()`——章节结构由 Artifact 自身派生，无固定模板、无万能 Writer |
| `app/runtime/events.py` | 结构化执行轨迹——`TASK_STARTED / TEAM_FORMED / AGENT_STARTED / TOOL_CALLED / AGENT_OUTPUT / ARTIFACT_CREATED / AGENT_RETRY / AGENT_REPLANNED / TASK_COMPLETED` |
| `app/ui_live.py` | Live View 升级——运行信息、时间线、协作、Artifact、最终 Markdown（查看 + 保存） |

### 可证明的协作

下游 Agent 真实读取上游 Artifact：System Architect 的 Artifact 携带 `architecture_decision = modular_fastapi`，Backend Developer 读取后产出 `backend_plan`，Test Engineer 读取两者，最终 Markdown 包含全部关键数据。`tests/test_autonomous.py::test_downstream_agent_receives_upstream_artifact` 断言了这一切。

失败恢复完全复用现有引擎：Database Engineer 失败一次后重试成功（`AGENT_RETRY`）；持续失败则被重规划、下游 `SKIPPED`，Session 依据透明的完成判据以 `PARTIAL_SUCCESS` 结束。

### Killer Demo

```bash
python examples/autonomous_task_demo.py
```

输出运行 ID、动态团队、执行分层、逐 Agent 结果、Artifact 依赖链、失败恢复演示，并把最终成果保存为可读 Markdown（`autoteam_output/<run_id>.md`）。

> 离线模式默认运行：Agent 输出与工具结果均为标注 `offline_mock` 的确定性桩。发布前已用真实 DeepSeek 兼容端点实测过真实 LLM 链路、并用真实 Tavily 端点实测过真实 Web Search（详见英文版 README 的 Real LLM Verification）；Key 由用户配置在本地 `.env`（gitignored），不写入仓库。Web Search 离线降级（`offline_mock`、空 URL、不伪造数据）同样已验证。

---

## 快速开始

```bash
git clone <repository>
cd autoteam
```

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

```bash
pip install -e ".[ui,dev]"
streamlit run app/ui.py
```

---

## 命令行 / 离线模式

运行任何演示都不需要 API key、数据库、Redis 或外部服务。

```bash
python main.py "为一款新的 AI 产品撰写市场研究报告。"
python examples/demo.py
python examples/topology_demo.py
python examples/scheduler_demo.py
python examples/recovery_demo.py
python examples/evaluation_demo.py
```

如果你希望用真实 LLM 驱动任务分析，请将 `.env.example` 复制为 `.env` 并填写 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。这严格可选——没有它，分析器仍保持基于规则且离线。

---

## 项目结构

```
app/
├── models/         Pydantic 模式：Task、Capability、AgentSpec、Topology
├── analyzer/       任务分析 —— 规则优先，可选 LLM
├── allocator/      能力 → 角色 → AgentSpec 分配
├── llm/            可选的 OpenAI 兼容结构化输出客户端
├── topology/       模板、生成器、DAG 校验器
├── scheduler/      异步 DAG 调度器、重试、重规划、mock 执行器
├── evaluation/     指标收集器、策略、评估器、基准
├── demo/           展示层：tasks、service、render、Streamlit 页面
├── config.py
└── ui.py           Streamlit 入口

examples/
├── demo.py
├── topology_demo.py
├── scheduler_demo.py
├── recovery_demo.py
└── evaluation_demo.py

tests/
.github/
└── workflows/
    └── ci.yml
```

`app/demo/` 是一个纯适配器：`service.py` 把现有组件接在一起，`render.py` 产出 SVG/HTML，`app.py` 负责渲染。那里没有重复任何调度器、拓扑、重试或评估逻辑。

---

## 测试

```bash
pytest -q
ruff check .
```

```
测试：138 passed
Ruff：PASS
CI：  Python 3.11 / 3.12
```

- Day 1-5：44 个测试
- Day 6：27 个测试（`tests/test_ui.py` —— 服务函数、离线模式、故障模拟、评估流水线、SVG/时间线渲染、语言切换、Live View）
- v0.2.0：11 个测试（`tests/test_research.py` —— 拆解、运行时、Provider、工具、结果传递、报告聚合、失败/恢复、离线全链路）
- v0.3.0：28 个测试（`tests/test_dynamic_team.py` —— 任务理解、能力发现、动态拆解、角色分配、Agent 工厂、工具选择、依赖分析含环/缺失/自依赖检测、执行计划、多任务差异化、离线 E2E、UI）
- v0.4.0：28 个测试（`tests/test_autonomous.py` —— Session 生命周期、Artifact、上下文装配、"下游读取上游"协作证明、Artifact 依赖链、组装器、完成判据、事件轨迹、重试/重规划集成、部分失败、三类任务、Killer Demo 链路、UI）
- 中英文切换（i18n）：UI 文案在 English / 简体中文之间切换，且切换语言不改变演示所组建的团队与拓扑

`tests/test_ui.py` 刻意不断言 Streamlit 的 HTML 细节。CI 在 Python 3.11 与 3.12 上运行 ruff、pytest、UI 导入冒烟测试与离线演示——无需 API key、无网络、无外部服务。

---

## 局限性

这是一次架构探索，而非生产级编排平台。当前边界：

- 离线任务分析是**基于规则**的，刻意保持轻量
- 拓扑候选目前使用**预定义模板**（Chain / Star / Hierarchical）
- 智能体执行使用**确定性的 mock 执行器**做离线演示
- 评估聚焦**结构与执行指标**，而非输出质量
- 没有生产级分布式执行层
- 没有持久化的工作流状态
- 没有真实世界的 LLM 性能基准

---

## 未来工作

方向，而非承诺：

- LLM 辅助的能力发现
- 更多拓扑模板
- 分布式执行
- 持久化工作流状态
- 真实世界基准套件
- 成本感知的拓扑选择
- 动态拓扑自适应
- 生产级智能体执行器

---

## 路线图

- [x] Day 1 —— 动态团队组建
- [x] Day 2 —— 动态拓扑生成
- [x] Day 3 —— 异步 DAG 调度器
- [x] Day 4 —— 重试与重规划
- [x] Day 5 —— 拓扑评估
- [x] Day 6 —— Streamlit 可视化
- [x] 中英文切换（UI i18n）
- [x] v0.1.0 Release
- [x] v0.2.0 —— AutoTeam Research：在引擎之上叠加真实 Agent Runtime（任务拆解、LLM Provider、工具注册表、结果存储、研究报告、实时视图）
- [x] v0.3.0 —— Dynamic Team Intelligence：Task → Capability → Role → Agent → Tool → Dependency → Execution Plan（三个差异化离线 Demo）
- [x] v0.4.0 —— Autonomous Task Completion：基于上游 Artifact 的智能体协作、Artifact 组装为可读最终成果、确定性完成判据、执行轨迹、失败/重试/重规划演示
