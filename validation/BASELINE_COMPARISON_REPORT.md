# AutoTeam v0.6.0 — 基线对照报告 (BASELINE COMPARISON REPORT)

> 对比对象：动态多 Agent 编排（Multi-Agent） vs 单 Agent 基线（Single-Agent Baseline）
> 分类：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】【人工核验】

---

## 1. 目的

验证"动态多 Agent 编排相较单 Agent 基线"在**可观测维度**（Agent 数、工具调用、证据/来源覆盖、完成度）上的差异，并诚实标注真实成本对照的可行性与结论。

---

## 2. 离线对照结果【实际测试】

运行命令：
- 多 Agent：`validation/run_scenario.py --scenario A --mode offline`（及 `--scenario B`）
- 单 Agent 基线：`validation/single_agent_baseline.py --scenario A --mode offline`

| 维度 | 多 Agent (Scenario A) | 多 Agent (Scenario B) | 单 Agent 基线 (A) |
|------|----------------------|----------------------|-------------------|
| Agent 数量 | 8 | 7 | 1 |
| 成功/失败/跳过 | 8/0/0 | 7/0/0 | 1/0/0 |
| 工具调用（offline_mock） | 7 | 6 | 3 |
| 证据/来源覆盖 | 见 artifacts | 见 artifacts | evidence/source = 3/9 |
| 真实 LLM | 否（Mock） | 否（Mock） | 否（Mock） |
| Verdict | `not_real_llm` | `not_real_llm` | `not_real_llm` |
| 成本数据 | **unavailable（诚实）** | **unavailable（诚实）** | **unavailable（诚实）** |

---

## 3. 成本对照可行性【设计推断 + BLOCKED】

- **离线**：无真实 Provider，`CountingProvider` 不观测 `response.usage`，`pricing.compute_cost` 对离线/未知模型返回 `None` → 成本一律 `null`。**绝不臆测**，如实标注 `unavailable`。
- **真实**：需开启 `REAL_EXECUTION_ENABLED` 且凭据可用。当前二者均不满足（硬闸门不变量 + API 余额耗尽），**真实成本对照 BLOCKED**。
- 结论：离线层面"多 Agent 比单 Agent 调用更多工具、覆盖更多来源"这一**结构差异**已可观测；**量化成本差异**需真实运行，本次无法给出。

---

## 4. 结构差异解读【设计推断】

- 多 Agent（A=8、B=7）通过 DAG 把任务拆给角色化 Agent，工具调用数（7/6）显著高于单 Agent 基线（3），符合"分工带来更细工具使用"的设计预期。
- 单 Agent 基线证据/来源 3/9：单 Agent 在来源覆盖上天然弱于多 Agent 的并行检索分工——这是引入多 Agent 编排的**动机侧证据**（离线层面）。
- 注意：离线 Mock 的工具/来源均为确定性桩数据，仅证明**控制流与计数正确**，不构成质量或真实覆盖率结论。

---

## 5. 真实基线对照状态【BLOCKED】

- 真实 Single-Agent Baseline 与真实多 Agent Scenario A/B 均未执行（见 FINAL_HARDENING_REPORT §7）。
- 解锁后：开启闸门 + 凭据可用 → 同一 Scenario 下分别跑多 Agent 与单 Agent → 用 `pricing.compute_cost` 对比真实 token 成本与来源覆盖 → 产出真实对照。

---

## 6. 诚实声明

本报告所有"成本/真实 LLM"相关结论均标【未验证】或【BLOCKED】。离线数字仅证明工程链路与计数正确，不得被解读为真实质量或成本结论。
