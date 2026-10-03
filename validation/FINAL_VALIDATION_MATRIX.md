# AutoTeam v0.6.0 — 最终验收矩阵 (FINAL VALIDATION MATRIX)

> 对应授权任务 22 步。状态：✅ 达成 / ⚠️ 部分达成 / ❌ 未达成 / 🔒 BLOCKED（不执行）/ — 不适用
> 分类：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】【人工核验】

| # | 验收项（任务步骤） | 状态 | 证据 | 分类 |
|---|-------------------|------|------|------|
| 1 | 全面只读审计 + 8 类问题矩阵 | ✅ | `validation/AUDIT_MATRIX.md`（8 类，含 2 个真阻断 R2/R5） | 静态审计 |
| 2 | R1 token usage 捕获 | ✅ | 核心已在 `provider.py`/`counting_provider.py` 捕获；上报层修复（`collect.py`/`run_scenario.py`） | 实际测试 |
| 3 | R2 来源需求↔工具调用衔接 | ✅(离线) / 🔒(真实) | `tool_selector.py` 单一授权源；离线守卫回归通过；真实调用受闸门约束 | 实际测试 / BLOCKED |
| 4 | Evidence/Source 守卫 + 回归 | ✅ | 既有守卫（`source_identity`/`claim_support`/`evidence_selection`/`source_policy`）回归通过 | 实际测试 |
| 5 | Agent 不完整交付 & 成功态失真修复 | ✅ | `agent_runtime.py`（partial 5 元组 + 元数据）、`session.py`（`CompletionCriteria` 降级） | 实际测试 |
| 6 | Synthesis/report 诚实性 | ✅ | `pipeline.py` 降级用真实证据、不伪造；回归通过 | 实际测试 |
| 7 | 可靠性：超时/预算/Retry/Replan/状态/SSE | ✅ | 可靠性子集 116 passed/1 skipped；预算原子预约、达顶拒绝、不伪装 mock、Replan 不重跑成功 Agent 等均有测试 | 实际测试 |
| 8 | Session 内存态（R8）评估 | ✅(记录) | `RunRegistry` 重启丢历史 → 记为**设计限制**，不加框架 | 设计推断 |
| 9 | R1 真实 usage 观测 | 🔒 | 硬闸门 `REAL_EXECUTION_ENABLED=False` + API 余额耗尽，不开启 | BLOCKED |
| 10 | R2 真实工具调用 | 🔒 | 同上，真实运行不执行 | BLOCKED |
| 11 | R1 真实成本上报 | 🔒 | 依赖真实运行；`pricing.py` 已就绪，未知/离线报 null | BLOCKED |
| 12 | R2 真实检索决策核验 | 🔒 | 同上 | BLOCKED |
| 13 | R3 Single-Agent Baseline | ✅(离线) / 🔒(真实) | 离线 Baseline 跑通（cost unavailable 诚实）；真实 Baseline 受闸门约束 | 实际测试 / BLOCKED |
| 14 | 真实稳定性复跑 | 🔒 | 同上 | BLOCKED |
| 15 | 语义质量评审 | ✅ | `SEMANTIC_QUALITY_AUDIT.md`（证据/来源/合成语义守卫评审） | 静态审计+实际测试 |
| 16 | 全量离线回归 | ✅ | pytest 481 passed/7 skipped；ruff 全绿；前端 `vue-tsc`+`vite build` 通过 | 实际测试 |
| 17 | 安全 / 密钥扫描 | ✅ | `.env` gitignored 且未跟踪；源码密钥签名扫描 0 命中 | 静态审计 |
| 18 | 六份最终文档 | ✅ | 本目录：FINAL_HARDENING_REPORT / FINAL_VALIDATION_MATRIX / BASELINE_COMPARISON_REPORT / SEMANTIC_QUALITY_AUDIT / RELEASE_READINESS / RELEASE_NOTES（README 同步） | 设计推断 |
| 19 | 22 项验收（本矩阵） | ⚠️ | 离线/静态/推断项全达成；真实运行项 BLOCKED 致整体"部分达成" | 混合 |
| 20 | Git 发布（commit/tag/push/Release） | 🔒(DEFERRED) | 未达"验收后再发布"门槛；本次不执行，保留工作树供复核 | 设计推断 |
| 21 | 纪律（不越界：不重写 Core/不引框架/不伪造/不弱断言） | ✅ | 全程遵守；闸门保持 False；未删用户文件/历史 | 设计推断 |
| 22 | 最终报告（14 节） | ✅ | `FINAL_HARDENING_REPORT.md` 14 节齐备 | 设计推断 |

---

## 汇总

- **✅ 达成（离线/静态/推断可验）**：1,2,4,5,6,7,8,13(离线),15,16,17,18,21,22 = 14 项
- **⚠️ 部分达成**：19（受真实项拖累）
- **🔒 BLOCKED（真实运行相关，不执行）**：3(真实),9,10,11,12,13(真实),14 = 真实路径 7 处
- **🔒 DEFERRED（发布）**：20

## 阻断根因（真实运行）

1. `REAL_EXECUTION_ENABLED = False` 为发布前硬不变量，禁止开启（项目约束 + 任务"验收前不发布"）。
2. 底层 LLM API 余额耗尽（HTTP 402），即便开启闸门真实运行亦会中止，无法产出有效真实证据。

## 解锁后发布门槛（见 RELEASE_READINESS.md）

维护者明确授权开启闸门 + 凭据可用 → 跑真实 Scenario A/B + Baseline + 稳定性复跑 → 真实证据齐全 → 再执行 commit/tag/push/Release。
