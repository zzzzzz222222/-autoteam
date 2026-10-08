# AutoTeam v0.6.1 → v0.6.2 — Evidence / Sources / Claim 溯源审查（Step 3）

> 数据源：复用既有真实多 Agent 运行 `validation/runs/20261003T084253Z_A_real/run1_run_f4c191c6/`（非新增调用）。
> 工具：`validation/` 下 JSON 产物 + 只读 Python 完整性脚本（已删除临时脚本）。
> 区分：**结构完整性**（ID / 字段 / 引用 / 关联是否正确）与**语义支撑性**（原始来源是否真正支持对应 Claim）。

## 一、结构完整性（自动核对）

| 检查 | 结果 | 判定 |
|---|---|---|
| Source → 数量 / 类型 | 36 条，全部 `web` | ✅ |
| Source URL 完整性 | 36/36 以 `http(s)` 开头，0 空 / 0 含空格畸形 | ✅ |
| Evidence → Source 引用 | 67 条 Evidence，其中 22 条带 `source_id`（source_fact）、45 条空（unverified_claim）；**带 source_id 者 0 悬空**（全部指向存在的 Source） | ✅ |
| Artifact → Evidence 引用 | 8 个 Artifact，引用 Evidence **0 悬空** | ✅ |
| Finding → Evidence 引用 | 10 个 Finding，引用 Evidence **0 悬空** | ✅ |
| Claim → Source 错联 | `claim_audit` 中 `unbound_citations` / `dangling source_id` = 0 | ✅ |

**结论：结构完整性无缺陷。** 不存在悬空引用、不存在错误关联、不存在伪造 URL。

## 二、语义支撑性（人工 + 字段核验）

| 维度 | 实测 | 说明 |
|---|---|---|
| Evidence `claim_type` | `unverified_claim`:45 / `source_fact`:22 | 45 条未绑定到检索片段 → 被降级为 `unverified_claim` |
| Evidence `verified` | 全部 `False` | 系统采取保守口径：未确证即不标 true |
| Evidence `review_status` | `unsupported`:45 / `not_checked`:22 | 与 claim_type 一致 |
| Finding `review_status` | `partially_supported`:5 / `unsupported`:1 / `not_checked`:4 | 仅 1 条 unsupported，5 条部分支撑 |
| Finding `finding_counts`（聚合） | `supported`:9 / `unverified`:1 / `unsupported`:0 | 与逐 finding `review_status` **口径不同**（见下） |
| `claim_audit` | 10 条，全部 `passed=False` | 每条 claim 均未能绑定到检索片段，被诚实标注 |
| Source 缺口（`source_gaps`） | 8 个（high:4 / medium:4） | 按 `declared_intent` 检测，诚实降级 |

### 典型语义案例（来自产物）
- `evidence_id=ev_81fdb47424`：claim 为「2026 全球 AI agents 市场约 109.1 亿美元…」，但 `source_id=""`、`claim_type=unverified_claim`、`match_score=0.4159`、`match_method=no_snippet`、`verified=False`。系统**未**把该数字当作已核验事实——属正确降级，非缺陷。
- `finding_id=kf_market_size`：`review_status=unsupported`，`unsupported_parts` 显式列出「2026年[year]」「91.4-109.1亿[currency]」等无法逐项核验的数值。系统对不确定部分做了**逐字标注**，诚实。

### 口径差（观察项 O1，非 Bug）
合成器同时输出两套口径：
1. `finding_counts`：`supported:9 / unsupported:0`（按**证据绑定**计）；
2. 逐 finding `review_status`：`unsupported:1 / partially_supported:5`（按**语义核验**计）。

两者衡量不同维度（前者「是否有证据挂接」，后者「claim 数值是否逐项可核验」），但同屏呈现易误读为「所有 finding 均已支撑」。建议在最终报告引用时显式区分，避免误导。

## 三、来源缺口 / 重复 / 冲突

- **来源缺口**：8 个（high:4 对应 market_overview / requirements_document / competitor_landscape / technology_trends，均 `source_required=True`；medium:4 对应 data_insights / backend_implementation / proposal_document / final_report，`source_required=False`）。已由 `source_policy` 检测并降级，未谎报 success。
- **重复来源**：36 个 Source 来自 8 个 Agent 的 9 次检索，`identity` 字段为 `web:<url>` 去重键，未发现重复录入（URL 唯一）。
- **相互冲突证据**：`synthesis_audit.json` 提供 `source_conflicts` 字段；本次运行无强制冲突记录（合成 `contradictions:4` 为 LLM 侧语义矛盾，已由 `uncertainties`/`tradeoffs` 承载，属正常研究输出）。
- **未验证信息误写事实**：未发现——所有 unverified 均显式标注，无把 unverified_claim 当确定事实写入最终结论的情形。

## 四、报告展示数量 vs 实际数据

主报告第七节引用「Evidence 67 / Sources 36」与产物 `evidence.json`(count=67)、`sources.json`(count=36) **完全一致**。Finding 数量（10）与 `synthesis.json` 一致。未出现数量虚报。

## 五、结论

- **结构完整性：PASS（0 悬空、0 伪造 URL）。**
- **语义支撑性：诚实且保守**——45/67 Evidence 与多数 Finding 被显式降级为 unverified / partially_supported，未掩盖不确定性。
- **未发现代码 Bug**。语义匹配严格（阈值/片段绑定）属设计取舍，非缺陷；如要提升真实检索召回，属 D4 / v0.7+ 范畴，不强行重写 Evidence 系统。
- **唯一改进项**：`finding_counts` 与 `review_status` 两轴口径在报告中显式区分（O1），已在 `V0.6X_FINAL_ACCEPTANCE_REPORT.md` 落实。
