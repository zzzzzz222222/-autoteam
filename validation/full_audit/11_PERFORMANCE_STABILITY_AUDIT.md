# AutoTeam v0.6.2 Candidate — 11 性能与稳定性审计

> 审计日期：2026-10-03
> **方法边界**：本阶段**不新增真实运行、不做压测**。结论基于静态分析 + 既有真实运行数据的推导；缺乏数据的性能指标一律标记「尚未测量」，不以推算填充。

---

## 1. 已有真实运行数据（唯一可用于性能分析的样本）

| 指标 | 多 Agent A（`run_f4c191c6`） | 单 Agent Baseline（`baseline_084830666126`） |
|---|---|---|
| Agent 数 | 8（DAG 4 层 / 11 边） | 1 |
| LLM 调用 | 20（blocked 0） | 1 |
| 真实 Web 检索 | 9（0 回退） | 0（基线不调用工具） |
| Evidence | 67 | 8 |
| Sources | 36 | 0 |
| Artifact | 8（rejected 0） | 单段产出 |
| Retry | 2 次（均恢复） | 无 |
| 执行时长 | **193.1s** | **9.0s** |
| 估算成本 | ≈ **$2.416** | ≈ **$0.046** |

**样本局限**：仅 **1 次**真实多 Agent 样本 → **不能得出**「Agent 数量与时长/成本的关系曲线」，也不能得出大规模稳定性结论。相关结论一律标注 **尚未测量**。

---

## 2. 并发与资源消耗（静态分析）

### 2.1 ⚠️ 并发上限在实际产品路径缺失（性能直接影响）

- `scheduler.py:44`：仅当 `max_concurrency` 为真值时创建 Semaphore
- 三条核心路径均未传该参数（`session.py:185-187`、`orchestrator.py:62-64`、`dynamic_team.py:113-115`）
- **后果**：同层所有 ready agent 经 `asyncio.gather` 无限制并发 → 真实 LLM/搜索场景瞬时打满速率限制与连接池，反而**降低**吞吐并可能触发 429
- **判定**：`AT-AUDIT-001 / HIGH`（既是可靠性也是性能问题）

### 2.2 Semaphore 在重试退避期间被持有

- `scheduler.py:104-152`：`async with semaphore` 在 `for attempt` **外层**，退避 `asyncio.sleep(retry_delay)` 发生在锁内
- 小并发 + 长退避场景下显著拖累有效吞吐
- **判定**：`AT-AUDIT-006 / MEDIUM`

### 2.3 Session / Event / Artifact 内存增长

| 对象 | 增长行为 | 风险 | 编号 |
|---|---|---|---|
| `RunRegistry._runs`（`runs.py:189`） | 完成即残留，**无上限/TTL/LRU** | 长稳内存泄漏 | AT-AUDIT-010 |
| `ResultStore.events`（`result_store.py:39-41`） | **只 append 不清理**（单例 orchestrator 路径） | 跨 run 单调增长 + 状态污染 | AT-AUDIT-002 |
| `ExecutionTrace`（`events.py:49-73`） | append-only、无容量上限 | per-session，不全局累积；理论竞态见 AT-AUDIT-025 | INFO |
| Artifact / Evidence / Sources | 随 run 增长，随 session 回收 | 正常 | — |

### 2.4 SSE 长连接

- 轮询间隔 `asyncio.sleep(0.25)`（`routes.py:203`），无忙等 ✅
- 每个连接右上角 4 次/秒轮询；大规模并发连接数下的表现 **尚未测量**

---

## 3. 超时与取消

| 检查 | 结果 |
|---|---|
| 单 agent 超时 | `asyncio.wait_for`（`scheduler.py:163-166`），超时协程被取消 ✅ |
| 全局运行预算 | **无**（`timeout=600` 为单 agent 上限，`runs.py:223`）→ `AT-AUDIT-009` |
| 取消能力 | **无**（全 repo 无 cancel 实现）→ `AT-AUDIT-009` |
| 重试预算 | `max_retries` 硬封顶（session 路径 = 2），无无限重试 ✅ |
| 团队构建阶段超时 | **未验证** → NEEDS_VALIDATION（见 04 号报告 §6） |

---

## 4. 长输出 / 上下文 / Token 预算

- `_complete_with_length_recovery`（`agent_runtime.py:327-370`）提供有界 length 自愈（×1.5、上限 8192、≤2 次）
- ⚠️ 但 `AUTOTEAM_LLM_MAX_TOKENS` 未设置 → `max_tokens=None` → 请求**不发** max_tokens（`provider.py:111-115`）→ **该自愈分支在真实环境从未生效**，仅有离线测试证据 → `AT-AUDIT-021`
- 上下文上限的记忆/裁剪策略：**未核实**（NEEDS_VALIDATION）

---

## 5. 明确标记为「尚未测量」的性能指标

| 指标 | 状态 | 原因 |
|---|---|---|
| Agent 数增长 → 执行时间的曲线 | **尚未测量** | 仅 1 个真实样本（8 agents） |
| DAG 层数对执行过程的影响 | **尚未测量** | 同上 |
| 并发 agent 数 vs 速率限制/失败率 | **尚未测量** | 未压测（安全边界禁止） |
| Session 内存在大规模 run 时的内存曲线 | **尚未测量** | 未做长稳测试 |
| 大规模 Evidence/Source 的装配耗时 | **尚未测量** | 仅 67/36 规模样本 |
| SSE 并发连接上限 | **尚未测量** | 未测 |
| 成本随任务复杂度的变化规律 | **尚未测量** | 仅 1 次成本样本（$2.416） |

> 上述指标不得以「推测值」形式写入报告；本报告一律留空为「尚未测量」。

---

## 6. 性能/稳定性结论

- **已知会在长稳场景劣化的点**：Run Registry 与 ResultStore 均无淘汰机制（010/002）
- **已知会在真实高并发场景暴露的点**：并发上限未启用（001）
- **已知无法优雅终止**（009）
- 其余性能维度因样本与安全边界限制，**尚未测量**，需后续专门的压测补齐。

---

## 7. 本模块问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-001 | HIGH | 核心路径并发上限缺失 | CONFIRMED |
| AT-AUDIT-002 | HIGH | ResultStore 跨 run 累积 | CONFIRMED |
| AT-AUDIT-006 | MEDIUM | 重试退避占用 Semaphore | CONFIRMED |
| AT-AUDIT-009 | MEDIUM | 无全局超时/无取消 | CONFIRMED |
| AT-AUDIT-010 | MEDIUM | Registry 无界增长 | CONFIRMED |
| AT-AUDIT-021 | INFO | length 自愈分支惰性 | DESIGN_LIMITATION |
| AT-AUDIT-026 | INFO | 无性能/并发压测 | TEST_GAP |
| — | INFO | 上下文裁剪策略 / 团队构建阶段超时 | NEEDS_VALIDATION |
