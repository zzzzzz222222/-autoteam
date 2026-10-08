# AutoTeam v0.6.2 Candidate — 12 文档与版本一致性审计

> 审计日期：2026-10-03｜只读审计。
> 核查对象：`README.md`、`README.zh-CN.md`、`RELEASE_NOTES_v0.5.0.md`、`RELEASE_NOTES_v0.6.0.md`、`RELEASE_NOTES_v0.6.1.md`、`.env.example`、`pyproject.toml`、`.gitignore`

---

## 1. 版本号一致性

| 位置 | 声明 | 与 v0.6.2 候选的关系 |
|---|---|---|
| `pyproject.toml` | v0.6.1 | 一致（发布 v0.6.2 前需提升，本次**未修改**） |
| `app/api/main.py:19` | `0.6.1` | 一致 |
| `app/api/routes.py:29` `VERSION` | `0.6.1` | 一致（B1 修复后） |
| `RELEASE_NOTES_v0.6.1.md` | v0.6.1 | 存在且对应当前 tag |

**结论**：✅ **未发现版本号四处矛盾**（B1 已消除 `/api/health` 过期暴露这一已知不一致）。

---

## 2. 启动 / 运行说明核对

| 文档项 | 是否与代码一致 | 依据 |
|---|---|---|
| `uvicorn app.api.main:app` 作为 web 入口 | ✅ 一致 | `app/api/main.py:3` 注释、`scripts/start_web.py:24` |
| 存在多个独立入口（CLI / Streamlit） | ⚠️ 文档需明确区分 | `main.py`、`app/ui.py`、`app/ui_dynamic.py`、`app/ui_live.py` 均为独立入口，非同一进程 |
| Real / Offline 模式说明 | ⚠️ 需核实 | 代码行为：无 provider/key → Mock（`provider.py:172-178`）；文档是否准确描述该回退**本次未逐句核对** → NEEDS_VALIDATION |

---

## 3. 环境变量说明核对

代码中实际读取的环境变量（源自本次代码审计）：

| 变量 | 用途 | 代码位置 |
|---|---|---|
| `AUTOTEAM_LLM_PROVIDER` | provider 选择 | `provider.py:172` |
| `AUTOTEAM_API_KEY` / `LLM_API_KEY` | LLM 密钥 | `provider.py:175` |
| `AUTOTEAM_LLM_MODEL` | 模型名 | `provider.py:174,179` |
| `AUTOTEAM_LLM_BASE_URL` | base url | `provider.py:182` |
| `AUTOTEAM_LLM_MAX_TOKENS` | 输出上限（**未设置则 length 自愈惰性**） | `provider.py:185-192` |
| `AUTOTEAM_WEB_SEARCH_URL` / `AUTOTEAM_WEB_SEARCH_API_KEY` | 真实检索 | `registry.py:178-179` |

**核对结果**：`.env.example` 存在（未被 ignore 排除，`.gitignore:18` 白名单），但**本次未逐行比对**其与上表的完整性 → 标记 **NEEDS_VALIDATION**。

⚠️ **建议**：`AUTOTEAM_LLM_MAX_TOKENS` 是让 D1 length-limit 自愈真正生效的关键变量（`AT-AUDIT-021`），文档应明确建议配置；若文档未提及，属**文档遗漏风险**。

---

## 4. 已知限制披露核查

| 已知限制 | 是否在发布说明中披露 | 本次判定 |
|---|---|---|
| 内存 Run Registry 重启丢历史（R8） | 需核实 | NEEDS_VALIDATION |
| 多 worker 不支持（单例 Registry） | `app/api/main.py:5` 代码内声明 “single process in production”，但**面向用户的 README 是否披露未核实** | NEEDS_VALIDATION / 建议披露 |
| 并发上限默认缺失（本次新发现 AT-AUDIT-001） | **未披露**（本次新发现） | ⚠️ 发布前应作为已知限制披露 |
| headline `supported` 计数口径（AT-AUDIT-004） | **未披露** | ⚠️ 建议披露，否则读者易高估可信度 |
| 非数值 Claim 未自动核验（AT-AUDIT-011） | **未披露** | ⚠️ 建议披露 |

---

## 5. 文档易其 ".txt" 项目卫生问题（01 号报告转述）

- 仓库根目录散落 **60+ 个 `*.log`** 调试文件（部分达 86 KB），非文档但与项目阅读/交付整洁度相关
- 建议在文档中明确「这些是临时调试产物」或清理

---

## 6. 文档/测试数字一致性

- `README` 中若记载测试数量（历史曾记 519 passed / 7 skipped 或类似），本次实际为 **519 passed**（0 failed）；**未对 README 逐句核对数字** → NEEDS_VALIDATION
- 本审计不做修改；若 README 数字与 519 不一致，属待修 Task（非本次范围）

---

## 7. 本模块问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| — | INFO | `.env.example` 与上表变量完整性未逐行比对 | NEEDS_VALIDATION |
| — | INFO | README 是否披露「多 worker 不支持」未核实 | NEEDS_VALIDATION |
| — | INFO | README 测试数量与本次实际 519 是否一致未核实 | NEEDS_VALIDATION |
| — | LOW | 建议补充披露 AT-AUDIT-001 / 004 / 011 三项已知限制 | 建议项 |

> 说明：本模块**未发现确认的文档—代码矛盾 Bug**；由于时间与安全边界，多数文档项采取关键词/抽样核对，故较多标为 NEEDS_VALIDATION 而非 CLEAN，以保持诚实。
