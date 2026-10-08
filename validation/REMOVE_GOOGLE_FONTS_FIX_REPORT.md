# Remove Google Fonts Dependency — Fix Report

- 修复日期：2026-10-08
- 修复人：WorkBuddy（Agent mode，授权范围内最小前端修复）
- 目标：消除 Console 中 `fonts.googleapis.com` 的 `net::ERR_CONNECTION_TIMED_OUT`

## 1. Google Fonts 引用位置

| 文件 | 行 | 引用 |
|---|---|---|
| `frontend/src/style.css` | 1 | `@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');` |
| `frontend/index.html` | 8 | `<link rel="preconnect" href="https://fonts.googleapis.com" />` |
| `frontend/index.html` | 9 | `<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />` |

`style.css:1` 的 `@import` 是运行时实际下载字体的根因；`index.html` 的两处 `preconnect` 是同域预连接（同样构成运行时外部请求）。

## 2. 修改文件

- `frontend/src/style.css`
- `frontend/index.html`

## 3. 修改内容

- `style.css`：删除第 1 行 Google Fonts `@import`，**保留** `@import 'tailwindcss';`。
- `index.html`：删除第 8–9 行两个 `preconnect` link。
- **未改动** font-family 栈：`--at-font-sans`（`'IBM Plex Sans', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif`）与 `--at-font-mono`（`'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace`）已内置系统 fallback。移除外部导入后，浏览器在本地无 IBM Plex Sans / JetBrains Mono 时自动回退到 `system-ui` / `ui-monospace` 等系统字体——即"IBM Plex Sans 风格无衬线 / JetBrains Mono 风格等宽"的 fallback，**字体层级、字号、字重、布局完全不变**。
- 未下载新字体、未增加字体依赖、未引入新 npm 包、未修改版本号。

## 4. 是否仍存在 fonts.googleapis.com / fonts.gstatic.com

- **源码**（排除 `node_modules`）：`No matches`（Grep `googleapis|gstatic|fonts.google`）
- **dist 产物**：`No matches`
- 结论：运行期 Google Fonts 依赖已彻底移除。

## 5. npm run build

`✓ built in 3.32s`（vue-tsc 类型检查 + vite 打包，无错误）。

## 6. pytest

`628 passed`（进度 100% 全通过，无失败用例）。
说明：裸跑末行 `exit=1` 为 sandbox **safe-delete 钩子**拦截 pytest 临时目录清理所致（与本项目历次 pytest 现象一致，非测试失败）；本次仅删除 2 个前端文件，不涉及任何 Python 代码。

## 7. ruff

`All checks passed!`（exit 0）。

## 8. 是否修改 Core / API / SSE

**否。** 本次仅改 `frontend/src/style.css` 与 `frontend/index.html` 两文件，`git diff --stat` 仅显示：

```
 frontend/index.html    | 2 --
 frontend/src/style.css | 1 -
 2 files changed, 3 deletions(-)
```

未触碰 `app/runtime/`、`app/tools/`、`scheduler`、`dynamic_team`、`agent_runtime`、`artifact`、`evidence`、retry/replan、FastAPI API、SSE、Task execution、Real LLM、Tavily。

## 9. Git HEAD 是否保持不变

**是** —— `f3f73300f9327f36491ce736dc3374da07a49d63`（未变）。

## 10. Git status

- working tree 含此前多任务（AT-AUDIT-004 / RC / Final Real / B Revalidation / BUG-01）累积的未提交改动，外加本次两文件改动。
- 本次新增改动仅：`frontend/index.html`（M）、`frontend/src/style.css`（M）。
- commit / push / tag / release 全 **NO**。
- 补充确认：`REAL_EXECUTION_ENABLED=False`（未运行任何真实 LLM/Tavily）；无新增依赖；未修改版本号；未处理 BUG-02/BUG-03。

---

最终结论：最小网络依赖修复完成，前端不再请求 `fonts.googleapis.com` / `fonts.gstatic.com`，UI 字体通过系统 fallback 保持原样。建议用户在浏览器硬刷新（Ctrl/Cmd+Shift+R）后确认 Console 中 `ERR_CONNECTION_TIMED_OUT` 已消失。
