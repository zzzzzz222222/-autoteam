# AutoTeam v0.6.2 UI Manual Acceptance Report

- 验收日期：2026-10-08
- 验收人：WorkBuddy（资深 AI Agent 产品 + 前端 UI QA 验收角色）
- 依据：用户提供的 16 张运行截图（Offline 组 11 张、Real 组 5 张），全部已逐张读取核验
- 边界：仅依据截图；未修改代码；未重设计 UI；未提出 v0.7.0 功能

---

## 1. Overall Verdict

**READY WITH MINOR UI FIXES**

（无 P0/P1；1 项 P2 = 全局版本号仍显示 v0.6.0；2 项 P3。修复版本号文案后即达 READY FOR RELEASE。）

## 2. Screenshot Inventory

| 编号 | 文件 | 模式 | 页面 |
|---|---|---|---|
| O-01 | 1000221358 | Offline | 运行页 run_17a4ee7e（团队就绪+工具+事件流） |
| O-02 | 1000221359 | Offline | run_17a4ee7e 团队画布 DAG（3 层 9 节点） |
| O-03 | 1000221360 | Offline | run_17a4ee7e 依赖列表 + Agent 详情 |
| O-04 | 1000221361 | Offline | run_17a4ee7e 交付物与协作流（9 卡片） |
| O-05 | 1000221362 | Offline | run_17a4ee7e 交付物详情（mock stub） |
| O-06 | 1000221363 | Offline | run_17a4ee7e 最终结果页（发现/洞察/矛盾） |
| O-07 | 1000221364 | Offline | run_17a4ee7e 结果页（权衡/建议/Citation Audit/Evidence Gaps） |
| O-08 | 1000221365 | Offline | 运行页 run_4c4e4525（5 agent 链式 + summary_derived） |
| O-09 | 1000221366 | Offline | run_4c4e4525 团队画布（链式 5 层） |
| O-10 | 1000221367 | Offline | run_4c4e4525 交付物与协作流（5 卡片） |
| O-11 | 1000221368 | Offline | run_4c4e4525 交付物详情（验收 JSON + 5 证据） |
| R-01 | 1000221369 | Real | 结果页（关键发现 1–6，左下"● 真实"） |
| R-02 | 1000221370 | Real | 结果页（关键发现 7–11：Intercom/Salesforce/ Copilot 定价） |
| R-03 | 1000221371 | Real | 结果页（跨智能体洞察 4 + 矛盾 1） |
| R-04 | 1000221372 | Real | 结果页（不确定性 3 + 权衡 3） |
| R-05 | 1000221373 | Real | 结果页（建议 5 + Citation Audit） |

分组判定说明：Offline 组 10 张带 `● 离线` 运行模式标识或 `[离线 Mock]`/`[离线搜索]`/`[offline mock]` 明示标记；Real 组 5 张带 `● 真实` 标识。两组未混淆。

## 3. Workspace — NOT CONFIRMED

16 张截图中**没有一张**是 Workspace 首页。任务输入框、Offline/Real 模式切换、Example Task、Build Team & Run 按钮均无法从截图确认。无证据表明异常，也无证据表明正常。

## 4. Team Formation — PASS（Offline）/ NOT CONFIRMED（Real）

- O-01/O-02/O-03：run_17a4ee7e 动态生成 9 agents / 3 execution layers / 21 依赖；O-08/O-09：run_4c4e4525 动态生成 5 agents / 5 layers / 4 依赖（链式）。同一任务两次运行产出**不同团队结构与拓扑**（"Discovered 9 required capabilities … decomposed into 9 roles and 9 agents arranged in 3 execution layers" vs "…5 roles and 5 agents arranged in 5 execution layers"），是动态组队（非固定假 Team）的强证据。
- 节点名称/能力/工具标签（web_search、data_analyzer、calculator）正常；DAG 分层布局清晰、无重叠节点、无连线错误、无 undefined。
- Real 模式的 Team Formation 页面未提供截图 → NOT CONFIRMED。

## 5. Execution — PASS（Offline）/ NOT CONFIRMED（Real）；SSE NOT CONFIRMED

- O-01/O-08 实时事件流带时间戳：`insights_extracted → contradiction_found → tradeoff_found → synthesis_completed → summary_derived → synthesis_validated(reference issues: 0) → task_completed SUCCESS`，事件类型与参数（insights=4 contradictions=1 tradeoffs=3 recommendations=5）具体且相互一致；页面声明"所有状态与数字均来自真实执行事件"。
- O-08 中 `summary_derived: model returned no summary; composed from validated findings/insights/recommendations … (no new facts added)` 是诚实降级路径的直接证据。
- Agent 状态全部渲染为 ✓完成，尝试次数 #1；**Retry/Replan 事件的 UI 呈现无法从截图确认**（两次运行均一次成功，未发生 retry）。
- 静态截图无法证明 SSE 实时推送本身 → 按规则标记 NOT CONFIRMED（不作为通过或失败依据）。

## 6. Tool Calls — PASS（Offline）/ NOT CONFIRMED（Real 面板）

- Offline：O-01 每次调用逐条列出工具名 + `[离线 Mock]` 徽章；O-08 web_search 带 `[离线搜索]` 徽章。工具名、状态、Offline 属性均明示。
- Real：**未提供 Real 运行页/工具面板截图**，无法直接看到 web_search/Tavily 调用展示 → NOT CONFIRMED。间接佐证：R-02 出现 Intercom Fin $0.99/解决、Salesforce Einstein Copilot $50/用户/月、Microsoft Copilot $30/用户/月、Zapier Central、Ada 等真实市场定价与"1 来源"标注，R-03 矛盾卡片含 `dropped unresolved source ids: ['src_…']`——与真实检索产出一致，但按规则不作推断性认定。

## 7. Evidence — PASS

- 证据计数贯穿全部页面：运行页顶部指标（19/36）、右侧面板、交付物卡片（如"1 上游 · 1 下游消费者 · 5 来源 · 9 证据"）、结果页每条发现的徽章（"2 证据 · 0 来源 · 2 相关 Agent"）。
- 发现与证据绑定：每条 finding 携带证据数/来源数/相关 Agent；矛盾与不确定性卡片内嵌 `ev_…` 可点击链接（O-06：ev_0894b40c92 · ev_62b3f9b7d7；R-03：ev_67d98f35d664）。
- O-11 交付物详情"关键验收"JSON（fact_with_external_support / conclusion_from_multiple_sources）+ 5 条结构化证据，证明证据是执行结果的一等公民，不是装饰。
- 无空 Evidence 列表、无明显重复、无 undefined/null。

## 8. Sources — PASS（计数与诚实标记）/ 部分 NOT CONFIRMED（URL 列表页）

- Offline：O-05 来源条目正文明示 `[offline mock] overview/key players/recent signals` + `[offline mock]` 类型徽章——离线来源不伪装真实 URL。
- Real：5 来源/36 证据计数一致贯穿；真实定价事实与来源绑定（R-02 每条含"1 来源"）。
- **来源列表页/URL 明文展示未出现在任何截图** → 无法确认 URL 可读性、重复来源检查 → 该子项 NOT CONFIRMED。

## 9. Artifacts — PASS

- O-04/O-10 交付物卡片明确携带：阶段徽章（依赖深度 0/1/2/3/4）、类型徽章（research_findings/requirement/analysis/proposal/report）、产出 Agent、上游/下游消费者/来源/证据计数。
- O-05/O-11 详情页展示"上游交付物"标签链与"下游消费者"标签链，完整呈现 Agent A → Artifact A → Agent B → Artifact B → Final Report 链路（如 O-05 顶部 6 个上游交付物标签）。
- Markdown/JSON 内容渲染正常（O-11 关键验收 JSON、O-10 中文报告正文），无空白异常。

## 10. Final Result — PASS

- Offline（O-06/O-07）：标题 + 目录（章节计数）+ 分节渲染 + `[offline mock]` 前缀 + 黄色警示 `offline stub — verify against real evidence` / `offline mock recommendation — not a market verdict` + Citation Audit + Evidence Gaps。
- Real（R-01–R-05）：标题 + "7 章节 · 5 来源 · 36 证据"徽章 + 复制/保存 .md 按钮 + 11 条关键发现 + 4 洞察 + 4 矛盾/不确定 + 3 权衡 + 5 建议 + Citation Audit + Evidence Gaps。
- 结果内容与任务强相关（AI Agent 市场/SMB 痛点/定价/切入建议），且**大量发现被诚实标注 `unsupported` / `not_checked`**（黄色徽章）——结果看起来是本次任务真实生成，且未粉饰支持状态。
- 复制/保存 .md 按钮可见，功能本身无法从截图确认。

## 11. Offline vs Real Comparison

| 项目 | Offline | Real | 结论 |
|---|---|---|---|
| Workspace | NOT CONFIRMED | NOT CONFIRMED | 双方均无截图 |
| Team | PASS（2 个不同动态团队） | NOT CONFIRMED | Offline 证明动态组队 |
| Execution | PASS（事件流完整） | NOT CONFIRMED | — |
| Agent Status | PASS（✓完成/尝试次数） | NOT CONFIRMED | — |
| Tool Calls | PASS（[离线 Mock]/[离线搜索]） | NOT CONFIRMED（结果页间接佐证） | Real 面板缺截图 |
| Evidence | PASS | PASS（计数+绑定一致） | 信息架构一致 |
| Sources | PASS（mock 明示） | PASS（计数）/URL 页 NOT CONFIRMED | Offline 不伪装 |
| Artifacts | PASS | NOT CONFIRMED（详情页未截） | — |
| Final Result | PASS | PASS | 结构完全一致 |
| UI 稳定性 | PASS（无 undefined/NaN/错位） | PASS | 两模式同一信息架构 |

核心回答：
1. 两模式信息架构一致（同一结果页模板、同一徽章体系、同一 Citation Audit/Evidence Gaps 段落）。
2. Real 模式结果页呈现真实市场定价事实与 src/ev 引用（间接），但真实 Tool/Search 面板未被截图证明。
3. Offline 明确表现为 Offline：`[offline mock]`、`deterministic stub — no real LLM or live tools involved`、`offline stub — verify against real evidence` 三重明示，绝不伪装 Real。
4. 两模式数据结构一致（同一 finding/insight/tradeoff/recommendation 卡片模型）。
5/6/7. 未发现 Real 特有 UI Bug；Real 独有区域（运行页/工具面板）因缺截图无法判断。

## 12. Visual / UX Assessment

- **Layout**：三栏（导航/内容/指标栏）稳定，16 张无一错位；卡片网格与依赖列表对齐良好。
- **Typography**：标题/正文/辅助三级清晰；**状态徽章与"适用前提"小字字号偏小、对比度偏低**（见 BUG-02）。
- **Spacing**：卡片间距与分节留白均匀，密度符合 developer tool 定位。
- **Information hierarchy**：目录计数 → 分节 → 卡片 → 徽章 → 证据链接，层级完整；`ev_…`/`src_…` 以链接样式可点击。
- **Status visualization**：蓝=支持类、绿=支持路径、黄=警示/unsupported、紫=跨 Agent/规划假设，语义一致且克制。
- **Developer Tool professionalism**：接近 Linear/Vercel 深色风格；`dropped unresolved source ids: ['src_…']` 这类原始调试信息直接呈现，符合目标用户（开发者），不算缺陷。

## 13. Bugs Found

| ID | Screenshot | Severity | Page | Problem | Release Impact |
|---|---|---|---|---|---|
| BUG-01 | 全部 16 张（左下角） | **P2** | 全局 | 版本标识显示 **v0.6.0**，当前发布版本为 v0.6.2 | 正式发布前应修正（一处文案），否则发布产物自报错误版本 |
| BUG-02 | R-01–R-05、O-06/O-07 | P3 | 结果页徽章 | 状态徽章与前提小字字号小、对比度低，难以快速读取（如"引用路径: unsupported"黄标） | 不影响发布；建议提高一档字号/对比 |
| BUG-03 | O-08–O-11 | P3 | 运行模式语义 | run_4c4e4525 模式标签为"离线"，但交付物为真实 LLM 中文内容（搜索侧由 `[离线搜索]` 徽章区分）——语义自洽但对新用户可能歧义 | 不影响发布；可选区分"LLM 通道/搜索通道" |

No P0 / No P1. 无 undefined / null / NaN / 空白异常 / 明显截断。

## 14. Missing Evidence（无法从截图确认）

1. Workspace 首页全部要素（输入框/模式切换/Example Task/Build Team & Run）。
2. Real 模式的运行页、团队画布、执行时间线、工具调用面板、交付物页（R 组仅覆盖结果页）。
3. SSE 实时推送本身（静态截图不可证）。
4. Retry / Replan 事件的 UI 呈现（两次运行均 attempt #1，未触发）。
5. 来源列表页与 URL 明文展示（两组均未截到）。
6. 复制 / 保存 .md / EN 切换的实际功能。

## 15. Release Recommendation

> 从截图能够确认的范围来看：**可以正式发布，但应先修复 BUG-01（版本号 v0.6.0 → v0.6.2）**。

结论：**READY WITH MINOR UI FIXES** — 无 P0/P1；核心链路（Task → Team → Execution → Tool → Evidence → Artifacts → Final Deliverable）在截图中完整、诚实、一致地呈现；Offline 不伪装 Real；证据/引用审计深度融入 UI。修复一处版本号文案后即为 READY FOR RELEASE。注意：本结论仅覆盖截图可见范围，第 14 节所列 NOT CONFIRMED 项不由本报告背书。
