# AutoTeam v0.6.2 Candidate — 09 安全与隐私审计

> 审计日期：2026-10-03｜只读审计。
> **重要约束遵循**：本报告中**不打印任何真实 Secret 值**；疑似命中仅给出文件路径、行号与 Secret **类型**。

---

## 1. 扫描范围与方法

| 范围 | 内容 |
|---|---|
| 凭据文件 | `.env`、` .env.example`、`.gitignore` |
| 源码 | `app/**/*.py`、`frontend/src/**/*.{ts,vue}` |
| 测试 | `tests/**/*.py` |
| 历史报告/运行产物 | `validation/**`（含 `runs/`） |
| 日志 | 根目录 `*.log` 若干（见 01 号报告的仓库卫生说明） |
| Git 跟踪文件 | `git ls-files` |

正则：`(api_key|apikey|secret|token|password|Bearer |AKIA|sk-[A-Za-z0-9]{20,})`

---

## 2. 扫描结果

### 2.1 Git 跟踪与凭据文件 ✅

| 检查 | 结果 |
|---|---|
| `.env` 是否被 Git 跟踪 | **否**（`git ls-files --error-unmatch .env` 返回 “Did you forget to 'git add'?”） |
| `.gitignore` 相关规则 | `:16 .env`、`:17 .env.*`、`:18 !.env.example`（**白名单保留示例文件**） |
| `validation/runs/` 是否忽略 | **是**（`.gitignore:44`） |

**判定**：✅ **CLEAN** —— 真实环境文件与运行产物均未被跟踪。

### 2.2 源码 Secret 硬编码扫描

- 源码（app + frontend/src）命中总数：**55**
- **逐条判别后确认**：全部为**变量名 / 参数名 / 字段名**，例如：
  - `app/llm/provider.py:83` `api_key: str`,（构造函数形参）
  - `app/llm/provider.py:176` `if not api_key:`（读取环境变量结果）
  - `app/llm/client.py:15` `OpenAI(api_key=settings.llm_api_key, ...)`（注入配置值）
  - `provider.py:310-312` `token in prompt...startswith("ev_")`（**文本 token 解析**，非凭据）
  - `agent_runtime.py:200,215,260,295` `length_limit_token_cap` / `_token_ceiling`（**LLM token 计数**，非密钥）
- **未发现**任何 `sk-<20+字符>` 形式的真实密钥字面量、`AKIA...`、或硬编码 Bearer token

**判定**：✅ **未发现已知泄漏**（源码层面 0 处真实 Secret）。

### 2.3 Provider 层的密钥隔离设计（正向证据）✅

`app/llm/provider.py:33-45` 文档明确：
> The message intentionally contains only the exception type ... It **never contains the API key, request headers or the raw response**.

`:138-142` `last_response_meta` 仅保存 `finish_reason` 与聚合 `usage`（注释 `:95-97` 明示不含 key/headers/raw prompt/response）。
`:120-122, :128` 异常统一包装为 `f"LLM provider call failed: {type(exc).__name__}"` —— **仅类型名**。

**判定**：✅ 这是良好的设计证据，不是巧合。

### 2.4 前端是否访问 Secret

- `frontend/src/types.ts` 全量阅读：**无任何** apiKey / secret / token / Authorization 字段
- 前端仅通过 `/api/*` 消费成品数据，不含凭据处理逻辑
- **判定**：✅ CLEAN

### 2.5 测试中的“假密钥”

- `tests/test_api.py:205` 出现 `assert "sk-super-secret-98765" not in dumped`
- **性质判定**：这是**反泄漏断言**（验证序列化输出不含该类字符串），属**安全正向测试**，**不是真实 Secret**
- 其余测试中的 `sk-abc…` / `pass@example.com` 类占位符均为 fixture 假数据

---

## 3. 未发现 vs 不能断言

**已确认干净项**：
1. 源码无真实 Secret 硬编码
2. `.env` 未入库且已被 ignore
3. Provider 错误/元数据不含密钥或原文
4. 前端不接触 Secret
5. 测试中的密钥字符串均为假数据/反泄漏断言
6. 后台线程异常被截断（200 字符）且不向端点输出（详见 `AT-AUDIT-008`，反过来也避免了堆栈外泄）

**⚠️ 不能断言「项目绝对不存在 Secret 泄漏风险」的原因（诚实披露）**：
- 本次**未审计**已提交的 Git **历史** commit 内容（若历史上曾误提交，需历史改写，超出只读范围）
- 根目录存在 **60+ 个 `*.log`** 历史调试文件（见 01 号报告），本次仅做关键词扫描，**未逐文件内容细读**
- 未做 SAST 工具深度扫描（如 semgrep / bandit）

---

## 4. 其他安全相关检查

| 检查项 | 结果 | 状态 |
|---|---|---|
| 跨 Task 数据污染 | **发现风险**：单例 `ResultStore` 跨 run 保留 events，且 `status_of` 可能返回上一 run 状态 → 不同任务间状态串味 | ⚠️ 见 `AT-AUDIT-002`（03 号报告） |
| 不安全文件路径处理 / 路径穿越 | 未发现 `task_id` 直接拼接路径的证据；但**未逐文件核实** | NEEDS_VALIDATION |
| Markdown / HTML 渲染消毒 | **未核实**前端 markdown 组件是否 sanitize | NEEDS_VALIDATION（08 号报告同步记录） |
| 不受控外部 URL | Source URL 直接来自检索结果并由前端展示为链接；未见校验/白名单 | INFO（属设计，建议前端展示加 `rel=noopener`） |
| 工具参数校验 | `validate_allowed` 覆盖权限；参数值语义校验**未核实** | NEEDS_VALIDATION |
| 旧路径权限旁路 | legacy `_run_tools` 绕过 `agent.tools` | ⚠️ `AT-AUDIT-012`（安全性次生影响） |

---

## 5. 安全问题清单（本次）

| 编号 | 严重度 | 标题 | 状态 |
|---|---|---|---|
| — | — | 源码硬编码 Secret | **未发现已知泄漏** |
| — | — | `.env` 入库 | **未发现**（已 ignore） |
| AT-AUDIT-002 | HIGH | ResultStore 跨 run 数据污染（跨 Task 隔离失效） | CONFIRMED（安全次生影响） |
| AT-AUDIT-012 | MEDIUM | legacy 路径绕过工具权限边界 | CONFIRMED |
| — | INFO | 前端 Markdown 消毒 / 路径穿越 / 工具参数深层校验 | NEEDS_VALIDATION |

---

## 6. 结论

**Secret 泄漏：未发现已知泄漏。**
凭证处理设计良好（环境变量注入 + 错误不含密钥 + `.env` 已 ignore + 测试含反泄漏断言）。

但本项目在**数据隔离**层面存在一个 HIGH 级的次生安全风险（`AT-AUDIT-002`：单例 ResultStore 跨 run 状态污染），建议在发布前与 03 号报告一并处理。

安全检查本身存在覆盖边界（未审计 Git 历史、未细读全部日志、未做 SAST），因此**不能**断言“零泄漏风险”。
