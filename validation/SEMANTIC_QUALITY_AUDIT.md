# AutoTeam v0.6.0 — 语义质量审计 (SEMANTIC QUALITY AUDIT)

> 评审对象：生成物（AgentArtifact / EvidenceRecord / Finding / 合成报告）的语义可信度
> 分类：【真实运行】【实际测试】【静态审计】【设计推断】【未验证】【人工核验】

---

## 1. 评审范围

聚焦"框架是否会在语义层面**误导读者**"——即把未经来源支撑的断言、Agent 自述、桩数据伪装成"已验证事实"。评审均为**确定性代码审查 + 既有测试回归**，不涉及 LLM 主观打分。

---

## 2. 关键语义守卫（静态审查）【静态审计】

### 2.1 数值断言支持（claim_support.py）【静态审计】
- **确定性数值匹配**：`match_assertion` 要求**值 + 单位类别 + 年份集合兼容**三重一致才算匹配；`%` 与"成"刻意区分为不同单位类别，避免 `4成` 被误等同 `40%`。
- **来源级支撑仅来自"检索片段"**：`is_source_backed` 必须 `source_id` **且** 绑定检索片段（`evidence` 非空）；Agent 自己的陈述文本绝不提升为"来源说"。
- **保守原则**：设计文档明确"支持不足是安全的，过度支持不是"——未匹配即降级，不强行绑定。
- **不混淆"多 Agent 同意"与"独立来源同意"**：`support_profile` 把 `multi_source`（≥2 个不同 source_id）与 `multi_agent`（≥2 Agent、无来源）严格区分；报告永远不会把 Agent 共识暗示为来源支撑。
- **绝不产出"verified"**：`derive_review_status` 明确"verified 永不由此处产生"——最高只到 `not_checked`/`partially_supported`。

### 2.2 声明式来源缺口（source_policy.py）【静态审计】
- **意图驱动、角色无关**：`declared_intent` 取自子任务声明的 `expected_output`，不取自角色名/Agent id，避免角色名误导。
- **缺口结构化**：`source_gaps` 在"声明意图要求来源但零绑定证据"或"声明为 source_fact 却无检索片段被降级为 unverified_claim"时产出结构化缺口（severity/markdown 原因），**绝不编造来源**。
- **与授权对齐（本次修正）**：`SOURCE_REQUIRED_INTENTS` 已与 `CAPABILITY_TOOLS` 对齐——仅列入 P6.12/6.13 已授予 `web_search` 的能力意图；已移除 `data_insights`（其 `DATA_ANALYSIS` 无 web_search，属不一致导致离线误报）。
- **降级规则**：`downgrade_unverified_claim` 确保无检索片段的 `source_fact` 退化为 `unverified_claim`，从源头堵住"假来源事实"。

### 2.3 来源身份与合成降级【静态审计】
- `source_identity.py`：URL 归一化，**绝不伪造 URL / 来源**（工作记忆不变量）。
- `pipeline.py`：降级路径使用**真实证据**，不伪造；来源缺口进入结构化缺口而非静默掩盖。

---

## 3. 本次修复对语义可信度的增强【实际测试】

- R2/R5（见 FINAL_HARDENING_REPORT §4.2）：`CompletionCriteria` 现在把"真来源缺口（`source_required` 且 `source_count==0`）"和"部分交付"纳入成功态判定——**不再把缺来源/部分交付的报告谎报为 SUCCESS**。
- `session.py` 收紧 `source_gaps_present`：仅当缺口确为"真未满足需求"才降级，避免离线 Mock 的未绑定声明被误判为缺口（修复回归中 11 个测试误降级）。

---

## 4. 回归证据【实际测试】

- `tests/test_synthesis.py`、`tests/test_phase69_source_identity.py`、`tests/test_provenance.py`、`tests/test_final_hardening_r1_r2.py`（CompletionCriteria 降级用例）等覆盖上述守卫。
- 全量 pytest 481 passed/7 skipped 包含上述语义守卫回归。

---

## 5. 语义质量结论

- **离线/静态层面**：框架具备**确定性的语义可信守卫**——数值支撑需值/单位/年份三重一致、来源级支撑仅认检索片段、Agent 共识与独立来源严格区分、来源缺口结构化且从不伪造、成功态不再掩盖缺来源/部分交付。**未见语义欺骗性缺陷**。
- **真实层面**：上述守卫对真实 LLM 输出同样生效（与 Provider 无关，属确定性后处理），但**真实产物的语义质量（如真实检索片段是否真支撑断言）需真实运行 + 人工核验**，本次因真实运行 BLOCKED 而标【未验证】。

---

## 6. 诚实声明

本审计是**代码级确定性评审**，不等同于对真实业务报告的人工事实核查。真实语义质量结论需真实运行证据，标【未验证】。
