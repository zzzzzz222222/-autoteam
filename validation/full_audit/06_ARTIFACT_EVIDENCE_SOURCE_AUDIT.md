# AutoTeam v0.6.2 Candidate — 06 Artifact / Evidence / Sources 审计

> 审计日期：2026-10-03｜只读审计。
> 数据：复用既有真实运行 `validation/runs/20261003T084253Z_A_real/run1_run_f4c191c6/`（**未新增任何 API 调用**）。
> 方法：代码阅读 + 对运行产物的独立只读重算（临时脚本已删除，未在项目留下文件）。

---

## 1. Artifact

### 1.1 结构与生产者 ✅

| 检查 | 实测 | 判定 |
|---|---|---|
| 生产者对应关系 | `artifact_id = artifact_<agent_id>`，8/8 与 agent 严格对应 | ✅ |
| 产出数量 / 状态 | 8 个全部产出，`rejected=0` | ✅ |
| 内容体量 | 千字级（如 market_researcher 3727 字符），**无空 artifact** | ✅ |
| 类型 | 全部 `research_findings` | ✅ |

### 1.2 Artifact 协作链（结构 vs 语义）

- **结构关系已验证**：`context.py:63-90` `assemble_agent_context` 按传递闭包上游 `upstream_agent_ids` 过滤，仅注入 `AgentArtifact` 且 status=success 的上游结果；DAG 11 条边 × 8 节点，7 个非根节点均 ≥1 上游依赖 ✅
- **语义使用尚未充分验证**：本次**未能证明**下游 agent 在语义上真正使用了上游内容（需要 prompt/输出对照分析，超出安全边界未执行）→ 标记为 **部分验证**。

> 按审计要求明确标注：**「结构关系已验证，语义使用尚未充分验证」**。

### 1.3 ⚠️ partial Artifact 仍作为完整上游被消费

- `agent_runtime.py:678-693` 预算耗尽产生 `metadata["partial"]`
- `session.py:271-279` 仅在 session 层降级 verdict，**调度器状态仍为 SUCCESS**
- `context.py:67-90` 不识别 partial
- **结果**：残缺产物会被当作正常上游注入下游 → `AT-AUDIT-007 / MEDIUM / CONFIRMED`

---

## 2. Evidence

### 2.1 结构完整性（本次独立重算，非沿用历史）

重算脚本读取 `evidence.json["items"]`（共 **67** 条），字段：`evidence_id / claim / source_id / source_type / producer_agent / artifact_id / claim_type / verified / review_status / match_score / match_method / evidence_text / source_domain`。

| 检查 | 实测 | 判定 |
|---|---|---|
| Evidence 总数 | 67 | — |
| 带 `source_id` | **22**（且全部同时带非空 `evidence_text` → 真正绑定） | ✅ |
| 绑定 source 且有 snippet | **22**（= 上述，无“空绑定”） | ✅ |
| 未绑定（`source_id=""`） | **45**，均为 `unverified_claim` | ✅ 诚实降级 |
| `verified=True` 的条数 | **0** | ✅ 极其保守，未发现误标 verified |
| claim_type 分布 | `unverified_claim: 45`、`source_fact: 22` | 一致 |
| review_status 分布 | `unsupported: 45`、`not_checked: 22` | 与 claim_type 一致 |

**结论**：✅ **结构完整性无缺陷** —— 无悬空引用、无伪造 Evidence、无虚假 verified。

> 更正说明：前一轮 `EVIDENCE_PROVENANCE_AUDIT.md` 曾记录相同结论，本次为**独立重算**（使用正确字段名 `evidence_text`），结论一致。

### 2.2 Evidence ↔ Claim 关联 ⚠️

- `claim_audit`（详见 07 号报告）显示：**每条 claim 平均有 8 条 unbound citations（合计 8）**，即存在被引用但无 source 绑定的 Evidence
- `numbers_supported = 16`、`numbers_missing = 16` → 被抽查数值中**约一半**在引用片段中找不到
- 这些均被诚实记录为 `unbound_citations` / `numbers_missing`，**未伪造支撑**，但说明语义支撑度有限（详见 07 号报告）

---

## 3. Sources

### 3.1 结构质量（本次重算）

`sources.json["items"]` 共 **36** 条，字段：`source_id / title / source_type / url / domain / retrieved_at / producer_agents / artifact_ids / identity / alt_titles / first_seen_agent / access_status / access_note`。

| 检查 | 实测 | 判定 |
|---|---|---|
| 数量 / 类型 | 36，全部 `web` | ✅ |
| URL 合法性 | 36/36 以 `http(s)` 开头，0 畸形 | ✅ |
| 去重 | 唯一 URL 36 = 唯一 ID 36，无重复录入 | ✅ |
| 标题缺失 | 0 | ✅ |
| `access_status` | **36/36 为空** | ⚠️ 见下 |
| `identity` 去重键 | 存在（`identity` 字段） | ✅ |

### 3.2 ⚠️ Source 只证明「存在」，不证明「被抓取核验」

- `access_status` 全为空 → 系统**未记录**该 source 是否被真正成功抓取/读取
- 这会削弱 07 号报告的可信度：URL 有效 ≠ 内容支持结论
- **判定**：`AT-AUDIT-023 / INFO / DESIGN_LIMITATION`

### 3.3 来源缺口（诚实机制在生效）✅

- `source_policy.py:75-130` `source_gaps()`：基于声明式 intent（`SOURCE_REQUIRED_INTENTS`，:39-54）检测
- 真实运行实测 **8 个来源缺口**（high 4 / medium 4），被显式降级并计数，**未谎报 success** ✅

---

## 4. Final Deliverable / Assembler

### 4.1 装配路径（双 assembler）

- 主路径：`session.py:238` `assemble_from_bundle`（新版合成装配）
- 兜底：`session.py:253` `ArtifactAssembler().assemble`（旧版），仅在合成异常时降级
- 数据类 `FinalArtifact`/`FinalSection` 单一来源（`runtime/assembler.py:31-249`），单向依赖 ✅

### 4.2 已被 pytest 覆盖的关键行为 ✅

- `session.py:215-226`：合并前二次 `validate_artifact`，拒绝项记录 `ARTIFACT_REJECTED` 且不进报告
- 合成失败降级 legacy assembler，**不使整 run 失败**（:230-264）
- 最终交付存在且可读取（真实运行 report.md 100,431 字符）

### 4.3 ⚠️ headline 计数与实际核验存在口径差（核心问题）

`synthesizer.py:643-654` 的文档定义：
- `supported`：bound evidence **AND** a support level that counts as backing (source text, **agent consensus** or **derived**)
- 实测常量：`SUPPORTED_LEVELS = frozenset({"source_text","agent_consensus","derived"})`（`synthesizer.py:636`）
- 仅 `review in UNSUPPORTED_REVIEW`（= `{"unsupported"}`，:637）才排除

**后果**：多 agent 一致（无独立来源）与派生估算都被计入 **supported**。真实运行 headlines 记 `supported: 9/10`，而逐 claim 严格引用核验仅 **2/10 `supported_by_citation`**。

→ **AT-AUDIT-004 / HIGH / CONFIRMED**（详见 07 号报告量化）

---

## 5. 本模块问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-004 | HIGH | `finding_counts.supported` 口径夸大（含 agent consensus / derived） | CONFIRMED |
| AT-AUDIT-007 | MEDIUM | partial Artifact 被下游当作完整产物消费 | CONFIRMED |
| AT-AUDIT-011 | MEDIUM | 非数值 Claim 完全绕过引用核验 | CONFIRMED |
| AT-AUDIT-016 | LOW | 两个同名 `assembler.py` | CONFIRMED |
| AT-AUDIT-023 | INFO | Source `access_status` 为空，无法证明内容被抓取 | DESIGN_LIMITATION |

**已确认干净**：
- ✅ Evidence 0 悬空、0 伪造 URL、0 误标 verified
- ✅ Source 去重与 URL 合法性 100%
- ✅ Artifact 8/8 产出、无空、生产者对应正确
- ✅ 来源缺口被诚实检测并降级，未谎报
- ✅ final artifact 数据类单一来源
