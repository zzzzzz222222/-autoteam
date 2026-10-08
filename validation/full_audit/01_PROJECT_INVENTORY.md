# AutoTeam v0.6.2 Candidate — 01 项目清单与 Git 状态审计

> 审计日期：2026-10-03
> 审计性质：只读审计（不修改业务代码、不修改测试、不修复、不提交/推送/打标签/发布）
> 数据来源：本次实际执行的只读命令与文件核查，不沿用历史报告结论。

---

## 1. 项目目录清单（实际存在）

### 1.1 顶层结构（实际）

| 路径 | 说明 | 是否已 git 跟踪 |
|---|---|---|
| `app/` | 核心 Python 包（api / runtime / scheduler / synthesis / tools / models 等） | 是 |
| `frontend/` | Vue 3 + TypeScript 前端 | 是 |
| `tests/` | pytest 测试（**29 个测试文件**） | 是 |
| `validation/` | 验证/审计产物与脚本 | 是（其中 `runs/` 被 gitignore） |
| `docs/` | 文档截图/报告 | 是 |
| `scripts/` | 启动脚本（`start_web.py`） | 是 |
| `examples/` | 示例 | 是 |
| `knowledge/` | 知识库 | 是 |
| `README.md` / `README.zh-CN.md` | 双语 README | 是 |
| `RELEASE_NOTES_v0.5.0.md` / `_v0.6.0.md` / `_v0.6.1.md` | 发布说明 | 是 |
| `pyproject.toml` | 项目元数据 | 是 |
| `.env` / `.env.example` | 环境与示例 | **`.env` 未跟踪（已 gitignore）** |
| `.gitignore` | 忽略规则 | 是 |
| `autoteam_output/`、`autoteam.egg-info/` | 运行/打包产物 | 未跟踪 |
| `*.log`（约 60+ 个） | 历史调试日志，**散落在仓库根目录** | 见 §4 风险 |

### 1.2 核心模块清单（实际存在，非假定）

| 子包 | 文件 |
|---|---|
| `app/api` | `main.py` `routes.py` `models.py` `runs.py` |
| `app/runtime` | `understanding.py` `decomposer.py` `capability_discovery.py` `tool_selector.py` `role_allocation.py` `agent_factory.py` `dependency.py` `dynamic_team.py` `dynamic_models.py` `orchestrator.py` `session.py` `agent_runtime.py` `artifacts.py` `context.py` `events.py` `assembler.py` `result_store.py` `validation.py` `models.py` `claim_quality.py` |
| `app/scheduler` | `scheduler.py` `executor.py` `retry.py` `replan.py` `models.py` |
| `app/synthesis` | `pipeline.py` `synthesizer.py` `models.py` `prompts.py` `assembler.py` `source_policy.py` `source_identity.py` `claim_support.py` `evidence_selection.py` `evidence_filter.py` |
| `app/tools` | `registry.py` `calculator.py` `local_knowledge.py` |
| `app/llm` | `provider.py` `client.py` `structured.py` |
| `app/models` | `agent.py` `capability.py` `task.py` `topology.py` |
| `app/topology` | `generator.py` `templates.py` `validator.py` |
| `app/allocator`、`app/analyzer`、`app/evaluation`、`app/demo`、`app/config.py`、`app/ui*.py` | 存在 |

> 说明：提示词中列举的 `app/api/runtime/events.py`、`result_store.py` 等路径在实际仓库中位于 `app/runtime/`（已按实际结构核对）。

---

## 2. Git 状态（本次实际只读命令输出）

| 检查项 | 实际结果 |
|---|---|
| 当前分支 | `master` |
| HEAD | `f3f73300f9327f36491ce736dc3374da07a49d63` |
| 最新提交 | `f3f7330 release: prepare AutoTeam v0.6.1` |
| 标签 | `v0.6.0`、`v0.6.1`（均存在） |
| 远程 | `origin https://github.com/zzzzzz222222/-autoteam.git` |
| 工作树是否干净 | **否**（存在未提交修改 + 未跟踪文件） |
| 与远程关系 | `up to date with 'origin/master'`（本地与远程同一 HEAD，未 diverge） |

### 2.1 未提交的代码修改（8 个文件，+116 / −7）

| 文件 | 改动与 v0.6.2 候选的关系 |
|---|---|
| `app/api/routes.py` | B1 版本常量 `VERSION="0.6.1"`(:29)、B2 SSE 游标 `last=last+len(events)`(:198)、B3 team 端点暴露 `partial`(:99) |
| `app/api/runs.py` | B3 快照暴露 `partial`(:77) |
| `app/runtime/session.py` | B3 `partial_agent_ids`(:100) |
| `frontend/src/types.ts` | B3 `AgentResultDto.partial`(:18)、`AgentStatus` 增 `'partial'`(:243) |
| `frontend/src/i18n/index.ts` | B3 `agentstatus.partial` 文案 |
| `frontend/src/stores/team.ts` | B3 `result.partial ? 'partial':'success'` |
| `frontend/src/components/AgentStatus.vue` | B3 `case 'partial'` 渲染 |
| `tests/test_api.py` | B1/B2/B3 三项回归测试（+92 行） |

### 2.2 未跟踪文件（10 个）

`validation/` 下全部为审计/验证报告：
`AGENT_COLLABORATION_AUDIT.md`、`API_SSE_UI_CONSISTENCY_REPORT.md`、`EVIDENCE_PROVENANCE_AUDIT.md`、`EXECUTION_STABILITY_REPORT.md`、`ISSUE_INVENTORY.md`、`POST_RELEASE_ISSUE_INVENTORY.md`、`POST_RELEASE_REPORT_v0.6.1.md`、`REAL_WORLD_QUALITY_VALIDATION.md`、`REPORT_QUALITY_AUDIT.md`、`V0.6X_FINAL_ACCEPTANCE_REPORT.md`

**核对结论**：当前未提交的修复与前期 v0.6.2 验收报告描述**一致**（B1/B2/B3），未发现额外私自改动；B1/B2/B3 三处修复行本次已重新 `grep` 确认在位（详见 08 号报告）。

---

## 3. 版本一致性核对（v0.6.1 vs 当前工作树）

| 位置 | 声明版本 | 判定 |
|---|---|---|
| `pyproject.toml` | v0.6.1 | 一致 |
| `app/api/main.py:19` | `0.6.1` | 一致 |
| `app/api/routes.py:29` `VERSION` | `0.6.1` | 一致（B1 修复后） |
| `frontend/package.json` | 见 12 号文档报告详查 | 待核 |
| `RELEASE_NOTES_v0.6.1.md` | v0.6.1 | 一致 |

**本次未发现四处版本号彼此矛盾**（B1 修复已消除 health 端点过期暴露）。完整文档一致性详见 `12_DOCUMENTATION_AUDIT.md`。

---

## 4. 已识别的仓库卫生风险（本次新发现）

| 项 | 观察 | 影响 |
|---|---|---|
| **仓库根目录散落 60+ 个 `*.log` 调试文件** | `f_diff.log`、`r2_*.log`、`v3_*.log`、`v4_*.log`、`rel_*.log` 等，部分体积达 86 KB（`r2_cacheddiff.log`） | 仓库污染、阅读成本高；需确认其中是否含敏感信息（见 09 安全审计） |
| `.pytest_cache/`、`.ruff_cache/`、`autoteam.egg-info/` 存在于根目录 | 构建缓存 | 应确认已被 gitignore |
| `autoteam_output/`（168 文件）与实际工程并存 | 运行输出目录 | 需确认 gitignore 覆盖 |

> 以上均属**仓库卫生/组织类问题**，非功能缺陷。相关风险分别记为 `AT-AUDIT-016`（命名/重复）与 09 号报告的日志审查项。

---

## 5. 历史资料与当前代码交叉核对

已核对的历史文档（本次实际存在）：

| 历史报告 | 与当前代码是否一致的抽查结论 |
|---|---|
| `POST_RELEASE_REPORT_v0.6.1.md` | 其记录的 B1/B2/B3 修复在代码中确已存在，一致 |
| `V0.6X_FINAL_ACCEPTANCE_REPORT.md` | 记录的 8 文件修改与当前 `git status` 完全一致 |
| `TARGETED_HARDENING_REVALIDATION.md` | 记录的 D1/D2/D3/D4 修复标记已 grep 到位（`_complete_with_length_recovery`、`compute_finding_counts`、`derive_executive_summary`、`_sourcing_requirement_note`） |
| `FINAL_VALIDATION_AND_RELEASE_REPORT.md` | 历史真实运行结论本次**未逐条重算**，仅作背景参考 |

**差异记录（重要）**：本次审计对 `validation/runs/` 中最新真实运行做了独立重算，发现 headline 指标 `finding_counts.supported=9/10` 与逐 claim 的严格引用核验结果（仅 2/10 `supported_by_citation`）存在显著差距。前期报告已标注该两轴口径差为「观察项 O1」，但**未量化差距幅度**。本次将其上升为空洞的高严重度问题，详见 `07_FINAL_DELIVERABLE_QUALITY.md` 与 `AT-AUDIT-004`。

---

## 6. 本阶段检查的局限

- 未检查已删除/历史 commit 中是否曾出现过敏感信息（需历史改写范畴，超出只读审计）。
- 根目录 60+ `*.log` 为逐文件内容审查，本次仅在前 seem 安全报告中做关键词扫描（见 09 号报告）。
- `frontend/package.json` 版本细节归入 12 号文档报告。

---

## 7. 结论

- 项目结构与提示词描述基本一致，个别路径约定（如 `events.py`/`result_store.py` 位于 `app/runtime/`）已按实际更正。
- 当前工作树处于 **v0.6.1 tag + B1/B2/B3 未提交修复 + 10 份未跟踪报告** 的状态，与 v0.6.2 候选预期一致。
- 版本号四处一致，未发现版本矛盾。
- 新识别仓库卫生问题：根目录 60+ 日志散落、多处缓存/产物目录（卫生类，非阻断）。
- 已执行与被杜绝的操作：仅执行只读 git 命令；**未执行** commit/push/tag/release。
