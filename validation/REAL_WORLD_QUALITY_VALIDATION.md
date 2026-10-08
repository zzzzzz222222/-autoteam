# AutoTeam v0.6.1 → v0.6.2 — 真实运行质量验证（Step 7）

> 原则：**不新增真实 API 调用**。复用已完成的真实多 Agent 任务与单 Agent Baseline。
> 数据源：`validation/runs/20261003T084253Z_A_real/run1_run_f4c191c6/`（多 Agent）、`validation/runs/20261003T084839Z_A_real/`（单 Agent Baseline）。
> 约束：**不得预设多 Agent 一定优于单 Agent**；不得将一次成功运行描述为生产级稳定性证明；证据不足处标注。

## 一、可追溯性

| 项 | 多 Agent A | 单 Agent Baseline |
|---|---|---|
| 运行 ID | `run_f4c191c6` | `baseline_084830666126` |
| 产物目录 | `20261003T084253Z_A_real/run1_run_f4c191c6/` | `20261003T084839Z_A_real/` |
| 配置 | `--mode real --confirm-real`，`REAL_EXECUTION_ENABLED` 临时 True 后恢复 | 同 |
| 模型 / Provider | deepseek-chat / api.deepseek.com/v1 | 同 |
| 真实 Web Search | 是（Tavily 兼容，`AUTOTEAM_WEB_SEARCH_URL` 配置） | 否（基线不调用工具） |

配置、日志、统计均留盘（`validation/runs/` 已被 `.gitignore` 忽略，不入库），可回溯。

## 二、对照分析

| 维度 | 多 Agent A | 单 Agent Baseline | 说明 |
|---|---|---|---|
| 任务完成 | `completed`（termination=completed） | 完成 | 两者均成功 |
| Agent 数 | 8（DAG 4 层 / 11 边） | 1（无 DAG / 无合成） | 结构差异 |
| Artifact 完整性 | 8 个产出，rejected 0 | 无独立 artifact（基线单段产出） | 多 Agent 产出更结构化 |
| Evidence | 67 | 8 | 多 Agent 经检索带来更多 evidence |
| Sources（真实） | 36（web:36，URL 全部合法） | 0 | 基线不检索，无真实来源 |
| 最终报告 | 合成 `completed`，10 findings + insights/recs | 单段文本 | 多 Agent 有跨源综合 |
| Retry / Replan | 2 次重试（竞品/数据 agent），均恢复 | 无 | 重试路径在真实负载下验证 |
| LLM 调用 | 20（blocked 0） | 1 | — |
| 执行时间 | 193.1s | 9.0s | — |
| 真实 API 成本 | ≈ $2.416 | ≈ $0.046 | 来自 pricing.py 列价，非臆造 |

## 3. 质量判读（克制表述）

- **多 Agent 优势（结构性，非绝对）**：在「证据广度 / 可核验真实来源 / 跨源综合」上明显优于单 Agent 基线（67 vs 8 evidence、36 vs 0 sources）。这是编排 + 真实检索带来的，与基线「单 LLM 不调用工具」的设计差异一致。
- **不宣称绝对优劣**：基线 0 工具是基线定义使然，非能力缺陷；本对照不证明「多 Agent 必然优于单 Agent」在所有任务上成立。
- **诚实溯源**：多 Agent 运行 45/67 evidence 降级为 `unverified_claim`、8 个来源缺口被显式标注——系统未把未核验信息当事实（见 `EVIDENCE_PROVENANCE_AUDIT.md`）。
- **非稳定性证明**：本次仅 1 次多 Agent + 1 次 Baseline；稳定性需多次重复（历史周期已有 13 次真实运行的先例，详见 `validation/FINAL_VALIDATION_AND_RELEASE_REPORT.md`），本验收不重复压测。

## 四、来源 / 配置 / 日志一致性

- Sources 36 条 URL 全部以 `http(s)` 开头、无畸形（结构完整性 PASS）。
- Evidence 67 条引用 Source 0 悬空；Artifact/Finding 引用 Evidence 0 悬空。
- 日志与 `metrics.json` 一致：Agent 8/0/0、LLM 20、web 9、cost $2.416 均可由产物反查。

## 五、证据不足处的记录

- 本验收**未**对历史 13 次真实运行逐一重算；仅复用最新一次多 Agent + Baseline 作为代表。若需全量复核，应另行执行（超出本次「不新增调用」约束）。
- `finding_counts.supported:9` 与逐 finding `review_status.unsupported:1` 的口径差（O1）已在 `EVIDENCE_PROVENANCE_AUDIT.md` 说明；本文件沿用产物原始聚合值，未做二次推算。

## 六、结论

- 已复用的真实运行**可追溯到配置、日志与统计**，任务完成、Agent 协作、Artifact、Evidence/Sources、最终报告、Retry、LLM 次数、时间、成本均一致且无伪造。
- 真实链路在 v0.6.1 中**端到端可用、无崩溃、溯源诚实**；B1/B2/B3 修复经真实运行 + 回归测试双重确认。
- 结论限于已复用样本，**不构成生产级稳定性证明**；稳定性证据可参考历史 13 次真实运行记录。
