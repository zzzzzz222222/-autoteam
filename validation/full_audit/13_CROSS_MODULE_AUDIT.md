# AutoTeam v0.6.2 Candidate — 13 跨模块端到端审计

> 审计日期：2026-10-03｜只读审计，未新增真实运行。
> 目标：寻找**单模块测试不易发现**的跨模块问题（Core ↔ API ↔ SSE ↔ Vue ↔ Final Result）。

---

## 1. 端到端链路核查

`Task Input → Understanding → Capability → Role → Dynamic Team → DAG → Scheduler → AgentRuntime → Tools → Evidence/Sources → Artifact → Collaboration → Retry/Replan → Assembler → API → SSE → Vue UI → Final Result`

| 环节 | 输入/输出正确 | 状态/事件一致 | 数据有无丢失 | 可否追溯到真实数据 |
|---|---|---|---|---|
| Task → Understanding | ⚠️ 未验证语义 | — | — | 部分（见 04 §6） |
| Capability → Role → Team | ✅ 实证 CAPABILITY_TOOLS 单一源 | — | — | ✅ |
| Team → DAG | ✅ 无环由代码强制 | — | — | ✅ |
| Scheduler | ✅ 拓扑/依赖/传播均正确 | ⚠️ RUNNING 不赋值（014） | — | ✅ |
| AgentRuntime → Tools | ✅ real 路径二次校验 | ⚠️ legacy 旁路（012） | — | ✅ |
| Evidence / Sources | ✅ 0 悬空、URL 全合法 | — | — | ✅ |
| Artifact → Collaboration | ✅ 结构链成立 | ⚠️ partial 当完整（007） | — | ⚠️ 语义使用未证明 |
| Retry / Replan | ⚠️ Retry 正常；**Replan 空操作却发事件**（003） | 不一致 | — | ✅ 代码实证 |
| Assembler → Final | ⚠️ headline 计数夸大（004） | — | ⚠️ 意涵失真 | ✅ |
| API | ⚠️ 失败原因不暴露（008） | — | — | ✅ |
| SSE | ✅ B2 已修，无丢帧 | ✅ | — | ✅ |
| Vue UI | ✅ types 对齐 | ⚠️ 无测试守护（020） | — | ✅ |

---

## 2. 跨模块问题清单（本次实际发现）

### 2.1 ⚠️ Core 执行成功，但 Semaphore 从未被创建（AT-AUDIT-001 的跨模块本质）
- Scheduler 提供了并发机制（`scheduler.py:44`），但**没有任何上层调用点**传入 `max_concurrency`
- 单看 Scheduler 测试（显式传值时）全部通过 → **模块测试无法发现**该问题
- **影响**：生产真实场景无并发保护（详见 03/11 号报告）

### 2.2 ⚠️ Replan 状态前端显示 ≠ 实际行为（AT-AUDIT-003）
- `replan.py` 恒 `replanned=False` → `scheduler.py:82-87` 仅记录事件 → `session.py:201-206` 向 trace 写 `AGENT_REPLANNED`
- 前端消费 trace 事件后，用户看到「已重规划」，但实际**未发生任何拓扑变更**
- 这是典型的「Core 状态 ↔ UI 展示」跨模块不一致

### 2.3 ⚠️ partial Agent 在 Reprlan/UI 层被当作 SUCCESS（AT-AUDIT-007）
- Scheduler 视角：partial = SUCCESS
- Session 视角：仅 verdict 降级（`session.py:271-279`）
- Context 视角：不识别 partial，直接注入下游（`context.py:67-90`）
- UI 视角：B3 已修快照/team 暴露 partial，但**上游 partial 的下游 Agent 仍显示 success**（因其自身未失败）
- **后果**：「任务部分交付却被呈现为完成」的风险链完整成立

### 2.4 ⚠️ Artifact 已生成 → Assembler 可能 distortion（AT-AUDIT-004）
- 8 个 Artifact 全部纳入 Final ✅
- 但 Final 的 `finding_counts` 口径把「多 Agent 一致」也算 supported → 用户读到 90% supported，实际 20% citation-verified
- **这是 Final Deliverable 内容与底层 Artifact/Evidence 语义不一致的典型案例**

### 2.5 ⚠️ Session 失败 → API 无法传达原因（AT-AUDIT-008）
- Core 记录 `handle.error` → snapshot 丢弃 error 字段 → 所有端点不输出
- 用户只看到 failed 或 404

### 2.6 ResultStore 跨 run 污染（AT-AUDIT-002）
- Orchestrator 单例 store → AgentRuntime 每次 record → `status_of` 遍历全部历史
- 第二个 run 的 Live View 可能显示第一个 run 的状态 → **跨任务数据串味**（Core → UI）

### 2.7 SSE ↔ Core Trace 一致性 ✅
- 事件由 Core session 产生并由 API 直接转发，无前端猜测状态；B2 修复后无丢帧
- **未发现**「UI 状态由前端猜测而非事件驱动」的证据（除上述 replan 语义误导）

---

## 3. 已排除的跨模块风险（避免夸大）

以下常见跨模块问题本次**未发现证据**：
- ❌ Api 返回成功但任务未真正启动（`runs.py:216` 同步调用后才替换 session）
- ❌ Team API 与实际执行计划不一致（8/8 一致）
- ❌ Artifact 生成但 Assembler 未使用（8/8 纳入）
- ❌ Evidence 生成但前端遗漏（`EvidenceDto` 已定义并在 FinalResultResponse 中）
- ❌ 重复请求导致重复执行（每请求独立 uuid + 独立 session/thread）
- ❌ SSE 事件乱序/重复

---

## 4. 本模块问题汇总

| 编号 | 严重度 | 标题 | 发现层级 |
|---|---|---|---|
| AT-AUDIT-001 | HIGH | 并发上限跨层缺失 | Scheduler ↔ 三个调用点 |
| AT-AUDIT-002 | HIGH | ResultStore 跨 run 污染 | Orchestrator ↔ UI |
| AT-AUDIT-003 | HIGH | Replan 空操作 vs UI 显示 | Replan ↔ trace ↔ UI |
| AT-AUDIT-004 | HIGH | headline 计数与底层核验不一致 | Synthesis ↔ Final Report |
| AT-AUDIT-007 | MEDIUM | partial 语义在各层丢失 | AgentRuntime ↔ Context ↔ UI |
| AT-AUDIT-008 | MEDIUM | 失败原因在 Core→API 层丢失 | Session ↔ API |

---

## 5. 结论

本次跨模块审计**发现 6 个单模块测试无法覆盖的真实风险**（其中 4 个 HIGH）。它们的共同特征：**每一层单独看都「正确」，但层与层之间的契约缺失或语义被稀释**：

1. Scheduler 有并发能力 → 无人调用（缺：「调用点必须配置」的契约/默认值）
2. Replanner 有能力判断 → 结果被丢弃却仍上报（缺：「事件必须反映真实行为」）
3. partial 有内部标记 → 跨越 module 边界时被忽略（缺：`AgentArtifact.is_partial`）
4. Evidence 有严格核验 → headline 用宽松口径展示（缺：两个 different metrics 分离）
5. ResultStore 有 record → 无 run 隔离（缺：`run_id` 分区）
6. handle.error 有记录 → snapshot 不暴露（缺：DTO 字段）
