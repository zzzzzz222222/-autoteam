# BUG-01 Fix Report

- 修复日期：2026-10-08
- 修复人：WorkBuddy（Agent mode，授权范围内直接修改/测试/本地验证）
- 对应验收：UI_MANUAL_ACCEPTANCE_v0.6.2.md — BUG-01（唯一发布阻塞）

## 1. Root Cause

UI 左下角版本号由 `frontend/src/i18n/index.ts` 的 i18n 文案键 `'app.version'`（中文 + 英文两处）提供，经 `frontend/src/layouts/AppShell.vue:160` 的 `{{ t('app.version') }}` 渲染（font-mono、dim 样式，与验收截图左下角一致）。

该值停留在 `v0.6.0`——比代码实际版本（pyproject `0.6.1`、发布目标 `v0.6.2`）还旧，是早期版本遗留且后续版本 bump 时未同步更新的**纯文案常量**，不属于 Core / API / SSE / 任何运行逻辑。

## 2. Changed Files

- `frontend/src/i18n/index.ts` —— 仅 `'app.version'` 中英文两处由 `v0.6.0` → `v0.6.2`。
  - 该文件另含此前任务遗留的 `'agentstatus.partial'`（中英文）文案行，为历史未提交改动，**非本次引入**。
  - 渲染位置 `frontend/src/layouts/AppShell.vue:160` 未改动（消费同一 i18n key）。

> 工作树中 `git diff --stat` 同时列出的 `app/api/*`、`app/runtime/*`、`app/scheduler/*`、`app/synthesis/synthesizer.py`、`validation/collect.py`、`frontend/src/components/AgentStatus.vue`、`frontend/src/stores/team.ts`、`frontend/src/types.ts`、`tests/*` 等均为**此前多任务（AT-AUDIT-004 / RC / Final Real / B Revalidation）遗留的未提交改动**，本次 BUG-01 未新增其中任何一行。

## 3. Change

```
frontend/src/i18n/index.ts
  'app.version': 'v0.6.0'  →  'v0.6.2'   (中文，line 21)
  'app.version': 'v0.6.0'  →  'v0.6.2'   (英文，line 345)
```

即 UI 展示版本号：**v0.6.0 → v0.6.2**。

## 4. Verification

- **pytest**：`628 passed in 17.68s`（加 `--tb=no` 复跑确认；首次裸跑 `exit=1` 为 sandbox safe-delete 钩子拦截 pytest 临时目录清理所致，非测试失败）。
- **ruff**：`All checks passed!`（exit 0）。
- **frontend build**：`cd frontend && npm run build` → `✓ built in 3.77s`（vue-tsc 类型检查 + vite 打包，无错误）。
- **UI version check**：重新构建后 `frontend/dist/assets/index-joDkT-8a.js` 已包含字符串 `v0.6.2`；AppShell 通过 `t('app.version')` 运行时渲染，刷新 `http://localhost:8000` 左下角即显示 `v0.6.2`（版本号为运行期渲染，静态 index.html 不可见，已通过打包产物字符串确认）。
- **Browser Console**：本次改动仅为 i18n 字符串值，无任何 JS 逻辑/类型/导入变更；`npm run build` 类型检查通过、uvicorn 进程 stderr 无报错、HTTP 200。预计无新 Console 错误，但浏览器 Console 最终确认需用户在浏览器查看（本环境无法读取浏览器 Console）。

## 5. Scope Check

- Core 未修改（diff 中的 Core 文件均为历史遗留，本次未新增）
- API 行为未修改
- SSE 未修改
- Real Execution 未执行
- `REAL_EXECUTION_ENABLED = False`（`validation/run_scenario.py:64`，grep 确认，未改动）
- 无真实 API 调用（仅 build + 起 UI，未运行任何 Scenario）
- 无新增依赖（`frontend/package.json` deps 未动，`node_modules` 未变）

## 6. Git State

- HEAD：`f3f73300f9327f36491ce736dc3374da07a49d63`（未变）
- working tree：含此前多任务累积未提交改动 + 本次 `i18n/index.ts` 改动
- commit：NO　push：NO　tag：NO　release：NO

## 7. Final Verdict

**READY FOR FINAL RELEASE**

BUG-01 已修复（UI 左下角版本号 v0.6.0 → v0.6.2），pytest / ruff / frontend build 全通过，UI 重启后 `http://localhost:8000` 正常可打开，修复范围严格限定于 UI 版本文案，未触碰任何 Core / API / SSE / 真实执行闸门。

---

### ⚠️ 待办提示（不在本任务授权范围）

`pyproject.toml` 与 `frontend/package.json` 当前版本字符串为 **`0.6.1`**，与用户预期的 "Backend 0.6.2" 不一致。本任务按授权**仅修复 UI 展示来源**（`v0.6.0 → v0.6.2`），未改动 backend / 前端包版本元数据（且其当前值为 0.6.1，并非错误的 0.6.0，不在"修复 v0.6.0"的直接目标内）。

若需将 backend / 包版本元数据也统一 bump 到 `0.6.2`，请另行授权（属版本元数据对齐，非 UI 显示 bug）。BUG-02 / BUG-03 按指令本次不处理。
