# AIOA 智能办公基座 · 项目全面评估报告

> 范围：`C:\Users\刘尖尖\WorkBuddy\aioa`
> 调研日期：2026-09-18
> 调研深度：4 路并行 Explore（git 历史 / Python agent / Java 后端+Bridge / 前端+文档+部署）+ 5 路汇总
> 文档定位：**评估报告**（不是实施计划）。用户的问题"识别项目、缺什么、优化、Python agent 对标框架"在本文档统一答复。

---

## 0. 一句话总评

**AIOA 不是"AI 办公骨架"了，它已经长成"业务域高度丰满的 AI 办公平台"——但骨架反而成了最薄弱的一环。**

- README 仍声称"M1 骨架已完成、M2/M3/M4 待启动"，但仓库实际已经跑到了 V53 迁移、10 个 Maven 模块、28 个用户端 + 管理端视图、20+ 份实施报告。
- **架构核心 aioa-bridge（工具注册表/桥接中间层）依然是 142K 占位、InternalToolController 直接 throw notImplemented**——这是 README 反复强调的"新系统接入 = 注册工具"叙事的命门，至今没接上。
- Python agent 服务是 1900 行的"FastAPI SSE 网关骨架"，**state graph、checkpoint、HITL 挂起、多 agent 协作全部未实现**，与 LangGraph / AutoGen / OpenAI Agents SDK 差距巨大。
- 后端业务域（aioa-resource / aioa-org / aioa-gitee）野蛮生长，把"基座不存业务数据"的红线几乎踩完。

**综合评分：6.5 / 10**。价值点是真的在的——但 README 与现实错位、bridge 旁路、Python agent 缺骨架，是阻碍"agent 协同办公 + 接入其他业务系统"目标的三座大山。

---

## 1. 项目识别与定位

### 1.1 项目是什么

按 README 与实现现状合并陈述：

| 维度 | 内容 |
|---|---|
| **产品定位** | Agent-era Office Automation：公司内部 AI OA 基座，各业务系统（票务/调度/...)统一接入后自动获得 AI agent 能力 |
| **核心叙事** | "前端 + 后端 + Agent"三端基座；新业务系统接入 = 注册工具，不写 AI 代码 |
| **技术栈** | Vue 3.5 + wujie 1.0.22 + Element Plus 2.9 + Pinia + TS 5.6；Spring Boot 3.3 + JDK 21 + MyBatis-Plus 3.5 + Spring Security + springdoc；FastAPI 0.110 + Pydantic 2 + httpx 0.27 |
| **数据** | MySQL 8（远程 192.168.31.129）+ Redis 7（远程）+ MinIO；53 个 Flyway 迁移 |
| **LLM 网关** | DeepSeek / 通义千问 / vLLM / Ollama / echo 共 5 个 provider，可运行时热加载 |
| **部署** | docker-compose 一键起（minio + server + agent + web + nginx），远程库直连；**无 K8s** |
| **协作** | 单兵 AIOA Dev 97% 提交、无 PR 流程、main 单分支、commit 规范三类混用 |

### 1.2 当前阶段判定

**README 与现实严重错位**——仓库实际处于"已完成 V53 的成熟业务平台"，不是 M1 骨架。

| 维度 | README 声称 | 实际状态 |
|---|---|---|
| 里程碑 | M1 已完成、M2 待启动 | 已完成 V53：M1(骨架)→ M2(工具网关/模型)→ M3(RBAC/HITL)→ M4(RAG)→ 一期交付 35 FR → V18-V22 权限迭代 → V36-V44 组织改造 → V45-V47 docs/28 收口 → V48 Gitee → V48-V52 消息中心/菜单合并 → V53 repo URL 规范化 |
| 后端模块 | 7 个 | **10 个**（多了 aioa-resource / aioa-org / aioa-gitee） |
| Bridge | "M2 完整" | **仍是 142K 骨架**，InternalToolController 仍 throw notImplemented |

---

## 2. 各维度成熟度评分

| 维度 | 评分 | 关键证据 |
|---|---|---|
| **后端业务完整度** | **8.0 / 10** | 53 个迁移、320 个 .java、Spring Security 双通道（JWT+Service JWT+JTI 吊销）、RBAC+实时授权（V36）、SHA-256 哈希链审计（V25 V2）、Gitee OAuth+Webhook 完整闭环 |
| **前端实现** | **7.0 / 10** | pnpm workspace 三应用；微前端 wujie；AI 助手 SSE 流式 OK；缺 tool call / citation UI 气泡、缺 i18n 与暗色、无前端监控 |
| **子应用接入** | **6.0 / 10** | @aioa/sdk 设计干净，但 `getToken()` 仍返回 null（子应用无法独立调基座 API）；postMessage origin 用 `*` 无白名单 |
| **Agent（Python）** | **3.5 / 10** | 1900 行 FastAPI 骨架；单 agent while 循环工具调用；state / checkpoint / HITL / 多 agent / 真 streaming / OpenTelemetry 全部缺失 |
| **Bridge 中间层** | **2.0 / 10** | 表结构 4 张齐了，Controller 直接 501；tool_permission / requires_approval 表里两列未被任何 service 读取 |
| **文档完整度** | **6.5 / 10** | 30+ 份实施报告丰富；缺 ER 图、ADR、独立的"模型网关规范"文档、监控告警 Runbook |
| **部署能力** | **6.0 / 10** | Compose 一键可用、nginx SSE 关键配置就位；无 K8s、ops profile 残缺（prometheus.yml 引用不存在）、缺 TLS 终止 |
| **整体** | **6.5 / 10** | 后端业务丰满、前端可用、Agent 与 Bridge 是明显短板 |

---

## 3. Python Agent 实现评估（用户重点）

### 3.1 体量与组织

- 代码量约 **1902 行**（含测试），全部在 `agent/app/`
- 组织：`main.py` + `core/`（runtime / agent_runtime / echo_runtime / intent_router / worker_intake / guards / events / answer_shape）+ `model_gateway/`（注册表 + 5 provider + mock_llm）+ `tools/`（sandbox + gateway_client 桩）
- 依赖极简：fastapi / uvicorn / pydantic / httpx / pytest；**未引入 LangGraph / LangChain / AutoGen / CrewAI / OpenAI Agents SDK / Anthropic Agent SDK / MCP SDK / OpenTelemetry / pydantic-settings**

### 3.2 能力清单

| 能力 | 状态 | 关键证据 |
|---|---|---|
| 单 agent 流式推理 | ✅ | `agent_runtime.run` + SSE；事件契约清晰（run.started / tool.call / tool.result / message.delta / message.completed / run.completed） |
| OpenAI 兼容工具调用循环 | ✅ | MAX_TOOL_ROUNDS=4；usage 计量；专家配置注入；KB citation 回填 |
| 数字员工意图识别 | ✅ | worker_intake 已挂 /internal/v1/worker-intent |
| 多 provider 模型网关 | ✅ | 5 个 provider；resolve() 三级降级；apply_overrides 热加载 |
| 错误码体系 | ✅ | TEXT_TOO_LONG / WALL_TIME_EXCEEDED / MODEL_UPSTREAM_ERROR 等 7 个 SSE 错误事件 |
| 单元测试 | ✅ | 5 个 pytest / 600 行；mock 充分；缺 e2e / LLM 集成 |
| **真正 LLM streaming** | ❌ | `_post_non_stream` 走 non-streaming HTTP，本地切片 delta；首字延迟 = 完整生成时间 |
| **state / checkpoint / 持久化** | ❌ | PG_DSN 配置存在但零连接；agent_run_step 表已建但无 service 写入 |
| **HITL 挂起 / 恢复** | ❌ | tool_definition.requires_approval 列在表里，Python 从不查；不发 approval.required |
| **主 agent + 子 agent 编排** | ❌ | 无 dispatch / subagent / child_agent 概念 |
| **本地工具抽象（@tool）** | ❌ | 无 BaseTool / @tool / StructuredTool |
| **MCP 客户端 / 服务端** | ❌ | 无 mcp SDK 依赖 |
| **OpenTelemetry / LangSmith** | ❌ | 仅 trace_id 写入 logger |
| **Anthropic 原生 driver** | ❌ | 只有 echo + openai_compatible 两个 driver |
| **fallback 链 / 重试 / 限流** | ❌ | UpstreamError 仅错误事件，不重试 |
| **并行工具调用** | ❌ | for call in calls 是串行 |
| **prompt caching / structured output** | ❌ | 未实现 |

### 3.3 与 7 个主流框架对比

| 能力 | LangGraph | AutoGen | CrewAI | OpenAI Agents SDK | Anthropic Agent SDK | MCP | **AIOA** |
|---|---|---|---|---|---|---|---|
| 状态机 / Graph | ✅ | ✅ | ✅ | ✅ | ✅ | — | ❌ while 循环 |
| Checkpoint | ✅ | 手写 | 手写 | ✅ | ✅ | — | ❌ |
| HITL / Interrupt | ✅ | ✅ | ✅ | ✅ | ✅ | — | ❌ |
| 多 agent | ✅ | ✅ | ✅ | ✅ handoffs | ✅ subagents | — | ❌ |
| 工具协议 | @tool | Function | BaseTool | @function_tool | @tool | JSON-RPC | ⚠ 自研 HTTP |
| 工具发现 | 装饰器 | 注册 | 列表 | 函数列表 | 列表 | tools/list | ⚠ Java GET |
| 流式 | astream_events | ❌ | ❌ | Runner.stream | ✅ | Streamable HTTP | ⚠ 本地切片 |
| Tracing | OTEL/LangSmith | Console | OTEL | OpenAI Traces | ✅ | OTEL | ⚠ logger |
| 重试 / 降级 | 节点 retry | ❌ | ❌ | ✅ | ✅ | — | ❌ |
| token 用量 | 自动 | ❌ | ❌ | ✅ | ✅ | — | ✅ |
| prompt caching | ❌ | ❌ | ❌ | ✅ | ✅ | — | ❌ |
| **总计 / 11** | 7/11 | 4/11 | 4/11 | 8/11 | 9/11 | 4/7 | **1/11** |

### 3.4 关键缺陷（与架构文档承诺对照）

1. **`agent_runtime.py` 是 while 循环，不是 StateGraph**——架构 §5 承诺的 perceive → plan → dispatch → execute → reflect 五个节点全部没落地
2. **没有 checkpoint**——进程重启 run 状态全丢；M3 HITL 的"WAITING_APPROVAL → APPROVE → RUNNING"状态机无法做
3. **不是真 streaming**——`_post_non_stream` 用 non-streaming HTTP + 本地切片，首字延迟 = 完整生成时间，违反架构"首字 ≤ 2s"门禁
4. **三个孤儿模块**：`intent_router.route()` / `mock_llm.summarize_tool_result` / `sandbox.run_script` 在代码库中 0 caller，已成死代码
5. **driver 抽象不够**：想换 Anthropic 原生协议必须改 agent_runtime.py；UpstreamError 是 OpenAI 协议错误形态
6. **provider 注册表线程不安全**：FastAPI 异步并发下 `apply_overrides` 改全局 dict 有竞态

### 3.5 Python agent 优化路线（按 ROI 排序）

**P0（2 周）**：
- 引入 LangGraph 0.2.x（README 已 pin），改写 agent_runtime 为 StateGraph：perceive → plan → dispatch → execute → reflect；edge = 条件路由；interrupt_before 用于 HITL
- 接入 SQLAlchemy 异步 + asyncpg，写 agent_run / agent_run_step / hitl_approval 三表
- checkpointer 用 MemorySaver（M2）+ PostgresSaver（M3）；thread_id = conversation_id
- 在 graph 加 `wait_approval` 节点；按 risk_level 自动执行或发 approval.required 事件；Java 侧新增 /internal/v1/runs/{id}/approve|reject 回调恢复 graph
- 用 args_hash 防篡改（架构 §5 已规划）

**P1（1-2 月）**：
- `_post_non_stream` → `_post_stream`，解析 SSE `data: {...}` 增量行；首字延迟降至「首 token 时间」
- 抽象 `BaseAdapter`：`async def stream(messages, tools, temperature) -> AsyncIterator[Delta]`；新增 AnthropicAdapter（Claude 原生 + prompt caching）；GeminiAdapter（可选）
- 加 OpenTelemetry：`opentelemetry-instrumentation-fastapi` + 自定义 span，run_id / conversation_id / model / token_usage 入 attribute
- 把 intent_router.route() 接入 plan 节点；sandbox / mock_llm 接入相应节点

**P2（季度）**：
- 并行工具调用：单轮多个 tool_calls 并发 invoke
- 本地工具抽象：BaseTool / @tool 装饰器（参考 LangChain）
- MCP client 占位：`MCPClient(transport=stdio)`，未来 MCP server 注册工具
- 结构化输出：with_structured_output 风格（Pydantic schema → JSON 强制 → 校验）
- tenacity 重试：UpstreamError + 网络错误指数退避，最多 3 次

---

## 4. Java 后端 + Bridge 中间层评估（用户重点）

### 4.1 Maven 模块结构（10 个）

```
aioa-common        ← ApiResponse / PageResult / BizException / TraceId
aioa-security      ← JwtAuthenticationFilter / ServiceTokenFilter / PermissionCatalog
aioa-admin         ← SysUser/Role/Permission/AppRegistry + AuthController
aioa-bridge        ← ⚠ ToolDefinition/Permission/Log 4 张表 + 501 占位 Controller
aioa-tool-sdk      ← ⚠ 仅 PageContext 1 个文件（无 @AioaTool 注解）
aioa-chat          ← Conversation/Run/WorkerIntake/Stats + RunService(SSE)
aioa-resource      ← ToolGateway(实际网关)/Approval/Billing/KB/Notification/ContentReview 等业务域
aioa-org           ← Onboarding/AuditRecorder(哈希链)/ApprovalFlow/PermissionGrant/Org
aioa-gitee         ← OAuth/Webhook/SyncScheduler/3 个 TaskHandler/Crypto
aioa-boot          ← 启动 + OpenApiConfig + 53 个 Flyway 迁移
```

调用关系单向无循环：`boot → admin/chat/resource/org/gitee/bridge/tool-sdk → security → common`；`chat → org`，`gitee → org`。

### 4.2 aioa-bridge 现状

- 表结构齐全：tool_system / tool_definition（含 `uk(tool_code, version)`）/ tool_permission（含 `uk(tool_code, role_code)` effect ALLOW/DENY）/ tool_invocation_log
- Entity / Mapper 占位（MyBatis-Plus BaseMapper，9 行无自定义 SQL）
- **InternalToolController 直接 throw notImplemented("tool invoke 将在 M2 实现")**
- 实际工具网关**不在 bridge 里**，在 `aioa-resource` 的 `ToolGatewayService`（5 个内置工具静态白名单 + ExternalToolHandler SPI）
- 鉴权层（SecurityConfig 路由 `/internal/**` → ServiceTokenFilter）能生效，但**模块边界已乱**——bridge 模块的 Controller 要借 chat 模块的 ServiceTokenProvider

### 4.3 工具调用关键缺陷

1. **ToolGatewayService 不查 tool_permission 表**——只按 `requiredRoles` 写死角色判定，新增工具易漏配 → 越权
2. **requires_approval 列在表里无 service 读取**——HITL 缺失
3. **idempotency_required 列在表里无 service 读取**——幂等缺失，重放风险
4. **aioa-tool-sdk 仍 1 个文件 PageContext**——子应用无 SDK 注解契约
5. **MCP Server 缺失**——无法被 Claude Desktop / Cursor 等 MCP 客户端直接消费

### 4.4 已落地能力

| 能力 | 状态 | 证据 |
|---|---|---|
| 多租户隔离 | ✅ | 几乎每张表带 tenant_id；SqlQueryToolService 强制注入 WHERE tenant_id |
| RBAC + 实时授权 | ✅ | 6 角色 × 12 权限码；V36 审批通过即生效无需重登 |
| SHA-256 哈希链审计 | ✅ | V25 V2 算法（微秒截断 + 自哈希可复算） |
| 配额 / 账单 / 订单 | ✅ | QuotaService / BillingService / OrderService |
| 通知多通道 | ✅ | 站内/邮件/短信/推送/HTTP 网关 5 通道（aioa-resource/notify/） |
| 知识库 RAG | ✅ | KbService + EmbeddingProvider + KnowledgeStore（MySQL/Elastic 双实现） |
| Gitee OAuth+Webhook | ✅ | 一次性 state + redirect_uri 严格匹配 + X-Gitee-Token + event_key 幂等 + 抢占式 outbox + 5 次退避 |
| Approval Flow | ✅ | 5 类节点模式 + 4 策略 ApproverResolver；V45 加权重 / 阈值 |

### 4.5 安全风险点（按严重度）

| 等级 | 风险 | 证据 |
|---|---|---|
| **高** | 默认密钥硬编码（jwt.secret / service-jwt.secret / gitee.token-enc-key），prod 无启动校验 | application.yml L57-L92 |
| **高** | HS256 单密钥，泄露即伪造任意用户身份；M2 计划换 RS256 但未换 | JwtTokenProvider L48 |
| **高** | /api/v1/tools/invoke 不看 tool_permission 表，越权风险 | ToolGatewayService L127-L131 |
| **高** | sql_query 工具 SQL 白名单是字符串正则，对 /*!...*/ / 0x... / unicode 同义字符未覆盖 | SqlQueryToolService L82-L115 |
| **中** | SSE 长连接 × Tomcat 线程，WebMvc.async.request-timeout=0 + SseEmitter(0)，200 并发即打爆 | application.yml L40-L42 |
| **中** | 跨模块 JdbcTemplate 原生 SQL 无切面统一 tenant_id 过滤 | AuthService L195-L198 |
| **中** | csrf.disable() 仅靠 JWT + CORS；同源 XSS 失效即携带 Bearer | SecurityConfig L68 |
| **中** | Redis 已依赖但 health.redis.enabled=false——RedisTemplate 注入却不用 | application.yml L20-L24 |
| **低** | agent_run_step 表已建但无 service 写入，半年内可能未清理 | V1 |

### 4.6 性能瓶颈

- SSE 长连接 × Tomcat 线程：每个 run 占 1 servlet 线程 + 1 WebClient 订阅线程 + 心跳调度
- 审计 lastHash：亿级行需分区/归档
- PermResolver / RoleResolver 每请求查 DB：QPS 1000 时 1000 次 SELECT；可加 caffeine
- /api/v1/admin/users / /personnel 全表拉到内存再分页：租户百万用户 OOM

### 4.7 后端优化路线（按 ROI 排序）

**P0（2 周）**：
- aioa-bridge 网关实现：InternalToolController#invoke 按 tool_definition.endpoint/httpMethod/inputSchema 调下游；调用前查 tool_permission 表按 effect ALLOW/DENY 决策；命中 requires_approval 走 approval_order
- 接入 idempotency_required：按 (tenant_id, tool_code, args_hash, idempotency_key) 缓存到 tool_invocation_log
- 全局限流：Bucket4j + Redis 按 userId/toolCode/endpoint 维度令牌桶；解析 tool_definition.rate_limit
- 密钥启动校验：JwtProperties / ServiceJwtProperties / GiteeProperties 检到默认 dev 串且 profile=prod 时启动失败
- Service JWT 换 RS256：Python 端持有 public key 验签
- /api/v1/admin/users / /personnel 改 LIMIT SQL 直查

**P1（季度）**：
- spring-ai-mcp-server + @McpTool / @McpResource，把 ToolGatewayService.listTools 包装为 MCP tools/list + tools/call → Claude Desktop / Cursor 可直连
- OAuth2/OIDC 服务端：spring-authorization-server；对接企业 AD/LDAP/钉钉/飞书 IdP
- Resilience4j：每个 tool_system.baseUrl 配 @CircuitBreaker + @Retry + @TimeLimiter
- 工具版本灰度 / 热加载：grayscale_pct + enabled_users + Redis pub/sub 失效
- SSE 改 WebFlux Flux<ServerSentEvent>，去掉 Servlet 线程占用

**P2（半年）**：
- aioa-tool-sdk 注解契约：@AioaTool / @AioaToolParam；spring-boot-starter 自动注册
- springdoc 6 个 group，6 个 Swagger UI 子页面
- ApiResponse 透出 traceId：所有响应自动加 traceId 字段
- DB 切面强租户隔离：@TenantFilter + MyBatis interceptor 自动拼 tenant_id
- agent_run_step 写入：把 message.completed.citations/tool_calls 持久化，支撑步骤回放
- 审计外部公证：每 N 行提交到国家区块链 / Git commit / 对象存储 WORM

---

## 5. 前端 + 子应用接入评估

### 5.1 已有能力

- pnpm workspace 完整（shell + demo-ticket + demo-dispatch + @aioa/sdk）
- wujie 微前端 1.0.22；iframe 逃生舱
- AI 助手面板 SSE 流式 + 上下文感知 + 异常态处理 + AbortController 停止
- 路由 / 状态 / 权限三层守卫（菜单 → meta → 后端）

### 5.2 关键缺口

| 优先级 | 缺口 | 影响 |
|---|---|---|
| **P0** | @aioa/sdk.getToken() 永远 null | 子应用无法独立调基座 API，必须经主应用转发——限制子应用能力 |
| **P0** | postMessage origin 用 `*` 无白名单 | 任意 iframe 可伪造 AIOA_SET_CONTEXT 注入恶意上下文 |
| **P0** | 缺主应用反向动作派发统一 API（仅内部 sendAction） | 业务代码"让子应用跳页"无统一 API |
| **P1** | MessageList.vue 只渲染文本，无 tool_call / citation / 思考链 UI 气泡 | 用户感知不到 AI 干了什么，可信度难建立 |
| **P1** | 缺 i18n（写死 zhCn）、缺暗色模式 | 多语言客户与体验天花板 |
| **P1** | 无前端监控 / 错误上报 / 性能埋点 | 线上问题排查靠"用户截图+日志" |
| **P2** | demo-ticket 数据是内存静态 5 条，无真实 CRUD | 演示"AI 帮我新建工单"空响 |
| **P2** | demo-dispatch 是反面教材（无 SDK / 无 router / iframe 演示） | 不应作为最佳实践模板 |

---

## 6. 文档 / 部署评估

### 6.1 文档完整度

- 已覆盖：01-架构设计（总纲）/ 02-子应用接入规范 / 03-工具注册规范 / 04-接口契约（openapi.yaml + internal-agent.yaml）/ 05-部署手册 / 06-交接包借鉴说明 / 07-项目结构 / 08-30 实施报告
- **缺失**：ER 图（26 表靠 migrations + Java entity 推理）、5 张关键时序图（登录/提问/HITL/RAG/Gitee OAuth）、ADR（架构决策记录）、独立模型网关规范、K8s 清单、监控告警 Runbook、前端开发规范

### 6.2 部署完整度

- 已覆盖：docker-compose 一键、nginx SSE 关键配置、MinIO 持久卷、profile=model 附加 vLLM/Ollama
- **缺失**：K8s Deployment/Service/ConfigMap/Secret/Ingress 清单、HPA / PDB / NetworkPolicy、Helm chart / Kustomize、TLS 终止、限流 zone、prometheus.yml（profile=ops 引用不存在的文件）、alert rules、Grafana dashboard、AES 加密密钥 / SMTP / Webhook 签名密钥未进 .env.example

---

## 7. 缺失模块清单（按优先级）

### P0 — 阻塞"接入其他业务系统"目标

| 模块 | 当前状态 | 补齐方案 |
|---|---|---|
| **通用工作流引擎** | ApprovalService 是硬编码流程；ApprovalFlowConfigView 仅支持"知会对象"，无条件分支/加签/会签/子流程/版本对比 | 引入 Camunda / Flowable；或自研 `WorkflowDefinition/Node/Instance/Task` + JSON DSL + 通用 UI 模板 |
| **aioa-bridge 真实实现** | InternalToolController 501；ToolGatewayService 不查 tool_permission | 见 §4.7 P0 |
| **@aioa/sdk.getToken 真实化** + 主应用 API 代理 | SDK 注释写"M1 恒返回 null" | 实现 shell 侧 `aioa.proxyRequest({url, method, body})`；SDK getToken 经 MessageChannel 异步取短期票据 |
| **postMessage origin 白名单 + appCode 签名** | 全 `*` | 立即加 origin 白名单 + 短期 nonce + appCode 签名校验 |

### P1 — 差异化竞争力

| 模块 | 当前状态 | 补齐方案 |
|---|---|---|
| **tool call / citation / 思考链 UI 气泡** | MessageList 只渲染文本 | 加 `<tool_call>` 折叠块（参考 Cursor/ChatGPT）+ citation chip + 思考链路 |
| **通知多通道 Sender SPI 端到端** | aioa-resource/notify 子目录雏形 | 补 EmailSender / SmsSender / DingTalkSender / WebhookSender + Channel 配置 + 失败重试 + 投递记录 |
| **通用任务调度面板** | 只有 GiteeSyncScheduler / WorkerScheduleService | XXL-Job / Quartz + 任务 CRUD + 触发记录 + 失败告警 |
| **ES 全文检索** | KB 用 MySQL `LIKE`；vector 模式预留 | 引入 ES 或 Meilisearch，与 pgvector / mysql 向量形成"全文 + 语义"双路召回 |
| **K8s 部署清单** | 无 yaml | `k8s/base/` + `k8s/overlays/{dev,staging,prod}/`（Kustomize）；HPA / PDB / NetworkPolicy |
| **ER 图 + 关键时序图** | 缺 | mermaid 输出 26 表 ER + 5 张时序图 |
| **ADR 起步** | 决策散在各期增量 PRD | `docs/adr/0001-*.md` 沉淀 10+ 关键决策 |
| **独立"模型网关规范"** | 散落在 README + application.yml 注释 + __init__.py | 与"工具注册规范"同级的独立文档 |

### P2 — 未来扩展

| 模块 | 当前状态 | 补齐方案 |
|---|---|---|
| **插件市场 / 应用商店** | BizSystemView 列出已注册业务系统；无版本/评分/安装/卸载 | app_market 层（分类/版本/截图/依赖/灰度发布） + "申请接入 → 审核 → 一键安装" |
| **前端可观测** | 无 Sentry/自研 RUM | 引入 Sentry 或自研埋点（错误 + 性能 + 接口慢查询） |
| **国际化 / 暗色** | 写死中文 | vue-i18n + Element Plus dark 主题或 CSS vars |
| **demo-ticket 真实化** | 内存静态数据 | 真实 CRUD + 工具注册示例 + "AI 帮我新建工单"端到端 |
| **MCP Server** | 无 | spring-ai-mcp-server + @McpTool / @McpResource，包装 ToolGatewayService.listTools |
| **OAuth2/OIDC 服务端** | 自签 HS256 JWT；Gitee 仅为 client | spring-authorization-server 对接 AD/LDAP/钉钉/飞书 |

### P3 — 长期生态对齐

- CI/CD：GitHub Actions 全链路（web typecheck/build / server mvn verify / agent pytest / docker buildx push）
- 前端单元测试：vitest 套件（assistant store / SDK bridge）
- PDF/Office KB 解析深度：Apache Tika / Unstructured / Marker
- Open API（/openapi/v1）真实化与 API Key 管理
- 多租户跨区容灾 + 备份恢复演练脚本
- 数字员工/Agent 间 A2A 协同协议
- 向量库替代评估（pgvector vs Milvus / Qdrant）

---

## 8. 全局优化建议（按 ROI 排序）

### 立刻做（1-2 周）

1. **bridge 网关实现 + tool_permission/requires_approval 接入**——叙事的命门
2. **@aioa/sdk.getToken 真实化 + 主应用 API 代理**——子应用独立业务请求能力
3. **postMessage origin 白名单 + appCode 签名**——M1 阶段就该有的安全门
4. **tool call / citation UI 气泡**——提升助手可信度
5. **K8s 基础清单**（Kustomize + Ingress + ConfigMap + Secret）
6. **ops profile 修复**：补 prometheus.yml + alert rules + Grafana dashboard
7. **前端错误监控 + 性能埋点**
8. **立即清理 .env.gitee-real + .aioa_login.json**（已泄漏的凭据）
9. **.gitignore 补丁**：`scripts/_*` / `*.probe*.txt` / `e2e_*_exit.txt` / `.env.*real` / `.env.*local` / `.aioa_login.json` / `.workbuddy/artifacts/`
10. **README 重写 §2 仓库结构、§5 里程碑、§1 定位**——与现实对齐

### 短期（1-2 月）

11. LangGraph 集成 + checkpoint + HITL 挂起恢复
12. 通用工作流引擎（workflow_definition/node/instance/task + JSON DSL）
13. Bucket4j 全局限流 + Resilience4j 熔断
14. 通知多通道 Sender SPI
15. ES / Meilisearch 全文检索
16. 密钥启动校验 + Service JWT 换 RS256
17. 改成真正的 LLM streaming（_post_stream）
18. 抽象 ModelAdapter，补 Anthropic 原生 driver

### 中期（季度）

19. 通用任务调度面板（XXL-Job）
20. MCP Server 暴露（spring-ai-mcp-server）
21. OAuth2/OIDC 服务端
22. OpenTelemetry 全链路
23. 工具版本灰度 / 热加载
24. SSE 改 WebFlux（去 Servlet 线程）
25. SSE 状态持久化（agent_run_step 写入）
26. aioa-tool-sdk 注解契约
27. springdoc 6 group 分组
28. DB 切面强租户隔离
29. 插件市场 / 应用商店
30. demo-ticket 真实化

### 长期（半年）

31. CI/CD 全链路
32. 前端 vitest 套件
33. PDF / Office KB 解析深度
34. Open API（/openapi/v1）+ API Key 管理
35. 多租户跨区容灾 + 备份恢复
36. A2A 协议（agent 间协同）
37. 向量库替代评估

---

## 9. 给用户的三步走路线图

**第 1 步（2 周，立刻止血 + 看清方向）**：
- 重写 README §1-2-5 与现实对齐
- .gitignore 补丁 + 清理 .env.gitee-real 等已泄漏凭据 + scripts/ 下划线脚本归档
- 实现 bridge 网关 + 接入 tool_permission + requires_approval（最大叙事缺口）

**第 2 步（4-6 周，骨架补齐）**：
- Python agent 引入 LangGraph + checkpointer + HITL 挂起 + 真 streaming
- Java 端 Bucket4j 限流 + Resilience4j 熔断 + 密钥启动校验
- @aioa/sdk.getToken 真实化 + postMessage origin 白名单
- tool call / citation UI 气泡
- K8s 基础清单（Kustomize + Ingress）

**第 3 步（季度，差异化竞争力）**：
- 通用工作流引擎（WorkflowDefinition + JSON DSL + 流程编辑器）
- 通知多通道 Sender SPI 端到端
- MCP Server 暴露（spring-ai-mcp-server）
- OAuth2/OIDC 服务端
- ES 全文检索
- ER 图 + 5 张时序图 + ADR 起步
- 独立"模型网关规范"文档

完成第 3 步后，AIOA 才能真正对外宣称"agent 协同办公 + 接入其他业务系统的 AI OA 基座"。

---

## 10. 用户确认的 P0 改造线 + 推荐实施顺序

用户已确认四条 P0 改造线全部要启动。按依赖与 ROI 排序：

### Phase A — 基建止血（Day 1-5，可单人并行）

1. .gitignore 补丁：`scripts/_*` / `*.probe*.txt` / `e2e_*_exit.txt` / `.env.*real` / `.env.*local` / `.aioa_login.json` / `.workbuddy/artifacts/`
2. 清理已泄漏凭据：`.env.gitee-real` / `.aioa_login.json`（从 disk 删除）+ 检查 git 历史是否曾 tracked `.env.gitee-real`，如有则 `git filter-branch` 或 BFG
3. scripts/ 下划线脚本归档到 `.workbuddy/diagnostics/`，committed 脚本（SMOKE_v48.py / e2e_*.py 等）保留
4. README §1-2-5 重写，与 V53 现实对齐（声明 aioa-bridge 真实状态、添加 aioa-resource/org/gitee 三个模块）
5. 根目录临时文件清理：bind_probe.txt / probe*.txt / e2e_v50_*.txt → 归档或删除
6. 暂时禁用 profile=ops 或补 deploy/ops/prometheus.yml（避免误导用户）

### Phase B — SDK 安全加固（Week 1-2，可与 A/C 并行）

1. **@aioa/sdk.getToken 真实化**：shell 暴露 `aioa.proxyRequest({url, method, body})`；SDK getToken 经 MessageChannel 异步取短期票据（access token 5 分钟过期 + refresh 机制）
2. **postMessage origin 白名单**：shell 维护 `appCode → allowedOrigins` 注册表；M3 之前先用宽松白名单（`localhost:5174-5175`），上线前严格化
3. **appCode 签名**：bridge 在子应用握手时下发短期 HMAC 签名，子应用每次上行消息附上，防伪造
4. **tool call / citation UI 气泡**：MessageList.vue 加 `<​tool_call>` 折叠块（参考 Cursor）+ citation chip 点击定位到 KB 文档；assistant store 增加 tool_calls 字段渲染
5. **demo-ticket 真实化**（顺带）：内存静态数据改为真实 CRUD（演示"AI 帮我新建工单"端到端）

### Phase C — bridge 网关真实化（Week 2-3，紧接 B）

1. **aioa-bridge 网关实现**：InternalToolController#invoke 按 tool_definition.endpoint/httpMethod/inputSchema 调下游；保留 ToolGatewayService.listTools 作为 OpenAI function-calling 兼容入口
2. **接入 tool_permission**：ToolGatewayService#invoke 调用前查 tool_permission 表按 (tool_code, role_code) 决策 effect ALLOW/DENY
3. **接入 requires_approval**：命中走 approval_order（沿用 ApprovalService），发 approval.required SSE 事件
4. **接入 idempotency_required**：按 (tenant_id, tool_code, args_hash, idempotency_key) 缓存到 tool_invocation_log
5. **aioa-tool-sdk 注解契约**：定义 @AioaTool(name, description, scopes, riskLevel, requiresApproval) + @AioaToolParam；子应用加 aioa-spring-boot-starter 自动注册
6. **Bucket4j 全局限流**：Redis 令牌桶按 userId/toolCode/endpoint 维度；tool_definition.rate_limit 解析为配置
7. **密钥启动校验**：JwtProperties / ServiceJwtProperties / GiteeProperties 检测到默认 dev 串且 profile=prod 时启动失败

### Phase D — Python LangGraph 重构（Week 3-6，可与 B/C 并行）

1. **引入 LangGraph 0.2.x**（README 已 pin），改写 agent_runtime.run 为 StateGraph：perceive → plan → dispatch → execute → reflect；edge = 条件路由
2. **接入 SQLAlchemy 异步 + asyncpg**，写 agent_run / agent_run_step / hitl_approval 三表（agent_run_step 表已存在 V1，启用写入）
3. **checkpointer**：MemorySaver（M2 验证）+ PostgresSaver（M3 上生产）；thread_id = conversation_id
4. **HITL 挂起 / 恢复**：graph 加 wait_approval 节点；按 risk_level 自动执行或发 approval.required；Java 侧新增 /internal/v1/runs/{id}/approve|reject 回调恢复 graph
5. **真 streaming**：_post_non_stream → _post_stream，解析 SSE `data: {...}` 增量行；首字延迟从「完整生成时间」降至「首 token 时间」
6. **ModelAdapter 抽象**：BaseAdapter.stream(messages, tools, temperature) → AsyncIterator[Delta]；新增 AnthropicAdapter（Claude 原生 + prompt caching）
7. **把孤儿模块接入**：intent_router.route() 接入 plan 节点；sandbox / mock_llm 接入相应节点
8. **OpenTelemetry**：opentelemetry-instrumentation-fastapi + 自定义 span，run_id / conversation_id / model / token_usage 入 attribute；导出 OTLP 到 Jaeger / Tempo
9. **Service JWT 换 RS256**（Python 端持有 public key 验签，不再共享对称密钥）

### 关键依赖图

```
A ─┬─→ B ─┬─→ C ─→ (Java 端进入生产可用态)
   │      │
   │      └─→ D ─→ (Python 端进入生产可用态)
   │
   └─→ (并行进行)

后续 P1（通知多通道 / 通用工作流引擎 / K8s / ES / MCP Server / OAuth2）视 Phase A-D 完成后启动
```

### 验证方式（Phase A-D 完成后）

1. **bridge 真实化验收**：用 scripts/SMOKE_v48.py 跑通 tool 注册 → permission 校验 → invoke → 审批挂起 → 恢复 全链路
2. **LangGraph 验收**：用 agent/tests/test_agent_runtime.py + 新增 test_graph_checkpoint.py + test_hitl_resume.py 跑通 checkpoint 持久化 + HITL 中断恢复
3. **SDK 安全验收**：用 scripts/_diag_real_gitee_*.py（已归档）跑通"跨子应用代理调用基座 API + 篡改 appCode 被拒绝"
4. **整体 e2e**：scripts/_run_all_regression.sh（已归档）覆盖 admin / org / resource / chat / gitee / agent 六域回归

---

## 11. 一句话结论（回答用户问题）

> **AIOA 是个"骨架没长大、业务旁路野蛮生长、Python agent 是 while 循环"的 AI 办公平台。**

- **项目识别**：Vue3 + wujie + Spring Boot 3.3 + FastAPI + MyBatis-Plus 的 AI OA 基座，已完成 V53 迁移、10 模块、20+ 实施报告，但 README 严重过时
- **缺失模块**：通用工作流引擎、aioa-bridge 真实网关、@aioa/sdk.getToken、K8s、ES、MCP Server、通知多通道、OAuth2、CI/CD、ER 图 / ADR / 时序图、国际化、暗色、前端监控
- **优化方向**：①补 bridge 骨架②Python 引入 LangGraph ③SDK token + origin 安全 ④tool call UI ⑤K8s 部署⑥ops profile 修复⑦.gitignore 补丁 + README 重写
- **Python agent 实现度**：**3.5/10**——单 agent while 循环工具调用完善；state graph / checkpoint / HITL / 多 agent / 真 streaming / OpenTelemetry / Anthropic driver / 并行调用 / prompt caching 全部缺失；与 LangGraph 11 项核心能力仅 1/11
- **结构标准度**：与 LangGraph / OpenAI Agents SDK / Anthropic Agent SDK / MCP 全面差距；唯一亮点是 model_gateway 的 Provider 注册表 + 热加载 + 工具下沉 Java 的工程纪律

---

## 附录：关键文件路径

**Python agent**：
- `agent/app/main.py`
- `agent/app/core/agent_runtime.py`（核心 while 循环）
- `agent/app/core/runtime.py`（echo/real 门面）
- `agent/app/model_gateway/__init__.py`（Provider 注册表）
- `agent/app/tools_client.py`（Java 工具网关客户端）
- `agent/app/tools/sandbox.py`（孤儿代码）

**Java 后端**：
- `server/aioa-bridge/src/main/java/cn/aioa/bridge/controller/InternalToolController.java`（501 占位）
- `server/aioa-tool-sdk/src/main/java/cn/aioa/tool/sdk/PageContext.java`（SDK 仅 1 个文件）
- `server/aioa-resource/src/main/java/cn/aioa/resource/service/ToolGatewayService.java`（实际工具网关）
- `server/aioa-chat/src/main/java/cn/aioa/chat/service/RunService.java`（SSE 中转）
- `server/aioa-security/src/main/java/cn/aioa/security/PermissionCatalog.java`
- `server/aioa-org/src/main/java/cn/aioa/org/support/AuditRecorder.java`（SHA-256 哈希链 V2）
- `server/aioa-boot/src/main/resources/application.yml`
- `server/aioa-boot/src/main/resources/db/migration/`（V1-V53）

**前端**：
- `web/apps/shell/src/stores/assistant.ts`（AI 助手 store 193 行）
- `web/apps/shell/src/components/assistant/MessageList.vue`（缺 tool call UI）
- `web/packages/aioa-sdk/src/bridge.ts`（SDK 桥接 144 行）
- `web/apps/shell/src/micro/bridge.ts`（主应用消息监听）

**部署 / 配置**：
- `deploy/docker-compose.yml`
- `deploy/nginx/nginx.conf`（SSE 关键配置）
- `deploy/ops/`（缺失，profile=ops 引用不存在的 prometheus.yml）

**文档**：
- `docs/01-架构设计.md`（总纲）
- `docs/02-子应用接入规范.md`
- `docs/03-工具注册规范.md`
- `docs/04-接口契约/openapi.yaml` + `internal-agent.yaml`
- `docs/05-部署手册.md`
- `docs/28-未开工项规划与实施计划.md`（关键：未开工清单）
