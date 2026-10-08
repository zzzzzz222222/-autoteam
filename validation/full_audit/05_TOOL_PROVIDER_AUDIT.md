# AutoTeam v0.6.2 Candidate — 05 工具 / Provider / Web Search 审计

> 审计日期：2026-10-03｜只读审计，未修改任何代码、未发起任何真实 API 调用。
> 主要文件：`app/llm/provider.py`（完整阅读）、`app/tools/registry.py`（关键函数）、`app/runtime/tool_selector.py`（完整阅读）、`app/config.py`

---

## 1. LLM Provider

### 1.1 Provider 解析与 Mock/Real 隔离 ✅

- `app/llm/provider.py:167-195` `get_llm_provider()`：
  - 无 `AUTOTEAM_LLM_PROVIDER` 或为 `mock` → `MockLLMProvider`（:172-174）
  - 有 provider 但无 key（`AUTOTEAM_API_KEY` / `LLM_API_KEY`） → **回退 Mock**（:175-178），注释明确："No key configured -> fall back to mock so the demo still runs offline."
  - provider=deepseek → 默认 base_url `https://api.deepseek.com/v1`、model `deepseek-chat`（:179-184）

**判定**：Mock 与 Real 由环境变量显式区分，离线优先级安全 ✅。**未发现 Mock 冒充 Real 的代码路径**。

### 1.2 敏感信息隔离（关键安全约束）✅

- `ProviderError`（:33-45）注释明确：
  > The message intentionally contains only the exception type ... It never contains the API key, request headers or the raw response.
  > `diagnostics` carries non-reversible facts (length, hash, delimiter balance), never the model's raw text.
- `last_response_meta`（:138-142）**仅**保存 `finish_reason` 与聚合 `usage`；注释 :95-97 "never contains the key, headers or the raw prompt/response text"
- 认证失败/传输异常统一包装为 `ProviderError(f"LLM provider call failed: {type(exc).__name__}")` —— **只暴露异常类型名**（:120-122, :128）

**判定**：✅ CLEAN —— Provider 错误码明确不含密钥/header/原文。

### 1.3 Token / Usage 统计 ✅（诚实设计）

- `usage` 从 `response.usage` 提取 `prompt_tokens`/`completion_tokens`/`total_tokens`（:131-137）
- `usage_available` 显式标记是否观测到 usage（:141）
- **缺失时不臆造**：`usage_meta or None` → 缺失报 None

**判定**：✅ 未发现 token 重复计数或缺口臆造。

### 1.4 ⚠️ `max_tokens` 仅在显式配置时发送（导致 D1 恢复分支惰性）

- `provider.py:111-115`：仅当 `AUTOTEAM_LLM_MAX_TOKENS` 已配置才写入请求 `max_tokens`；否则**不发该参数**（兼容不同 OpenAI 兼容端点）
- `provider.py:185-192`：环境变量缺失 → `max_tokens=None`
- **后果**：`_complete_with_length_recovery`（`agent_runtime.py:327-370`）的 ×1.5 自适应增长分支在真实环境中**从未被触发**（无 max_tokens 可增长，仅走 hint-only 兼容路径）
- **判定**：`AT-AUDIT-021 / INFO / DESIGN_LIMITATION`
- **建议**：若在发布 Docs 中推荐配置该变量，可让 length-limit 自愈真正生效（当前仅有离线 12 项测试证据）。

### 1.5 超时与重试导致的重复费用

- `scheduler._with_timeout`（`scheduler.py:163-166`）使用 `asyncio.wait_for`：超时后取消协程并转 `TimeoutError` → FAILED → 重试
- **风险**：重试会对 LLM 重新发起请求；若首次请求已在服务端产生消耗且已计费，重试将**产生重复计费**
- **判定**：INFO（设计取舍，非缺陷）；未见预算红线之外的成本保护（预算配额由 `CountingProvider` 原子预约，详见前期报告）

---

## 2. ToolRegistry

### 2.1 权限与校验 ✅

- `validate_allowed`（`registry.py:306-324`）：未注册 → `ToolNotFound`；已注册但未授权 → `ToolNotAllowed`；两者均在 `execute` 前抛出
- `agent.tools is None` → 拒绝
- **工具白名单来自 `CAPABILITY_TOOLS`**（`tool_selector.py:26-46`），缺省即拒绝 ✅

### 2.2 工具异常信息是否泄漏给前端

- 工具失败以 `ToolResult`(with `error`) 形式回填（`registry.py` 相关路径）
- `web_search` 失败回填 `error="web search failed: {type(exc).__name__}"`（:230）—— **仅类型名，不含响应原文或密钥** ✅
- 后台线程异常被截断 200 字符并存入 handle（`runs.py:229-232`），但不向 API 输出（见 `AT-AUDIT-008`）

**判定**：✅ 未发现工具异常信息泄漏路径。

### 2.3 ⚠️ legacy 路径绕过权限（已列入前模块）

`agent_runtime.py:880-893` `_run_tools(behavior.tools, ...)` 直接执行，**未调用 `validate_allowed`** → `AT-AUDIT-012 / MEDIUM`。

### 2.4 离线模式是否可能意外调用真实工具 ✅

- `session.py:149-150`：provider 为 None/Mock 时**强制** `tool_mode="mock"`，工具遵循 mock 路径
- `registry.py:86` 显式 `stubs = _offline_web_results(query)` 分支
- **判定**：✅ 未发现离线模式下意外调用真实工具的路径。

---

## 3. Web Search / Tavily

### 3.1 双模设计与 Fallback ✅

- `registry.py:168-232` `web_search`：
  - 需要 `AUTOTEAM_WEB_SEARCH_URL` + `AUTOTEAM_WEB_SEARCH_API_KEY`（:178-179）才走真实 POST（Tavily 兼容，JSON `{"query":...}`，`Authorization: Bearer`）
  - 失败（超时/坏响应/校验）→ 降级 `_offline_web_results`，并**回填 `error` 字段**（:223, :230）
- **Fallback 标记诚实**：降级结果带 error 标记，不会伪装成真实检索 ✅

### 3.2 真实搜索验证（复用既有运行，非新增调用）

- 既有真实运行 `run_f4c191c6`：9 次真实检索、0 次 offline 回退（`offline_fallback=0`），36 个 Source 全部为 `web` 类型、URL 全部以 `http(s)` 开头、无畸形 ✅
- **判定**：真实路径可用且标记准确。

### 3.3 风险与限制

| 项 | 说明 | 严重度 |
|---|---|---|
| Source 仅保存元数据 | 仅存 URL/title/snippet，`access_status` 字段在真实运行中**全为空**（见 07 号报告）→ 无法证明 URL 内容曾被实际抓取核验 | INFO（`AT-AUDIT-023`） |
| 检索召回不足 | 真实运行中 8 个来源缺口（4 high / 4 medium），源于 claim 无法绑定到检索片段 → 诚实降级而非崩溃 | INFO（见 07 号报告） |
| 搜索次数上限 | 未见单次/全局搜索次数硬上限（D4 设计：授权不等于强制调用） | INFO |

### 3.4 Mock/Real 日志混淆 ✅

- Mock provider 输出统一带 `[mock]` / `[offline_mock]` 前缀（`provider.py:225-236, 320, 329`）；Mock evidence 显式标注 `derivation="deterministic offline stub (no external data)"`、claim_type `unverified_claim`（:327-329）
- **判定**：✅ Mock 内容在产出中自带可识别标记，不易被误认为真实结果。

---

## 4. 本模块问题汇总

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| AT-AUDIT-012 | MEDIUM | legacy `_run_tools` 绕过工具权限校验 | CONFIRMED |
| AT-AUDIT-021 | INFO | `AUTOTEAM_LLM_MAX_TOKENS` 未设置 → length-limit 自愈分支惰性 | DESIGN_LIMITATION |
| AT-AUDIT-023 | INFO | Source `access_status` 为空，无法证明内容被实际抓取 | DESIGN_LIMITATION |

**未发现的问题（避免夸大）**：
- ❌ 未发现真实 API Key 硬编码或日志泄漏凭证（详见 09 号报告）
- ❌ 未发现 Mock 冒充 Real 的执行路径
- ❌ 未发现空响应被判成功（至少 artifact 路径由 `validate_artifact` 拦截）
- ❌ 未发现 token 统计臆造（缺失报 None）
