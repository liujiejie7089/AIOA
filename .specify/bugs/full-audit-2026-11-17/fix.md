# Bug Fix Report: AIOA 全项目审查 18 项

- **Slug**: full-audit-2026-11-17
- **Date**: 2026-11-17T19:30:00+08:00
- **Assessment**: `.specify/bugs/full-audit-2026-11-17/assessment.md`
- **原则**: 最小代码；评估阶段不改源码，本阶段才动手；逐项对应 assessment 编号。

## 改动清单

### Python agent（C1 / H4 / L2，L3 为误报未改）

| 项 | 文件 | 改动 |
|---|---|---|
| C1 | `agent/aios_ai/tools/sandbox.py` | `BLOCKED_NAMES` 增 `getattr`/`hasattr`；`_validate_ast` 遍历所有 `ast.Constant` 字符串，命中任一 `BLOCKED_DUNDERS` 子串即拒绝。堵住 `getattr(obj,"__class__")` 与动态 dunder 名两条绕过路径。 |
| H4 | `agent/aios_ai/tools/web_search.py` | 新增 `_assert_public_url()`：拒回环/私网/链路本地/组播/保留地址与非 http(s)；`run_fetch` 先校验且 `follow_redirects=False`，堵住 302 跳转绕过。`run_search` 用固定 bing host，不受影响。 |
| L2 | `agent/aios_ai/errors.py` | `internal_payload(None)` 文案不再提「错误编号」，与「载荷无 errorId」一致；有 trace_id 时保持原文案+编号。 |
| L3 | — | **误报，未改**。回源 `nodes.py:769` 只打印 `[c["name"] for c in rescued]`（工具名列表），不含 `arguments` 参数，不存在敏感参数外泄。 |

### Java 后端（H1 / M1 / H2 / L1 / M2 / M3 / M4）

| 项 | 文件 | 改动 |
|---|---|---|
| H1 | `SqlQueryToolService.java` | `injectTenant` 删掉「SQL 含 tenant_id 就原样放行」分支，无条件追加当前租户条件；顺带修 `mainTableAlias` 把 `WHERE` 误判成表别名（曾生成 `WHERE.tenant_id` 语法错），用关键字集合排除。 |
| M1 | `SqlQueryToolService.java` + `ToolGatewayService.java` | 两处 catch 不再把 `e.getMessage()` 外发，改固定文案「SQL 查询失败，请检查语句后重试」/「工具调用失败，请稍后重试」；原始异常仍进日志。 |
| H2 | `FileController.java` | `download` 由 `selectById` 裸查改为按 `id + user_id + tenant_id` 联合查询，与 `list` 的私有文件口径一致。 |
| L1 | `FileController.java` | 分页 size 加 `Math.min(..., 200)` 上限。 |
| M2 | `OrgStatMapper.java` + `DashboardService.java` | 新增 `countOverviewByInstitutions()` 一次聚合四类计数（LEFT JOIN + GROUP BY），`tenantOverview` 按 id 归并，消除每机构 4 次查询的 N+1。 |
| M3 | `StartupCheckRunner.java` | 种子口令校验日志移除口令占位符，只记 matched 与 status。 |
| M4 | `DashboardService.java` | `orgQuota` 查询的 catch 补 `log.warn`；类加 `@Slf4j`。 |

### 前端（H3 / M6 / M7 / L4 / L5 / L6 / M5）

| 项 | 文件 | 改动 |
|---|---|---|
| H3 | `user-client/index.html` | 新增 `escJs()`（HTML 转义后再转义反斜杠与单引号，而非 `&#39;`——后者会被 HTML 属性解析还原）；三处内联 onclick（技能名/权限码/附件URL）改走它；新增 `safeUrl()` 拒绝 `javascript:` 伪协议，附件 href 与 window.open 均走它并加 `rel=noopener`。 |
| M6 | `user-client/index.html` | 上传前 `file.size > 50MB` 拦截，与后端 `FileController` 上限同口径。 |
| M7 | `user-client/index.html` | `API._sse` 遇非 200 先读响应体错误信封，用 `envelopeError()` 取人话原因再抛。 |
| L4 | `user-client/index.html` | 会话 token 由 localStorage 改 sessionStorage（关闭标签即失效）；登录读回兼容旧 localStorage 并自动迁移清除；登出/失败双清。 |
| L5 | `user-client/index.html` | 会话相关路径段（conversations id）统一 `encodeURIComponent`。 |
| L6 | `user-client/index.html` | 流式 delta 用 `requestAnimationFrame` 合并，避免逐字强制重排；回调内检测 `.ans` 已排版则不回退成纯文本（防破坏上轮 Markdown 修复）。 |
| M5 | `web/apps/shell/src/views/LoginView.vue` | redirect 只接受 `^\/(?![\/\\])` 站内相对路径，外链/协议相对一律回落 `/home`。 |

## 未改动的说明

- L3：误报（见上）。
- 无新增数据库迁移；无配置变更；无依赖升级。
