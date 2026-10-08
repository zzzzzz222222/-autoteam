# AutoTeam v0.6.2 — AT-AUDIT-004 Fix Report

**议题**：Synthesizer 证据支持等级判定过宽（`finding_counts.supported` 口径夸大）
**结论**：**FIXED**
**日期**：2026-10-04
**基线**：`master` @ `f3f7330 release: prepare AutoTeam v0.6.1`
**授权边界**：仅修复 AT-AUDIT-004；禁止真实 API 调用（DeepSeek / OpenAI / Tavily）；禁止联网取数；禁止 git commit / push / tag / release。

---

## 1. Root Cause

`app/synthesis/synthesizer.py` 的 `compute_finding_counts()` 用一个单一维度表达"支持"，而该维度的判定集合把**内部背书**与**外部证据**混为一谈：

```python
# 修复前（synthesizer.py:636）
SUPPORTED_LEVELS = frozenset({"source_text", "agent_consensus", "derived"})
```

三个成员的性质完全不同：

| support_level | 谁来背书 | 是不是外部来源 |
|---|---|---|
| `source_text` | 检索到的外部来源片段 | ✅ 是 |
| `agent_consensus` | 本轮 run 内部多个 Agent 说法一致 | ❌ 否，run 内自证 |
| `derived` | 模型基于可追溯输入的推算 | ❌ 否，模型自证 |

`support_profile()`（`app/synthesis/claim_support.py:386`）的判定顺序本身是正确的、分层的（`planning_assumption` → `derived` → `source_text` → `agent_consensus` → `agent_restatement` → `unknown`），**它并没有撒谎**。问题出在下游：汇聚成 `finding_counts` 时，这三层被折叠成同一个 `supported` 计数器。

后果是一个可被复现的口径落差：

-  headline（按证据绑定 + tier）：`supported = 9 / 10`（**90%**）
-  严格逐 claim 引用核验（数值 / 单位 / 年份比对）：`2 / 10`（**20%**）

来源：`validation/full_audit/07_FINAL_DELIVERABLE_QUALITY.md:53`。该 run 的 `metrics.json → synthesis.counts.finding_counts` 为
`{"total": 10, "with_valid_evidence": 10, "supported": 9, "multi_source": 4, "single_source": 6, "unverified": 1, "unsupported": 0}`。

根因一句话：**"Agent 一致意见"和"模型推算"都不是外部来源，却被计入了面向外部读者展示的 `supported`**。

---

## 2. Reproduction

修复前有两条独立的复现路径，均已实际执行。

### 2.1 真实产物重算（真实运行数据，非伪造）

对 `validation/runs/**/synthesis.json` 中的 **20 个历史运行产物**逐条重新计算，同一份 finding 数据同时套两种公式：
`OLD` = 修复前的 `SUPPORTED_LEVELS` 判定；`NEW` = 修复后的 `compute_finding_counts()`（调用真实生产函数）。

| 运行 | FINAL total | OLD supported | NEW supported | backed_count | agent_consensus | derived |
|---|---|---|---|---|---|---|
| `20261003T084253Z_A_real`（审计引用的 9/10 run） | 10 | **9 (90%)** | 8 | 9 | 0 | 1 |
| `20261003T032043Z_A_real` | 14 | 9 | 7 | 9 | 1 | 1 |
| `20261003T041859Z_B_real` | 14 | 10 | **4** | 10 | 0 | **6** |
| `20261003T033843Z_B_real` run1 | 16 | 8 | 7 | 8 | 1 | 0 |
| `20261002T102529Z_A_real` | 6 | 5 | 3 | 5 | 2 | 0 |
| 7 个离线 run（各 2 findings） | 2 | 1 | 0 | 1 | 1 | 0 |

最刺眼的一行是 `20261003T041859Z_B_real`：**10 条里有 6 条是模型推算**，旧口径照报 `supported = 10`，修复后 `supported = 4`、`derived = 6`。这正是"口径夸大"的具体形态。

> 该重算脚本为一次性只读探针，执行后已删除；数字可用 `git show HEAD:app/synthesis/synthesizer.py` 还原旧逻辑后复算得到。

### 2.2 定向测试复现（受控还原 + sha256 校验）

方法：临时把 `app/synthesis/synthesizer.py` 还原为 `HEAD`（修复前）版本 → 运行新测试文件 → 还原 → 用 sha256 校验文件内容逐字节一致（`RESTORED_OK: True`）。

```
PRE-FIX pytest exit: 1
FFFFF..FFF.FFF...F                                                       [100%]
12 failed, 6 passed in 2.04s
RESTORED_OK: True
```

12 项失败按性质分两类：

| 类别 | 数量 | 失败签名 | 说明 |
|---|---|---|---|
| **语义缺陷**（supported 被夸大） | 5 | `assert 1 == 0` ×4、`assert 2 == 1` ×1 | 直接证明 `agent_consensus` / `derived` 被计入 `supported` |
| 新增轴缺失 | 7 | `KeyError: 'citation_verified'` ×6、`KeyError: 'backed_count'` ×1 | 当时尚无独立 Keys，属预期 |

失败的 5 项语义用例：

| 测试 | 位置 | 修复前实际值 |
|---|---|---|
| `test_agent_consensus_is_not_counted_as_supported` | `:98` | `supported = 1`（应为 0） |
| `test_agent_count_never_inflates_source_counts` | `:116` | `supported = 1`（应为 0，且 `multi_source/single_source` 未被污染） |
| `test_derived_estimate_is_not_counted_as_supported` | `:129` | `supported = 1`（应为 0） |
| `test_peer_agreement_does_not_change_an_unsupported_finding` | `:258` | `supported = 1`（应为 0） |
| `test_backed_count_never_exceeds_the_backed_tiers` | `:344` | `supported = 2`（应为 1；多出的 1 来自 agent consensus） |

---

## 3. Existing Support Semantics（修复前的判定链）

修复前的完整链路已经具备区分能力，只是**汇聚时丢掉了区分**：

1. `support_profile(evidence_ids, by_id, claim_type)` → `SupportProfile(support_kind, support_level, evidence_count, agent_support_count, independent_source_count, agents)`
   - `multi_source` 已要求 **≥2 个不同独立来源**；多个 Agent 一致但没有来源只算 `multi_agent`（`app/synthesis/models.py:52`）
2. `audit_claim_support(statement, evidence_ids, by_id, pool)` → 逐 claim 的 **数值 / 单位 / 年份**比对
   - 状态：`supported_by_citation` / `partially_supported` / `unsupported` / `no_numeric_claim`
   - **明确不做语义判断、不做 LLM 投票**（`app/synthesis/claim_support.py` 头部注释）
3. `derive_review_status(...)` → `Finding.review_status`
4. `compute_finding_counts(...)` → **缺陷所在**：把 1/2/3 三层塌缩成一个 `supported`

`Finding.support_audit`（`app/synthesis/models.py:195`）在活体链路里由 `synthesizer.py:248` 写入，**这条严格核验轴一直存在，只是从来没有被汇成一个独立计数**。

---

## 4. Updated Support Semantics（修复后的判定语义）

拆成**两条永不合并的轴**，每个等级都有可验证的含义：

| 概念 | 判定依据 | 计数键 | 是否计入 `supported` |
|---|---|---|---|
| **外部来源支持** | `support_level == "source_text"` 且 `review_status != "unsupported"` | `supported` | ✅ |
| **多来源交叉印证** | `independent_source_count >= 2` | `multi_source` | 不单独计（仍是 `supported` 的构成信息） |
| **单来源支持** | `independent_source_count == 1` | `single_source` | 同上 |
| **Agent 一致意见** | ≥2 Agent 无来源片段地一致 | `agent_consensus` | ❌ |
| **单 Agent 复述** | 1 个上游 Agent 陈述，无来源 | `agent_restatement` | ❌（落入 `unverified`） |
| **模型推算** | `claim_type` 派生自可追溯输入的分析 | `derived` | ❌ |
| **规划假设** | 产品/商业计划，非既成事实 | — | ❌（落入 `unverified`） |
| **引用核验通过** | `support_audit.status == "supported_by_citation"` | `citation_verified` | ❌（另一条轴，永不合并） |
| **证据不足** | 有绑定证据但达不到外部来源支持 | `unverified` | ❌ |
| **无证据（悬空引用）** | `evidence_ids` 一条都不可解析 | `unsupported` | ❌ |
| **冲突证据** | 多条来源结论相悖 | 不消解，原样暴露 | ❌ |

原则（与审计要求一致）：

- **Agent 一致意见 ≠ 外部证据**，**模型推导 ≠ 来源证实**
- 不靠"证据条数 / Agent 个数"单方面判定——`supported` 只看"有没有外部来源说出来"，来源条数另由 `multi_source/single_source` 表达
- **没有为抬高支持率而放宽任何标准**：修复后 `supported` 只会变小或不变（`backed_count` 保留了旧序列以便对照）
- 冲突证据不上报 Illusion of resolution，保留原样供人工裁决

---

## 5. Fix

只改一处生产文件：`app/synthesis/synthesizer.py`（+61 / −8）。

### 5.1 常量

```python
# v0.6.2 (AT-AUDIT-004): ``supported`` means backed by EXTERNAL evidence.
SUPPORTED_LEVELS = frozenset({"source_text"})
# Internal backing: real, but not "a source said it". Counted separately and
# also reported as ``unverified`` on the evidence axis.
INTERNAL_BACKING_LEVELS = frozenset({"agent_consensus", "derived"})
UNSUPPORTED_REVIEW = frozenset({"unsupported"})
CITATION_VERIFIED_STATUS = "supported_by_citation"
```

### 5.2 `compute_finding_counts()` 分类逻辑

```python
if review in UNSUPPORTED_REVIEW:
    unverified += 1
    continue
if level in SUPPORTED_LEVELS:
    supported += 1
    backed_count += 1
elif level in INTERNAL_BACKING_LEVELS:
    # AT-AUDIT-004: agreement between agents and model-side estimates are
    # real backing, but they are not a source...
    if level == "agent_consensus":
        agent_consensus += 1
    else:
        derived += 1
    backed_count += 1
    unverified += 1
else:
    unverified += 1
audit = getattr(finding, "support_audit", None) or {}
if str(audit.get("status", "") or "").strip().lower() == CITATION_VERIFIED_STATUS:
    citation_verified += 1
```

返回字典新增 4 个键，**旧键全部保留**（`total` / `with_valid_evidence` / `supported` / `multi_source` / `single_source` / `unverified` / `unsupported`），因此下游 `validation/collect.py:434`（整字典拷贝）与历史产物解析器均无需改动。

**不变量**：`with_valid_evidence == supported + unverified`（新测试锁定）。

### 5.3 刻意未做的事

| 未做 | 原因 |
|---|---|
| 不修改 `support_profile()` | 它的分层本身正确，无需改；改了会波及 v0.6.6 的 A1–A7 语义 |
| 不让 `claim_support` 做语义判断 | 引入 LLM judge 属新增评分框架，超出本次授权 |
| 不把 `citation_verified` 并入 `supported` | 那正是本次要修的病 |
| 不重命名 `supported` | 保持对外结构稳定；新语义由 `backed_count` 提供对照序列 |
| 不改前端 | 前端不渲染 `finding_counts`（已 grep 确认 `frontend/src` 无引用），无需改且改动会超范围 |
| 不动 AT-AUDIT-005 及其它议题 | 授权边界 |

---

## 6. Evidence Integrity

| 检查项 | 结果 |
|---|---|
| 来源是否被伪造以抬高支持率 | **否**。全程未新增/改写任何 `SourceRecord` / `EvidenceRecord`，未触碰 `source_identity` / `claim_support` / `source_policy` |
| 是否有 URL 编造 | **否**。本次未产生 URL，也未读取外部网络 |
| 降级路径是否被绕过 | **否**。`UNSUPPORTED_REVIEW` 分支完整保留，`review_status == "unsupported"` 仍然直接进 `unverified` |
| 语义判定是否被 LLM 接管 | **否**。`citation_verified` 只读已有的 `support_audit.status`，该状态由确定性的数值/单位/年份匹配产生 |
| 是否用"数量阈值"冒充质量 | **否**。`supported` 不依赖证据条数；`multi_source/single_source` 只描述独立性，不参与 `supported` 判定 |
| 旧口径是否还可审计 | **是**。`backed_count` ≡ 旧 `supported` 序列，可逐 run 对照（见 §2.1 表格） |
| 是否有"未核验却标注核验" | **否**。`agent_consensus` / `derived` 明确同时计入 `unverified`，不会被误读为已证实 |

---

## 7. Test Coverage

新增 **`tests/test_support_level_semantics.py`**（18 项），全部驱动真实链路：
`EvidenceRecord` → `support_profile()` → `audit_claim_support()` → `derive_review_status()` → `Finding` → `compute_finding_counts()`。
无真实 LLM、无联网、无"假装是真来源"的 mock 来源。

| # | 测试 | 锁定的语义 |
|---|---|---|
| 1 | `test_agent_consensus_is_not_counted_as_supported` | Agent 一致 ≠ supported，但仍有 `agent_consensus` / `backed_count` |
| 2 | `test_agent_count_never_inflates_source_counts` | 4 个 Agent 一致时 `multi_source`/`single_source` 仍为 0 |
| 3 | `test_derived_estimate_is_not_counted_as_supported` | 输入可追溯的推算仍不是来源 |
| 4 | `test_derived_estimate_is_not_citation_verified` | 断言数字不在片段里 → 不通过引用核验 |
| 5 | `test_single_valid_source_is_supported` | 单条真来源 = supported，且 `citation_verified` 有独立值 |
| 6 | `test_multiple_independent_sources_are_supported` | 多独立来源仍 supported，`multi_source = 1` |
| 7 | `test_repeated_citations_of_one_source_are_not_independent` | 同一来源反复引用不算 `multi_source` |
| 8 | `test_numbers_missing_from_the_snippet_are_not_citation_verified` | 片段缺数值 → 不核验通过，缺口被记录 |
| 9 | `test_semantic_mismatch_remains_an_open_limitation` | 语义不匹配是**已知局限**，不被谎称为已核验 |
| 10 | `test_finding_without_evidence_is_unsupported` | 无证据 → `unsupported`，且 `backed_count = 0` |
| 11 | `test_single_agent_restatement_without_source_is_not_supported` | 单 Agent 复述 ≠ supported |
| 12 | `test_peer_agreement_does_not_change_an_unsupported_finding` | 同伴同意不能把 unsupported 洗成 supported |
| 13 | `test_numeric_claim_matching_the_snippet_is_citation_verified` | 数值与片段吻合 → `citation_verified` |
| 14 | `test_numeric_estimate_without_a_source_stays_unverified` | 无来源估值仍需外部核验 |
| 15 | `test_conflicting_sources_are_surfaced_not_silently_resolved` | 冲突证据原样暴露，不静默裁决 |
| 16 | `test_support_levels_stay_within_the_declared_schema` | 所有 tier ∈ `SUPPORT_LEVELS`，不出现野值 |
| 17 | `test_counts_keep_the_total_invariant` | `with_valid_evidence == supported + unverified` |
| 18 | `test_backed_count_never_exceeds_the_backed_tiers` | `backed_count` 不虚增，`supported ⊆ backed` |

同时改动既有测试 **`tests/test_targeted_hardening_d1_d4.py`**：
`test_counts_agent_consensus_is_supported_derivation` → `test_counts_agent_consensus_and_derived_are_not_external_support`。
该测试原本**断言了缺陷本身**（`assert counts["supported"] == 1`）。判定依据：`agent_consensus` / `derived` 的定义（models.py:68-75）从未声称它们是外部来源。它是被**修正**，不是被删除或跳过，且新断言更严格（同时校验 `supported=0` / `unverified=1` / `backed_count=1` / 专属键=1）。

---

## 8. Test Results（实际执行，含真实退出码）

| 命令 | 结果 | 退出码 |
|---|---|---|
| `pytest -q tests/test_support_level_semantics.py` | **18 passed** in 1.99s | `0` |
| `pytest -q`（全量） | **616 passed** in 18.92s | `0` |
| `ruff check .` | **All checks passed!** | `0` |
| `cd frontend && npm run build` | `vue-tsc --noEmit && vite build` 通过，56 modules transformed，built in 2.17s | `0` |

修复过程中出现过 1 次 ruff 报错（`tests/test_support_level_semantics.py:26` I001 import 未排序），已修；上表为重跑后的最终值。

前置/后置对比：

| 文件 | 修复前（受控还原版） | 修复后 |
|---|---|---|
| `tests/test_support_level_semantics.py` | 12 failed / 6 passed，exit **1** | **18 passed**，exit **0** |

---

## 9. Regression

逐文件复跑（每文件单独执行，非合并值）：

| 文件 | 关联议题 | 结果 |
|---|---|---|
| `tests/test_support_level_semantics.py` | AT-AUDIT-004（本次） | **18 passed** |
| `tests/test_targeted_hardening_d1_d4.py` | 历史 D1–D4 + 本次改动 | **29 passed** |
| `tests/test_max_concurrency.py` | AT-AUDIT-001 | **27 passed** |
| `tests/test_result_store_isolation.py` | AT-AUDIT-002 | **16 passed** |
| `tests/test_replanner_event_truthfulness.py` | AT-AUDIT-003 | **16 passed** |
| `tests/test_replan_topology_application.py` | AT-AUDIT-005 | **20 passed** |

六文件合计合并运行：**126 passed**，exit `0`。
这四个前置修复（001/002/003/005）全部保持有效，本次改动未触及 `scheduler` / `replan` / `result_store` / `orchestrator`。

兼容性校验：`finding_counts` 的消费点只有 `validation/collect.py:434`（整字典拷贝进 `counts`）与 `app/synthesis/pipeline.py:136`。新增键**追加**，旧键未改名未删除 → 历史产物解析与 `metrics.json` 兼容。前端对该字典零引用（已 grep 确认）。

---

## 10. Security

| 检查 | 命令 | 结果 |
|---|---|---|
| 改动内容密钥扫描 | `git diff -U0` + 正则（`sk-*` / `tvly-*` / `api_key=` / `Bearer *` / `ghp_*` / `AKIA*`） | **0 命中** |
| 真实执行硬闸门 | `grep -n REAL_EXECUTION_ENABLED validation/run_scenario.py` | `:64 REAL_EXECUTION_ENABLED = False`（未改动） |
| 真实 API 调用 | 本次全程 | **0 次**（无 DeepSeek / OpenAI / Tavily 调用） |
| 联网取数 | 本次全程 | **0 次** |
| git 写操作 | `git log --oneline -1` | 仍为 `f3f7330`，**无 commit / push / tag / release** |
| 空白 / 冲突标记 | `git diff --check` | exit `0` |

---

## 11. Changed Files

本次（AT-AUDIT-004）改动：

| 文件 | 类型 | 说明 |
|---|---|---|
| `app/synthesis/synthesizer.py` | 修改 | +61 / −8：`SUPPORTED_LEVELS` 收敛、`INTERNAL_BACKING_LEVELS` / `CITATION_VERIFIED_STATUS` 新增、`compute_finding_counts()` 双轴输出 |
| `tests/test_support_level_semantics.py` | **新增** | 18 项定向测试 |
| `tests/test_targeted_hardening_d1_d4.py` | 修改 | 1 项断言缺陷的旧测试改为断言正确语义 |

工作树中其余修改文件（`app/runtime/*`、`app/scheduler/*`、`app/api/*`、`frontend/src/*` 等）来自**前置任务** AT-AUDIT-001/002/003/005 与 B1/B2/B3，本次未触碰。

---

## 12. Git Status

```
HEAD: f3f7330 release: prepare AutoTeam v0.6.1   (未变动)
Branch: master
```

17 个已跟踪文件被修改（累计多轮修复），19 个未跟踪文件（新增测试 5 个 + validation 报告）。
`app/synthesis/synthesizer.py` 与 2 个测试文件的变更即本次范围。
**未执行任何 git 写操作**，符合"git 提交须经显式确认"的既定规则。

---

## 13. Known Limitations

1. **`citation_verified` 在已落盘产物上重算为 0。** `validation/collect.py:466-470` 序列化 finding 时用的是显式字段元组，**不含 `support_audit`**，因此历史 `synthesis.json` 里没有该字典。活体链路中是有的（`synthesizer.py:248` 写入），并会随 `metrics.json → synthesis.counts.finding_counts` 落盘（`collect.py:434`）。本次为控制范围未改 `collect.py` 的字段元组——若要让 `support_audit` 也可离线重算，需加一个字段，属后续可选项。
2. **`claim_support` 只做数值 / 单位 / 年份匹配，不做语义判断。** 一条语义相悖但数字巧合的引用仍会 `supported_by_citation`。这是既有设计约束（避免引入 LLM judge），不是本次引入；新测试 `test_semantic_mismatch_remains_an_open_limitation` 把它显式钉成"已知局限"而非"已核验"。
3. **`agent_restatement` 未单列计数键。** 它落入 `unverified`，语义正确但粒度不如 `agent_consensus` / `derived`。留作可选增强。
4. **`supported` 语义变更会影响新运行的对外展示数字。** 修复后数值会下降（如 9/10 → 8/10、10/14 → 4/14）。这是**有意为之**的正确方向；`backed_count` 保留了旧序列可供对照。若 v0.6.2 发版说明引用该指标，需同步更新措辞。
5. **真实环境下的端到端验证尚未补做。** 本次在"禁止真实 API"边界内完成，全部基于离线测试 + 历史真实产物重算。发版前建议在真实 Scenario A/B 上跑一轮，确认 `citation_verified` 在活体链路里的真实取值与分布。

---

## 14. Conclusion

# **FIXED**

判定依据：

1. **缺陷已被确定性复现**（不是推测）。修复前把 `synthesizer.py` 临时还原为 `HEAD` 版，新增测试 **12 failed / 6 passed，exit 1**；其中 **5 项**为纯语义失败（`assert counts["supported"] == 0` 实际得到 `1`，以及 `assert 2 == 1`）。还原后用 sha256 校验文件内容逐字节一致（`RESTORED_OK: True`）。
2. **修复后全部通过**。新增文件 **18 passed**；既有相关文件均通过（D1–D4 29 / 001 27 / 002 16 / 003 16 / 005 20）；**全量 616 passed，exit 0**；`ruff check .` exit `0`；`npm run build` exit `0`。
3. **虚假口径已量化消除**。真实产物 `20261003T041859Z_B_real`：旧 `supported = 10`（其中 6 条为模型推算）→ 新 `supported = 4`、`derived = 6`、`backed_count = 10`。审计引用的 `20261003T084253Z_A_real`：旧 9 → 新 8，`backed_count = 9`（旧口径可对照）。
4. **没有以放宽标准换取支持率**。判定集合只做**减法**（移除 `agent_consensus` / `derived`），未新增任何宽松条件；`supported ⊆ backed_count` 的不变量由测试锁定。
5. **两条轴严格分离**。`citation_verified`（严格引用核验）与 `supported`（外部来源绑定）永不合并，各走独立键。

遗留项见 §13，其中第 1 项（`collect.py` 未序列化 `support_audit`）是唯一会影响"离线复核 citation_verified"的点，建议在真实 run 验证阶段一并处理。

---

**范围声明**：本次仅处理 AT-AUDIT-004。未触碰 AT-AUDIT-005 及其它审计项，未开始 v0.7.0，未执行任何 git commit / push / tag / release。
