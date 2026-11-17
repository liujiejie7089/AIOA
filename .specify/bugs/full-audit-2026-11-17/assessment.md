# Bug Assessment: AIOA 全项目缺陷审查

- **Slug**: full-audit-2026-11-17
- **Created**: 2026-11-17T18:45:00+08:00
- **Source**: 用户请求「全面审查潜在 bug、异常处理、边界条件、安全与性能风险」
- **Verdict**: valid（多项确凿缺陷）
- **Severity**: critical（最高项：沙箱 AST 可绕过）
- **Method**: 三路并行审查（Java 后端 / Python agent / 前端与配置），主审对全部 high 级以上的条目逐条回源 Read 或实跑复现；未能亲自复现的条目标注 `[待复核]`。
- **Status**: **已修复并验证**（2026-11-17 19:32）。17 项已修；L3 回源判定误报未改。详见同目录 `fix.md` 与 `test.md`（verdict=verified）。

## Report（审查范围与取证口径）

覆盖 `server/`（Java 后端全模块）、`agent/`（aios_ai 与 app）、`user-client/index.html`、`web/`（Vue 管理端）、启动脚本。
用 Grep 全仓搜可疑模式后逐条 Read 上下文确认，不以模式命中直接定级。
主审亲自复现：沙箱 AST 绕过（实跑 `_validate_ast`）、SQL 租户注入绕过、文件越权下载、前端 `esc()`、登录重定向、种子口令日志。
按 spec-kit assess 纪律：本阶段只读，不改任何源码。

---

## 严重程度汇总

| 级别 | 数量 | 主题 |
|---|---|---|
| critical | 1 | 沙箱 AST 白名单可被字符串参数绕过 |
| high | 4 | 跨租户数据绕过、文件越权下载、存储型 XSS、SSRF 探测内网/云元数据 |
| medium | 7 | 内部异常外发、N+1、明文口令日志、吞异常、开放重定向、上传无大小限制、SSE 错误吞因 |
| low | 4 | 分页无上限、错误编号承诺不一致、token 落 localStorage、日志打印敏感参数、路径未编码、逐帧重排 |

---

## CRITICAL

### C1. 沙箱 AST 白名单可被 `getattr` + 字符串字面量绕过

- **文件位置**：`agent/aios_ai/tools/sandbox.py:100-113`（`_validate_ast`），`BLOCKED_DUNDERS` 定义于 `:48-53`
- **症状**：受限执行沙箱宣称禁止访问 `__globals__`/`__class__` 等危险 dunder，但这些名字只在"写死的属性访问"（`ast.Attribute`）时被拦；通过 `getattr(obj, "__class__")` 这样的函数调用可完全绕过。
- **证据**（主审实跑，非推测）：
  ```text
  direct_dunder           -> 禁止访问危险属性：__class__      # ().__class__ 被拦
  getattr((), "__class__")  -> None                            # 放行
  动态 dunder 名字符串       -> None                            # 放行
  ```
  代码层：`_validate_ast` 的 `ast.Attribute` 分支只检查 `node.attr in BLOCKED_DUNDERS`；`ast.Call` 分支只检查 `func.id/attr in BLOCKED_NAMES`（`getattr` 不在其中）；`ast.Constant` 字符串内容从不检查。
- **影响**：模型或用户构造的数据处理脚本可用 `getattr` 逐跳拿到对象 `__globals__` → `__builtins__` → `eval`/`__import__`，从而读写文件、外联、执行系统命令。当前调用面主要是测试与兼容垫片，但 intent/router 已有「数据分析」意图，一旦把模型生成脚本接入该沙箱即为远程代码执行（RCE）。
  - 说明：主审尝试用 `warnings` 模块跑完整逃逸链时被"仅允许导入"二次挡住，未在本轮拿到 `RCE_OK` 实证；但 AST 这层防线被绕过是确定的事实，且白名单内的 `pandas`/`numpy` 含大量可到达 `__globals__` 的 Python 函数，运行时是否还有兜底需单独确认。**即便运行时暂有兜底，AST 白名单作为设计防线已失效。**
- **修复建议**：
  1. 禁止 `getattr`/`hasattr`/`type`/`vars` 等反射类内建函数作为调用名（`BLOCKED_NAMES` 增补）；
  2. 遍历所有 `ast.Constant` 字符串，命中任一 `BLOCKED_DUNDERS` 子串即拒绝；
  3. 对 `ast.Call` 的任意参数做同样的字符串扫描；
  4. 子进程改用 `python -I -S` 并裁剪 `__builtins__`，不要仅依赖 AST 层；
  5. 补一条 `getattr((), "__class__")` 必须被拒的单测，防回归。
- **风险**：沙箱由多个工具/tests 依赖，加严后需回归既有合法数据处理脚本（尤其 pandas/numpy 用例）。

---

## HIGH

### H1. SQL 查询工具的租户隔离可被 SQL 文本本身绕过（跨租户数据读取）

- **文件位置**：`server/aios-resource/.../service/SqlQueryToolService.java:123-127`（`injectTenant`）
- **症状**：强制注入 `tenant_id = <当前租户>` 的逻辑，只要原始 SQL 文本任意位置含 "tenant_id" 字样就跳过注入。
- **证据**：
  ```java
  if (lower.contains("where")) {
      if (lower.contains("tenant_id")) {
          return sql;   // 原样放行，未追加当前租户条件
      }
  ```
- **影响**：被提示注入诱导的模型（或恶意用户）可构造 `SELECT ... FROM <白名单表> WHERE tenant_id > 0`，因文本含 `tenant_id` 直接执行，越过租户隔离读取他租户数据。白名单表校验仍在，但租户维度失效。
- **修复建议**：删除"含 tenant_id 即放行"的分支；无条件重写 WHERE，强制追加 `AND <alias>.tenant_id = <tid>`；若用户自带的 tenant_id 条件与之冲突应保留两者（结果为空）或以当前租户为准并覆盖。改用 SQL 解析器（JSqlParser）替代字符串启发式。
- **风险**：改动会影响所有依赖该工具 conversational SQL 查询的既有流程，需回归。

### H2. 文件下载接口缺属主/租户过滤（IDOR）

- **文件位置**：`server/aios-resource/.../controller/FileController.java:201-218`（`download`）
- **症状**：按主键 `selectById(id)` 直接下载，未带 `user_id`/`tenant_id` 约束。
- **证据**：`SysFile rec = fileMapper.selectById(id);` —— 对比同控制器 list 按 `getUserId` 过滤，唯独 download 裸查。上传时已存 tenantId/userId。
- **影响**：任何登录用户遍历自增 id 请求 `GET /api/v1/files/{id}` 即可下载其他用户/租户的附件，包含请假证明等敏感材料。
- **修复建议**：改为 `selectOne(new LambdaQueryWrapper<SysFile>().eq(id).eq(user_id, 当前用户).eq(tenant_id, 当前租户))`，无权限返回 404（不要 403，避免枚举）。
- **风险**：若下载链接被用于跨用户分享场景（邮件/审批通知直链），加过滤后这些链接会失效，需评估业务是否依赖直链。

### H3. 技能名拼进内联 `onclick`，`esc()` 不转义单引号（存储型 XSS）

- **文件位置**：`user-client/index.html:4666`（渲染），`esc()` 定义于 `:4111`
- **症状**：`esc()` 只替换 `& < > "`，不含单引号；技能名被拼进 `onclick="openSkill('...')"` 的单引号字符串上下文。
- **证据**：
  ```js
  const esc = s => String(s==null?'':s).replace(/[&<>"]/g, ...);  // 无 '
  '<div class="grid-item" onclick="openSkill(\''+esc(s.name||s.title||'技能')+'\')">'
  ```
  同文件 `:5894` 已有正确口径 `qArg=esc(q).replace(/'/g,"\\'")`，说明是遗漏而非有意。
- **影响**：管理员配置的技能名含 `'` 即可闭合字符串注入脚本，在其他登录用户会话中执行。同源还有附件 `url`（`:9546`）、权限码（`:6356`）、附件链接 href（`:9667`）等多处同型问题。
- **修复建议**：`esc()` 增加 `'` → `&#39;`；更彻底的做法是改用 `addEventListener` + `data-*` 传值，彻底杜绝内联 JS 拼接；URL 场景额外校验协议（拒绝 `javascript:`）。
- **风险**：`esc()` 是全局函数，加单引号转义会影响所有调用点，需回归name/title展示（一般无害）。

### H4. `web_fetch` 无内网/云元数据黑名单且自动跟随重定向（SSRF）

- **文件位置**：`agent/aios_ai/tools/web_search.py:135,166-181`
- **症状**：URL 校验仅判断以 `http(s)://` 开头；`AsyncClient(..., follow_redirects=True)`。
- **证据**：`if not u.startswith(("http://","https://")): raise`。
- **影响**：通过对话或 prompt 注入诱导模型调用该工具，可探测内网服务、读取云主机元数据端点（169.254.169.254）窃取 IAM 凭据；302 跳转可绕过初始地址校验。
- **修复建议**：解析 host，用 `ipaddress` 拒绝私有段/回环/链路本地/IPv6 本地；关闭自动跟随，自行受控跟随且每跳重新校验 host；限制端口白名单。
- **风险**：会拦截部分合法内网知识库抓取需求，需与业务确认白名单。

---

## MEDIUM

### M1. SQL 执行失败把 JDBC 内部异常原文外发给模型/用户
- **位置**：`SqlQueryToolService.java:75-77` → `ToolGatewayService.java:151-154`
- **证据**：`throw BizException.badRequest("SQL 执行失败：" + e.getMessage());`，外层 `Map.of("ok", false, "error", String.valueOf(e.getMessage()))`
- **影响**：SQLException 含真实 SQL、表/列名、驱动细节，泄露内部库结构。
- **建议**：对外固定文案，完整异常只进日志（对齐本项目 `errors.sanitize` 口径）。

### M2. 看板统计 N+1 查询
- **位置**：`server/aios-org/.../DashboardService.java:39-65`
- **证据**：`for (OrgInstitution it : insts) { statMapper.countActiveDepts(...); countActiveMembers(...); countKbOfInstitution(...); countLeaveByStatus(...); }`
- **影响**：每机构 4 次 SQL，机构数 N 时 4N 次，看板变慢、连接池承压。
- **建议**：一条 `GROUP BY institution_id` 聚合 SQL 或批量 IN 一次取回。

### M3. 种子用户明文口令写入 INFO 日志
- **位置**：`server/aios-boot/.../StartupCheckRunner.java:97-99`
- **证据**：`log.info("seed user '{}' password '{}' matches = {} ...", SEED_USERNAME, SEED_PASSWORD, matched, ...)`，`SEED_PASSWORD = "Admin@123"`
- **影响**：明文口令进入日志/日志采集系统，成为凭据泄露点。
- **建议**：移除日志中的 password 参数，只记录校验结果；避免硬编码明文口令。

### M4. 额度查询异常被吞且无日志
- **位置**：`server/aios-org/.../DashboardService.java:89-93`
- **证据**：`try { quota = quotaService.orgQuotaView(...); } catch (Exception e) { quota = null; }`
- **影响**：查询失败被静默转为 null，故障不可观测。
- **建议**：至少 `log.warn(...)`；区分"无数据"与"查询失败"。

### M5. 登录 redirect 参数未校验（开放重定向）
- **位置**：`web/apps/shell/src/views/LoginView.vue:75-80`
- **证据**：`const redirect = route.query.redirect` → `router.replace(redirect)` → catch 中 `window.location.href = redirect`
- **影响**：构造 `?redirect=//evil.com` 可将登录用户导向钓鱼站。
- **建议**：仅允许以单个 `/` 开头且不以 `//` 开头的站内相对路径，否则回落 `/home`。

### M6. 上传只校验扩展名、无大小上限
- **位置**：`user-client/index.html:7271-7294`（及 `:13656` OA 态）
- **证据**：`var ext=(file.name.split('.').pop()...); if(CHAT_ATTACH_EXTS.indexOf(ext)<0) return;` 直接 `API.fileUpload(file)`，无 `file.size` 判断。
- **影响**：超大文件耗尽前端内存/带宽并挤占存储。
- **建议**：前后端双端加 `MAX_FILE_SIZE` 校验与提示。

### M7. SSE 非 200 响应丢弃错误信封原因
- **位置**：`user-client/index.html:3954`
- **证据**：`const res = await fetch(..); if(!res.ok) throw new Error('SSE HTTP ' + res.status);`
- **影响**：限流/权限/额度耗尽等非 200 时用户看不到具体原因，与 `API.req`/`envelopeError` 文案口径不一致。
- **建议**：非 200 时读 `res.json()` 过 `envelopeError`/`sseError` 解析后再抛。

---

## LOW / 待复核

- **L1** `FileController.java:147-148` 分页 size 仅下限无上限（`Math.max(size,1)`），传超大 size 可拉海量数据。建议 clamp 到 200。
- **L2** `agent/aios_ai/errors.py:140-141,175-179` `internal_payload(trace_id=None)` 文案提"错误编号"但载荷无 `errorId`（本项目铁律 4 记载过的老 bug 残留）。`[待复核]` 触发面依赖 trace 头缺省。
- **L3** `agent/aios_ai/graph/nodes.py:769` 日志打印还原出的工具调用完整参数（可能含收件人/金额/正文），建议截断脱敏。`[待复核]`
- **L4** token 持久化在 localStorage（`user-client/index.html:4278`、`web/.../api/index.ts:37`、`stores/auth.ts:45`），任一 XSS 可长期盗号。建议 HttpOnly+SameSite Cookie。
- **L5** 部分路径参数未 `encodeURIComponent`（`user-client/index.html:3734,3739,3861,4025`），id 含特殊字符时路径被截断。当前多为数字主键，风险有限。
- **L6** 流式每帧全量 `textContent=` + 读 `scrollHeight`（`:7360`），长回答逐帧 O(n) 重排。建议节流合并 delta。

---

## Root Cause Hypothesis

三路审查呈现同一模式：项目历史上多次以"字符串包含/前缀判断"替代严格的解析与校验（SQL 租户注入、URL 校验、AST 属性校验、esc 转义），这类启发式在安全边界上系统性地可被构造输入绕过。置信度：高（关键项均已回源或实跑）。

## Proposed Remediation（优先级顺序）

1. **立即**：C1 沙箱 AST（RCE 面）、H1 租户绕过、H2 文件 IDOR —— 三项均为数据/系统级风险。
2. **本迭代**：H3 XSS、H4 SSRF、M5 开放重定向、M1 异常外发。
3. **常规排期**：M2/M3/M4/M6/M7 与 LOW 项。

## Risks & Considerations

- 本阶段严格只读，未修改任何源码；`specify init` 新增的 `.codebuddy/`、`.specify/` 与 WorkBuddy skill 包装是"启用工具"的产物，不是 bug 修复。
- H2 加属主过滤可能打破跨用户文件直链场景，需先确认业务依赖。
- C1/H1 加严需回归既有合法脚本与 conversational SQL 流程。

## Open Questions

- [NEEDS CLARIFICATION] 沙箱当前是否已接入模型生成脚本的执行路径？若是，C1 定为可被外部输入触发的 RCE；若否，定为潜在缺陷，仍需修复。
- [NEEDS CLARIFICATION] 文件下载链接是否用于跨用户分享（审批通知/邮件直链）？决定 H2 的修复方式。
