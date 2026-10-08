# AutoTeam v0.6.2 Candidate — 02 架构审计

> 审计日期：2026-10-03｜只读审计，未修改任何代码。
> 方法：逐文件阅读 + 跨模块导入边核查 + grep 交叉验证，所有结论附 `file:line`。

---

## 1. 模块边界：Core / API / Runtime 的分层

### 1.1 分层结论

| 层 | 位置 | 职责是否清晰 |
|---|---|---|
| 核心引擎（Core） | `app/runtime/session.py::execute_task`(:126) | ✅ 唯一编排入口 |
| 调度 | `app/scheduler/scheduler.py` | ✅ DAG 波次调度 |
| 合成 | `app/synthesis/*` | ✅ 独立子流程 |
| API | `app/api/routes.py` / `runs.py` | ⚠️ 含非平凡投影逻辑 |
| UI | `frontend/`、Streamlit `app/ui*.py` | ✅ 仅展示 |

**主链路**：`POST /api/tasks` → `RunRegistry.start`（`app/api/runs.py:204-236`）→ 后台线程 → `execute_task`（`app/runtime/session.py:126`）→ `AsyncDAGScheduler` + `AgentRuntime` + 合成管线。

### 1.2 发现：API「薄封装」定位与实现有偏差

- **位置**：`app/api/routes.py:70-108`（get_team 组装 agents/explanation）、`:111-137`（artifacts 组装）、`app/api/runs.py:37-157`（snapshot 组装 final 字典，含 20+ 字段）
- **依据**：`app/api/routes.py:4` 文档自称 “No mock data, no re-implemented orchestration.”
- **判定**：**CONFIRMED / LOW**（`AT-AUDIT-017` 相关）—— 业务编排**未**被重复实现（这点优良、诚实），但确有大量「Core 对象 → DTO」投影逻辑。自我定位的“thin”略被夸大，属可接受的架构约定偏差。
- **建议**：在 docstring 明确「thin = 仅投影，不含业务规则」，或将投影收敛到单一模块。

---

## 2. 绕过 Core 的旁路执行

经核查：

- API 不存在绕过 `execute_task` 的执行路径（`runs.py:216` 是唯一调用点）。
- Streamlit 视图（`app/ui_live.py:41`、`app/ui_dynamic.py:42`）与 CLI（`main.py:14-16`）同样走 Core。
- **编排约束**（timeout / retry / offline 强制 mock）全部在 `execute_task` 内部施加，**无法被旁路**：
  - `app/runtime/session.py:149-150`：`provider is None or MockLLMProvider` → 强制 `tool_mode="mock"`
  - `app/api/runs.py:214-219`：offline 模式绝不走真实工具
- **结论**：✅ CLEAN —— 不存在绕过核心约束的旁路执行。

> 例外（已单独立项）：legacy orchestrator 路径 `app/runtime/agent_runtime.py:880-893` 的 `_run_tools` 直接执行 `behavior.tools` 而**未校验 `agent.tools` 权限**，属权限旁路（见 `AT-AUDIT-012`，仅影响旧 orchestrator 路径，不影响 FastAPI session 路径）。

---

## 3. 依赖方向与循环依赖风险

逐边核查结果：**无顶层循环导入** ✅

- `app/api/runs.py:17` → `app/runtime/session.py`
- `app/runtime/session.py:19,231` → scheduler / synthesis（后者为**函数内局部导入** `assemble_from_bundle`，刻意避免顶层依赖）
- `app/runtime/agent_runtime.py` 顶层导入 `app.synthesis.source_identity` / `source_policy`；二者均为**叶子模块**（`source_policy.py:1-2` 仅依赖 `app.runtime.artifacts`，而 `artifacts.py` 无任何 `app.*` 导入）
- `app/synthesis/assembler.py:14` 单向复用 `app.runtime.assembler` 的 `FinalArtifact/FinalSection`

**潜在风险约定**：若未来 `app/runtime/artifacts.py` 反向依赖 synthesis，将形成循环。建议在代码评审中守住「runtime ↔ synthesis 只经叶子模块或局部导入」。记为 INFO。

---

## 4. 状态传递、错误传播与异常边界

| 链路 | 实现 | 判定 |
|---|---|---|
| 后台线程异常 | `runs.py:207-234` try/except/finally，存入 `handle.error`（截断 200 字符），`finally: handle._done_event.set()` | ✅ 不逃逸到请求线程 |
| session 并发读写 | `runs.py:227` 在 `with handle._lock` 内原子替换整个 session；此后 session 无并发写者，`snapshot()`(:37-157) 在锁内读 | ✅ CLEAN（原子替换模式） |
| SSE 游标（B2） | `routes.py:198` `last = last + len(events)` | ✅ CLEAN |

### 4.1 问题：运行失败原因未向客户端暴露

- **位置**：`app/api/runs.py:229-232`（赋值 `handle.error`）、`runs.py:249-261`（`_failed_session.session.error`）、`runs.py:142-157`（`snapshot()` 返回字典**不含 error**）、`app/api/routes.py`（无任何端点读取 error）
- **实际表现**：运行失败时，客户端只能看到 `status=="failed"` 或 `/result` 返回 404（"run finished without a final artifact"），**拿不到失败原因**，无法区分「进程异常」与「确实无最终产物」。
- **判定**：**CONFIRMED / MEDIUM**（`AT-AUDIT-008`）
- **建议**：在 `TaskSnapshot`（`app/api/models.py:29`）增加 `error: str | None`，在 `snapshot()` 回填 `handle.error or session.error`。

---

## 5. 重复实现 / 职责相近模块

### 5.1 两个同名 `assembler.py`

- `app/runtime/assembler.py:31-249`：`FinalArtifact`/`FinalSection` 数据类 + **旧版**确定性装配器 `ArtifactAssembler.assemble`
- `app/synthesis/assembler.py:14,322`：**新版**合成装配器 `assemble_from_bundle`，并**复用**前者的 `FinalArtifact/FinalSection`（单向依赖）
- **实际执行路径**：`app/runtime/session.py:230-259` **两者都用** —— 先跑合成管线 + `assemble_from_bundle`（主），合成异常时降级到 `ArtifactAssembler().assemble`（兜底 `:253`）
- **判定**：**CONFIRMED / LOW**（`AT-AUDIT-016`）—— 数据类单一来源、功能正确，但同名双文件易误改。
- **建议**：将数据类抽到独立模块，或明确层级命名。

### 5.2 多个 `models.py` 命名分散

`app/models/*`（领域）、`app/runtime/models.py`（agent 结构化产出 schema）、`app/scheduler/models.py`、`app/synthesis/models.py`、`app/api/models.py`（DTO）。核心数据类单一来源、跨层复用良好，属**可读性/维护**问题 → LOW。

---

## 6. 资源释放、任务终止与服务入口

### 6.1 无取消 / 终止端点（重要）

- **位置**：`app/api/routes.py:46-209` 仅有 health/list/create/get/team/artifacts/result/events/stream，**无 cancel/delete/stop**
- **grep 结果**：`app/api/` 下检索 `cancel|terminate|stop|delete|shutdown` → **无匹配**
- `app/scheduler/scheduler.py:163-166` 的 `_with_timeout` 仅作用于**单次** `executor.execute`；`runs.py:223` 传入 `timeout=600` 是**每 agent 上限**，非全局预算
- **影响**：运行只能自然跑完或被单 agent 超时掐断；进行中的 LLM/工具调用无法中断（仅进程退出时 daemon 线程被强杀）
- **判定**：**CONFIRMED / MEDIUM**（`AT-AUDIT-009`）

### 6.2 Run Registry 无界增长

- **位置**：`app/api/runs.py:185-202`，`self._runs: dict` 仅追加，**无 pop/del、无上限、无 TTL、无 LRU**
- `list()`(:242-246) 遍历全部，响应随运行数线性增长
- **判定**：**CONFIRMED / MEDIUM**（`AT-AUDIT-010`）—— 长稳内存风险

### 6.3 模块级单例 Registry 对多 worker 不友好

- **位置**：`app/api/routes.py:27` `registry = RunRegistry()`（模块级）、`app/api/main.py:5` 已声明 “single process in production”
- **影响**：若 `uvicorn --workers N`，POST 落在 worker A 而 GET 可能被路由到 worker B → 404。默认配置安全，但易被运维误操作打破
- **判定**：**DESIGN_LIMITATION / MEDIUM**（`AT-AUDIT-013`）
- **建议**：文档显式声明禁止多 worker / 需粘性会话，或外置状态。

### 6.4 服务入口

- Web 唯一 ASGI 入口：`app.api.main:app`（`scripts/start_web.py:24` 以 uvicorn 启动）✅ CLEAN
- 但项目整体存在多个**独立**入口：`main.py`（CLI）、`app/ui.py`、`app/ui_dynamic.py`、`app/ui_live.py`（Streamlit），并非同一进程 —— 部署文档应区分（INFO）。

---

## 7. 数据模型跨模块一致性

| 检查 | 结果 |
|---|---|
| 核心数据类单一来源 | ✅ `FinalArtifact`/`FinalSection`/`AgentArtifact`/`AgentResult`/`ReportBundle` 各由一处定义 |
| 两个状态枚举语义重叠 | ⚠️ `app/scheduler/models.py:12-18` `ExecutionStatus` vs `app/runtime/session.py:33-38` `SessionStatus`，均有 pending/running/success/failed；代码以 `.value` 字符串转接（`runs.py:70,86,148`），运行正确但语义重复 → LOW（`AT-AUDIT-019`） |
| API DTO ↔ snapshot 字典键耦合 | ⚠️ `app/api/models.py:77-94` 经 `final.get("findings") or []` 读取 `runs.py:85-141` 手拼字典；键改名会**静默**落默认值，无编译期保证 → LOW（`AT-AUDIT-017`） |
| `TeamResponse.agents` 弱类型 | ⚠️ `app/api/models.py:46-53` 为 `list[dict[str, Any]]`，且前端 `types.ts:169` 的 `explanation.agents` 为 `unknown[]` → LOW（`AT-AUDIT-018`） |

---

## 8. 架构层「已核查且确认干净」的项

- ✅ **无循环导入**（第 3 节）
- ✅ **无绕过 Core 的旁路编排**（第 2 节）
- ✅ **session 并发读写安全**（原子替换 + 只读快照）
- ✅ **SSE 游标修复到位**（B2，无忙等，`await asyncio.sleep(0.25)`）
- ✅ **脱机安全**：无 provider/key 时强制 mock，绝不触碰真实工具
- ✅ **Web 服务入口单一**
- ✅ **核心数据类单一来源**

---

## 9. 本架构层问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-008 | MEDIUM | 运行失败原因未向客户端暴露 | CONFIRMED |
| AT-AUDIT-009 | MEDIUM | 无取消/终止端点，超时仅为单 agent 上限 | CONFIRMED |
| AT-AUDIT-010 | MEDIUM | Run Registry 无界增长无淘汰 | CONFIRMED |
| AT-AUDIT-013 | MEDIUM | 模块级单例 Registry 不支持多 worker | DESIGN_LIMITATION |
| AT-AUDIT-012 | MEDIUM | legacy `_run_tools` 绕过 `agent.tools` 权限 | CONFIRMED |
| AT-AUDIT-016 | LOW | 两个同名 `assembler.py` | CONFIRMED |
| AT-AUDIT-017 | LOW | DTO 与 snapshot 字典键耦合，无编译期保证 | CONFIRMED |
| AT-AUDIT-018 | LOW | `TeamResponse.agents` / `explanation.agents` 弱类型 | CONFIRMED |
| AT-AUDIT-019 | LOW | `ExecutionStatus` 与 `SessionStatus` 语义重叠 | CONFIRMED |

（完整问题定义见 `15_FULL_PROJECT_ISSUE_LIST.md`）
