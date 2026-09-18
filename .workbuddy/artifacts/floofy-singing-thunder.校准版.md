# AIOA 智能办公基座 · 项目全面评估报告

> 范围：`C:\Users\刘尖尖\WorkBuddy\aioa`
> 调研日期：2026-09-18
> 调研深度：4 路并行 Explore（git 历史 / Python agent / Java 后端+Bridge / 前端+文档+部署）+ 5 路汇总
> 文档定位：**评估报告**（不是实施计划）。用户的问题"识别项目、缺什么、优化、Python agent 对标框架"在本文档统一答复。

> **校准日期：2026-09-15（第二轮 · 逐项回代码取证）**
> 本文档首轮成稿于「V53 时代」的调研快照。本轮以当前工作副本 `HEAD = 30f235b` 的**实际代码 / 迁移 / 文档**逐项复核首轮结论，并把首轮遗漏的**已实现功能**回填（＝"补全功能"）。
> 判定分三类，全文就地标注：
> - **① 已过时** — 首轮判断已被后续迭代推翻（例：通用工作流引擎、通知多通道）
> - **② 仍成立** — 缺口未动，首轮结论有效（例：aioa-bridge 501、Python agent while 循环）
> - **③ 原缺项** — 首轮未覆盖、但系统**已经实现**的功能面（例：H5 用户端、企业 Gitee 主动初始化、V54-V58）
>
> ③ 类集中列于新增的 **§12 补全总账**；②类保留原判；①类在原文处加「校准结论」。

---

## 0. 一句话总评

**AIOA 不是"AI 办公骨架"了，它已经长成"业务域高度丰满的 AI 办公平台"——但骨架反而成了最薄弱的一环。**

- README 仍声称"M1 骨架已完成、M2/M3/M4 待启动"，但仓库实际已经跑到了 **V58** 迁移、10 个 Maven 模块、**29 个管理端视图 + 1 个 H5 用户端**、**21 份实施报告**。〔原文为"V53 / 28 视图 / 20+ 报告"，已按校准更新；校准说明见 §0.1〕
- **架构核心 aioa-bridge（工具注册表/桥接中间层）依然是占位（模块仅 9 个 .java = 1 Controller + 4 entity + 4 mapper）、InternalToolController 直接 throw notImplemented**——这是 README 反复强调的"新系统接入 = 注册工具"叙事的命门，至今没接上。〔原文称"142K 占位"，改为按类文件数描述更准确〕
- Python agent 服务是 **2514 行**的"FastAPI SSE 网关骨架"，**state graph、checkpoint、HITL 挂起、多 agent 协作全部未实现**，与 LangGraph / AutoGen / OpenAI Agents SDK 差距巨大。〔原文称"1900 行"，已按校准更新〕
- 后端业务域（aioa-resource / aioa-org / aioa-gitee）野蛮生长，把"基座不存业务数据"的红线几乎踩完。〔校准补充：这条判断**需要打折**——业务域确实是主力（11 域 / 77 表 / 256 端点），但"基座只存账号权限、会话、配置、知识库索引与审计日志"的原始红线确实被大幅突破：`leave_*` / `cost_alloc_*` / `biz_*` / `gitee_*` 等**业务真值已经落在基座库里**〕

**综合评分：6.5 / 10**。价值点是真的在的——但 README 与现实错位、bridge 旁路、Python agent 缺骨架，是阻碍"agent 协同办公 + 接入其他业务系统"目标的三座大山。

### 0.1 校准后结论（2026-09-15 复核）

首轮的"三座大山"里，**只有两座仍然成立**：

| 首轮结论 | 校准判定 | 依据 |
|---|---|---|
| README 与现实错位 | **仍成立，且错位扩大** | README 仍写"一期 M1 骨架"；现实已 **V58**（首轮称 V53） |
| aioa-bridge 仍是 142K 占位 | **仍成立** | `InternalToolController#invoke` 至今 `throw notImplemented("tool invoke 将在 M2 实现")` |
| Python agent 是 while 循环骨架 | **仍成立** | `agent_runtime.py` 336 行，`for _round in range(MAX_TOOL_ROUNDS+1)` + `_post_non_stream`（非 StateGraph、非真 streaming） |
| "后端业务域野蛮生长、把红线踩完" | **部分推翻** | 业务域确实是主力（11 个域、77 张表），但**通用工作流引擎 / 通知多通道 / 消息中心 / 企业 Gitee 初始化**均已从"缺失"变为"已交付"（§12） |

同时，首轮把若干**已实现能力误判为"缺失 / 雏形 / 硬编码"**，本轮已逐项纠正（§7 每行加「校准结论」列，§12 给全账）。**校准后综合评分重估为 7.2 / 10**（后端业务完整度 8.0→8.5、文档完整度 6.5→7.5；Bridge 2.0 与 Python agent 3.5 维持不变）。

---

## 1. 项目识别与定位

### 1.1 项目是什么

按 README 与实现现状合并陈述：

| 维度 | 内容 |
|---|---|
| **产品定位** | Agent-era Office Automation：公司内部 AI OA 基座，各业务系统（票务/调度/...)统一接入后自动获得 AI agent 能力 |
| **核心叙事** | "前端 + 后端 + Agent"三端基座；新业务系统接入 = 注册工具，不写 AI 代码 |
| **技术栈** | Vue 3.5 + wujie 1.0.22 + Element Plus 2.9 + Pinia + TS 5.6；Spring Boot 3.3 + JDK 21 + MyBatis-Plus 3.5 + Spring Security + springdoc；FastAPI 0.110 + Pydantic 2 + httpx 0.27 |
| **数据** | MySQL 8（远程 192.168.31.129）+ Redis 7（远程）+ MinIO；**58 个 Flyway 迁移（V1–V58）· 77 张表**〔校准：首轮称 53 迁移〕 |
| **LLM 网关** | DeepSeek / 通义千问 / vLLM / Ollama / echo 共 5 个 provider，可运行时热加载 |
| **部署** | docker-compose 一键起（minio + server + agent + web + nginx），远程库直连；**无 K8s** |
| **协作** | 单兵 AIOA Dev 97% 提交、无 PR 流程、main 单分支、commit 规范三类混用 |

### 1.2 当前阶段判定

**README 与现实严重错位**——仓库实际处于"已完成 V58 的成熟业务平台"，不是 M1 骨架。

| 维度 | README 声称 | 实际状态 |
|---|---|---|
| 里程碑 | M1 已完成、M2 待启动 | 已完成 **V58**：M1(骨架)→ M2(工具网关/模型)→ M3(RBAC/HITL)→ M4(RAG)→ 一期交付 35 FR → V18-V22 权限迭代 → V36-V44 组织改造 → V45-V47 docs/28 收口 → V48 Gitee → V48-V52 消息中心/菜单合并 → V53 repo URL 规范化 → **V54-V58 Gitea 托管方切换真机修复链**（provider 维度身份绑定 / JWT 令牌列放宽 / CREATING 卡死回填 / webhook 事件词表回填 / 回填文案中立化） |
| 后端模块 | 7 个 | **10 个**（多了 aioa-resource / aioa-org / aioa-gitee）；**41 个 Controller · 256 个端点 · 339 个 .java** |
| Bridge | "M2 完整" | **仍是骨架**（9 个 .java = 1 Controller + 4 entity + 4 mapper），InternalToolController 仍 throw notImplemented ⇒ **首轮结论成立（②）** |
| 用户端 | 未提 | **另有独立 H5 单文件用户端** `user-client/index.html`（4070 行 / 241KB），首轮完全遗漏（③） |
| 前端 | — | shell **15519 行 / 29 个视图**（首轮称 28）；另有 2 个示例子应用 + @aioa/sdk |

---

## 2. 各维度成熟度评分

| 维度 | 评分 | 关键证据 |
|---|---|---|
| **后端业务完整度** | **8.5 / 10** ↑ | **58 个迁移、339 个 .java、77 张表、41 Controller / 256 端点**、11 个业务域；Spring Security 双通道（JWT + Service JWT + JTI 吊销，`revoked_token` 表已建）、RBAC+实时授权（V36）、SHA-256 哈希链审计（V25 V2）、Gitee/Gitea OAuth+Webhook 完整闭环；**校准新增已交付**：通用审批流引擎（V45）、通知多通道（V52）、企业 Gitee 主动初始化（V51） |
| **前端实现** | **7.0 / 10** | pnpm workspace 三应用；微前端 wujie；AI 助手 SSE 流式 OK；缺 tool call / citation UI 气泡、缺 i18n 与暗色、无前端监控 |
| **子应用接入** | **6.0 / 10** | @aioa/sdk 设计干净，但 `getToken()` 仍返回 null（子应用无法独立调基座 API）；postMessage origin 用 `*` 无白名单 |
| **Agent（Python）** | **3.5 / 10**（不变 ②） | **2514 行**（含测试，首轮称 1900）；单 agent while 循环工具调用；state / checkpoint / HITL / 多 agent / 真 streaming / OpenTelemetry 全部缺失 |
| **Bridge 中间层** | **2.0 / 10** | 表结构 4 张齐了，Controller 直接 501；tool_permission / requires_approval 表里两列未被任何 service 读取 |
| **文档完整度** | **7.5 / 10** ↑ | **21 份 .md**（01-07 / 10 / 14-16 / 19-30）+ 接口契约目录；**校准修正**：`docs/class-diagram.mermaid`(96 行) 与 `docs/sequence-diagram.mermaid`(43 行) **已存在**（首轮称"缺"）；仍缺 ADR、真正的 ER 图、独立的"模型网关规范"、监控告警 Runbook |
| **部署能力** | **6.0 / 10**（不变 ②） | Compose 一键可用、nginx SSE 关键配置就位；无 K8s（无 `k8s/`、无 Helm）、**`deploy/ops/` 仍不存在**、缺 TLS 终止 |
| **整体** | **7.2 / 10** ↑ | 后端业务丰满且仍在扩张、前端可用、H5 用户端独立成体系；**Agent 与 Bridge 是仅剩的两块明显短板** |

---

## 3. Python Agent 实现评估（用户重点）

### 3.1 体量与组织

- 代码量约 **2514 行**（`app/` + `tests/`，含测试；首轮称 1902 行）
- 组织：`main.py` + `config.py` + `schemas.py` + `core/`（runtime / agent_runtime / echo_runtime / intent_router / worker_intake / guards / events / answer_shape）+ `model_gateway/`（`__init__` 注册表 + `gateway.py` + 5 provider + `mock_llm`）+ `tools/`（sandbox + gateway_client）+ `tools_client.py`
- 依赖极简（`agent/pyproject.toml` 实测）：fastapi / uvicorn[standard] / pydantic / **pyyaml** / httpx / pytest；**未引入 LangGraph / LangChain / AutoGen / CrewAI / OpenAI Agents SDK / Anthropic Agent SDK / MCP SDK / OpenTelemetry / pydantic-settings**
- 单测：`agent/tests/` 5 个文件（test_agent_runtime / test_echo_run / test_gateway / test_tools_client / test_worker_intake）

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

> **校准（2026-09-15）**：本节 6 条**逐条复核，全部仍然成立（②）**。
> - 第 1 条：`agent_runtime.py` 实为 **336 行**，核心仍是 `for _round in range(MAX_TOOL_ROUNDS + 1):`（L230-232），无任何 graph / node / edge 结构
> - 第 3 条：`_post_non_stream` 仍在（L142），全文无 `_post_stream`
> - 第 4 条：`grep -rn "sandbox"` / `"mock_llm"` / `"intent_router"` 在 `agent/app/`（排除自身文件）**命中 0 个调用点**（`intent_router` 仅被 `worker_intake.py` 的一句注释提及）⇒ 三个孤儿模块确认
> - 唯一变化：代码量 1902 → **2514 行**，增量落在 `config.py` / `schemas.py` / `model_gateway/gateway.py` / `tools_client.py`（**工程结构补齐，能力矩阵未变**）

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
aioa-common        ←  11 .java  ApiResponse / PageResult / BizException / TraceId / 领域事件
aioa-security      ←  13 .java  JwtAuthenticationFilter / ServiceTokenFilter / PermissionCatalog
aioa-admin         ←  30 .java  SysUser/Role/Permission/AppRegistry + AuthController / TenantController / ModelConfigController
aioa-bridge        ←   9 .java  ⚠ ToolDefinition/Permission/Log 4 张表 + 501 占位 Controller（② 仍未实现）
aioa-tool-sdk      ←   1 .java  ⚠ 仅 PageContext（无 @AioaTool 注解）（② 仍未实现）
aioa-chat          ←  26 .java  Conversation/Run/WorkerIntake/Stats + RunService(SSE)
aioa-resource      ← 111 .java  ToolGateway(实际网关)/Approval/Billing/KB/**notify 多通道**/ContentReview/Kpi/CostAlloc/Quota/Result 等业务域
aioa-org           ←  71 .java  Onboarding/AuditRecorder(哈希链)/**ApprovalFlow + ApproverResolver 策略族**/PermissionGrant/Leave/Quota/Org
aioa-gitee         ←  63 .java  OAuth/Webhook/SyncScheduler/3 个 TaskHandler/Crypto/**GiteaProviderClient**
aioa-boot          ←   4 .java  启动 + OpenApiConfig + **58 个 Flyway 迁移**
```

调用关系单向无循环：`boot → admin/chat/resource/org/gitee/bridge/tool-sdk → security → common`；`chat → org`，`gitee → org`；`org ↔ resource` 通过 `aioa-common` 领域事件解耦（`TenantProvisionedEvent` / `NotificationRequested`）。

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
| 通知多通道 | ✅ **（V52 完整交付，首轮 §7 误判为"雏形"）** | 站内 / 邮件 / 短信 / 推送 / HTTP 网关 5 通道，实现于 `aioa-resource/.../service/notify/`（**10 个类 / 1001 行**：`NotificationChannel` SPI + `InApp`/`Email`/`Sms`/`Push`/`HttpGateway` 5 实现 + `NotificationDispatcher` + `ConfigService` + `PreferenceService` + `DeliveryContext`）；配套 `notification_channel_config` / `notification_delivery`（投递记录 + 重试）/ `notification_preference`（用户偏好）3 张表 + `NotificationChannelController` + 前端 `NotificationCenterView.vue` |
| 知识库 RAG | ✅ | KbService + EmbeddingProvider + KnowledgeStore（MySQL/Elastic 双实现） |
| Gitee OAuth+Webhook | ✅ | 一次性 state + redirect_uri 严格匹配 + X-Gitee-Token + event_key 幂等 + 抢占式 outbox + 5 次退避 |
| Approval Flow | ✅ **（远比首轮描述强）** | V45 四期：`ApproverResolver` **策略族**（`DEPT_DUTY` / `UNIT_DUTY` / `DEPT_LEADER` / `ORG_ADMIN` / `TENANT_ADMIN` / `PLATFORM_ADMIN` / `SPECIFIC`）把"类型→人"的求值从引擎里剥离，流程模板可跨部门复用；V45 五期：节点**处理模式** `single` / `parallel`(会签，全通过才推进) / `grab`(抢占，任一人处理即完成) + **条件路由** + `levels`(向上几级) + `cc`(知会，生成 `task_role='CC'` 不阻塞流程)；V39 起 `APPLICANT_SUPERIOR` 按申请人层级逐级递推 |
| **企业 Gitea/Gitee 主动初始化** | ✅（首轮遗漏） | V51 + `docs/30`；企业提供**企业级令牌 + 组织名**，平台校验后落库激活（口径是"不自动初始化"，避免"看似开通实则不可用"） |
| **Gitea 托管方切换（真机修复链）** | ✅（首轮遗漏） | V54 provider-scoped 身份绑定（一个人可同时绑 Gitee + Gitea，解唯一键与 AEAD 解密冲突）· V55 令牌列放宽（Gitea 发的是 JWT，长于原列宽）· V56 CREATING 卡死回填为 FAILED · V57 webhook 事件词表按托管方回填 · V58 回填文案中立化（不把上一任托管方原文显示给当前用户） |
| **请假 / 假种 / 额度** | ✅（首轮遗漏） | `LeaveService` + `LeaveType` + `LeaveBalance` + `LeaveTypeProvisioner`（新租户自动播种）；V33 起按额度闸门走 `quotaTracked` 分支 |
| **成本分摊 / 配额体系** | ✅（首轮遗漏） | `CostAllocService`（规则 + 账单）· `QuotaService` / `QuotaExpandService` / `DeptQuota` / `OrgQuota` / `TenantResourcePool` / `ResourceGrantService` + `QuotaAllocLog` |
| **权限申请与发放** | ✅（首轮遗漏） | `PermissionGrantService` + `permission_grant` 表；V36 起**终态回调才置 ACTIVE 并发放**（`granted_by/at` = 终态处理人/时间） |
| **经营看板 / KPI / 仪表盘** | ✅（首轮遗漏） | `DashboardService` + `KpiController` / `AdminKpiController` + `biz_kpi` / `biz_kpi_insight` / `biz_kpi_trend` + `KpiView.vue` / `AuditView.vue` |
| **成果沉淀 / 项目与仓库** | ✅（首轮遗漏） | `ResultController` / `AdminResultController` + `ResultsView.vue`；`GiteeProjectsView.vue` / `GiteeProjectDetailView.vue` |
| **H5 单文件用户端** | ✅（首轮遗漏） | `user-client/index.html` 4070 行 / 241KB；`localStorage['aioa_session']` 持令牌、页面级 `go('page-xxx')` 路由、与 :5181 同源 |

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

> **校准（2026-09-15）**：本表 10 条**逐条复核，风险等级与结论全部不变（②）**，仅**行号发生位移**：
> - 默认密钥硬编码 —— **仍成立**：`application.yml` L57 `${AIOA_JWT_SECRET:aioa-dev-jwt-secret-please-change-in-production}`、L61 `${AIOA_SERVICE_JWT_SECRET:aioa-dev-service-jwt-secret-please-change}`、L85/L96（Gitee）、**L124/L135（新增 Gitea）** ⇒ 兜底默认串仍是"能起得来但很危险"的形态；prod 仍无启动校验（首轮称 L57-L92，因新增 Gitea 配置而后移）
> - HS256 单密钥 —— **仍成立**：`JwtTokenProvider:80` 与 `ServiceTokenProvider:42` 均 `signWith(key, Jwts.SIG.HS256)`，且两处注释仍写"**M2 起替换为 RS256**"（未替换）
> - CSRF 关闭 —— **仍成立**：`SecurityConfig:68` `.csrf(AbstractHttpConfigurer::disable)`（行号与首轮完全一致）
> - `health.redis.enabled=false` —— **仍成立**，位置由 L20-24 移至 **L162-163**
> - 新增关注点：Gitea 接入引入 `AIOA_GITEA_INSECURE_SKIP_VERIFY`（L148）与 `trust-store` 系列（L149-151）——**可关闭 TLS 校验的开关**，属本次切换的新增安全面，建议在 prod 强制 `false`

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

- 已覆盖：01-架构设计（总纲）/ 02-子应用接入规范 / 03-工具注册规范 / 04-接口契约（openapi.yaml + internal-agent.yaml）/ 05-部署手册 / 06-交接包借鉴说明 / 07-项目结构 / **10 / 14 / 15 / 16 / 19-30 共 15 份增量 PRD 与审计报告**
- **校准（2026-09-15）**：文档总数 **21 份 .md**（首轮称"30+ 份实施报告"，口径应为"21 份 md"，其中 docs/20 与 docs/28 是体量最大的两份）；**`docs/class-diagram.mermaid` + `docs/sequence-diagram.mermaid` 已存在**；`docs/28` 的定位是"**未开工项规划与实施计划**"且**已全部收口**（首轮把它当作"未开工清单"引用，方向相反）
- **仍缺**：表级 ER 图（**77 表**，非首轮所写 26 表）、登录/提问/HITL/RAG/Gitee OAuth 5 张关键时序图、ADR（架构决策记录）、独立模型网关规范、K8s 清单、监控告警 Runbook、前端开发规范
  - **实测两张 mermaid 的实际内容（消除歧义）**：`class-diagram.mermaid` 是**审批域类图**（`ApprovalFlowService` / `PermissionGrantService` / `OrgGuard` / `OrgStatMapper` 的方法签名），**不是表级 ER 图**；`sequence-diagram.mermaid` 覆盖**2 条**权限域序列（"部门名义申请"、"知会点开自动已读"），**与首轮要求的那 5 张（登录 / 提问 / HITL / RAG / Gitee OAuth）完全不重叠** ⇒ **本节"缺 ER 图 + 5 张时序图"的结论实质成立**，只是"一张图都没有"的表述需要修正为"两张图都在别的域"

### 6.2 部署完整度

- 已覆盖：docker-compose 一键、nginx SSE 关键配置、MinIO 持久卷、profile=model 附加 vLLM/Ollama
- **缺失**：K8s Deployment/Service/ConfigMap/Secret/Ingress 清单、HPA / PDB / NetworkPolicy、Helm chart / Kustomize、TLS 终止、限流 zone、alert rules、Grafana dashboard、AES 加密密钥 / SMTP / Webhook 签名密钥未进 .env.example
- **校准（2026-09-15）**：① `deploy/` 实际只有 `docker-compose.yml` + 3 个 `Dockerfile` + `nginx/{nginx.conf,web.conf}` + `.env.example`，**`deploy/ops/` 仍不存在**；② **`application.yml` 里已无 `ops` profile**（全文只有 `management:` 块，`exposure.include: health`、`show-details: never`）⇒ 首轮"profile=ops 引用不存在的 prometheus.yml"**已不成立**（该 profile 不存在，因此无引用的悬空文件）；③ `management.health.redis.enabled=false` **仍成立**（Redis 已依赖但未纳入健康检查）；④ 新增了 `AIOA_GITEA_*` 一组配置（`insecure-skip-verify` / `trust-store` 系列）——Gitea 托管方切换的配套

---

## 7. 缺失模块清单（按优先级）

### P0 — 阻塞"接入其他业务系统"目标

| 模块 | 当前状态 | 补齐方案 |
|---|---|---|
| **通用工作流引擎** | ~~ApprovalService 是硬编码流程；仅支持知会对象~~ **① 已推翻大半** | **校准（V45 已交付）**：`ApproverResolver` 策略族（7 类口径）+ 条件路由 + 会签(parallel) + 抢占(grab) + levels + cc 知会，`docs/28` 记 F4/F5/F3-1/F3-2 "已完成"。**仍缺**：加签、子流程、模板版本对比 —— 剩余项可在既有 `steps_json` DSL 上扩展，**无需引入 Camunda / Flowable** |
| **aioa-bridge 真实实现** | InternalToolController 501；ToolGatewayService 不查 tool_permission | 见 §4.7 P0 —— 校准：**② 仍成立**（实读代码确认 501 未变，`ToolGatewayService` 全文无 `tool_permission` 读取） |
| **@aioa/sdk.getToken 真实化** + 主应用 API 代理 | SDK 注释写"M1 恒返回 null" | 实现 shell 侧 `aioa.proxyRequest({url, method, body})`；SDK getToken 经 MessageChannel 异步取短期票据 —— 校准：**② 仍成立**（`web/packages/aioa-sdk/src/bridge.ts:89-91` 仍是 `getToken() { return null }`） |
| **postMessage origin 白名单 + appCode 签名** | 全 `*` | 立即加 origin 白名单 + 短期 nonce + appCode 签名校验 —— 校准：**② 仍成立**（`shell/src/micro/bridge.ts:76` 与 `aioa-sdk/src/bridge.ts:127` **双侧**均传 `'*'`，无白名单） |

### P1 — 差异化竞争力

| 模块 | 当前状态 | 补齐方案 |
|---|---|---|
| **tool call / citation / 思考链 UI 气泡** | MessageList 只渲染文本 | 加 `<tool_call>` 折叠块（参考 Cursor/ChatGPT）+ citation chip + 思考链路 |
| **通知多通道 Sender SPI 端到端** | ~~aioa-resource/notify 子目录雏形~~ **① 已交付（首轮误判）** | **校准（V52 + `docs/30` §2 "已实现"）**：`aioa-resource/.../service/notify/` **10 个类 / 1001 行** —— `NotificationChannel` SPI + `InApp`/`Email`/`Sms`/`Push`/`HttpGateway` 5 实现 + `NotificationDispatcher`（异步分发，监听 `NotificationRequested`）+ `ConfigService` + `PreferenceService`；表 `notification_channel_config` / `notification_delivery`（逐条投递记录）/ `notification_preference`（用户级偏好）；`NotificationChannelController` + 前端 `NotificationCenterView.vue`。**本项无需再补** |
| **通用任务调度面板** | 只有 GiteeSyncScheduler / WorkerScheduleService | XXL-Job / Quartz + 任务 CRUD + 触发记录 + 失败告警 |
| **ES 全文检索** | KB 用 MySQL `LIKE`；vector 模式预留 | 引入 ES 或 Meilisearch，与 pgvector / mysql 向量形成"全文 + 语义"双路召回 |
| **K8s 部署清单** | 无 yaml | `k8s/base/` + `k8s/overlays/{dev,staging,prod}/`（Kustomize）；HPA / PDB / NetworkPolicy |
| ~~**ER 图 + 关键时序图**~~ **① 部分已交付（但不在同一域）** | 缺 | **校准**：`docs/class-diagram.mermaid`（96 行）+ `docs/sequence-diagram.mermaid`（43 行）**已存在，但实测内容是**——前者为**审批域类图**（方法签名级，非表级 ER），后者仅覆盖**2 条权限域序列**（部门名义申请 / 知会自动已读）。**结论**：首轮要的"表级 ER 图（77 表）+ 登录/提问/HITL/RAG/Gitee OAuth 5 张时序图"**确实一张都没有**；"完全缺图"的措辞改为"**图在别的域，覆盖不到本次所需的 6 类视图**" |
| **ADR 起步** | 决策散在各期增量 PRD | `docs/adr/0001-*.md` 沉淀 10+ 关键决策 |
| **独立"模型网关规范"** | 散落在 README + application.yml 注释 + __init__.py | 与"工具注册规范"同级的独立文档 |

**P1 校准小结（2026-09-15）** —— 8 项中 **2 项已交付**（通知多通道、ER/时序图部分），**6 项仍缺且逐项复核有效**：

| 仍缺项 | 复核证据 |
|---|---|
| tool call / citation UI 气泡 | `web/apps/shell/src/components/assistant/` 仅 4 个组件（AssistantDrawer / ContextBar / ConversationList / MessageList），**全目录 0 处** `tool_call` / `citation` / 思考链渲染 |
| 通用任务调度面板 | 仅 `GiteeSyncScheduler` + `WorkerScheduleService` 两个专用调度器，无任务 CRUD / 触发记录 / 失败告警面板 |
| ES 全文检索 | `KbService` 注释自述"现阶段为 MySQL 实现（LIKE 检索）"，`KnowledgeStore` SPI 预留向量模式但未启用 |
| K8s 部署清单 | 无 `k8s/`、无 `helm/`；仅 `deploy/Dockerfile.{server,agent,web}` + docker-compose |
| ADR 起步 | 无 `docs/adr/` |
| 独立模型网关规范 | 仍散落在 README / `application.yml` / `model_gateway/__init__.py` |

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

**P2 / P3 校准（2026-09-15）**：**逐项复核，全部仍然成立（②）**，无一项已交付。
- P2：`BizSystemView.vue` 仍只是已注册系统列表（无版本/评分/安装/卸载）；无 Sentry/RUM；`grep vue-i18n` 无命中（`dark` 仅命中 Element Plus 色阶变量与 `effect="dark"`）；`demo-ticket` 仍为静态数据；无 `mcp` SDK 依赖；JWT 仍 HS256（`JwtTokenProvider`），Gitee/Gitea 仅为 OAuth client
- P3：**无 `.github/workflows`**（CI/CD 未建）；**无 vitest**（`web` 各 `package.json` 无 `vitest`，全仓 0 个 `*.spec.ts` / `*.test.ts`）；KB 无 Tika/Unstructured；`aioa-boot` 下仅 `AioaBootApplication` + `config/` + `runner/`，**无 `/openapi/v1` 实现**；无容灾/备份演练脚本；无 A2A 协议；向量库仍为 `KnowledgeStore` SPI 预留

---

## 8. 全局优化建议（按 ROI 排序）

### 立刻做（1-2 周）

1. **bridge 网关实现 + tool_permission/requires_approval 接入**——叙事的命门
2. **@aioa/sdk.getToken 真实化 + 主应用 API 代理**——子应用独立业务请求能力
3. **postMessage origin 白名单 + appCode 签名**——M1 阶段就该有的安全门
4. **tool call / citation UI 气泡**——提升助手可信度
5. **K8s 基础清单**（Kustomize + Ingress + ConfigMap + Secret）
6. ~~**ops profile 修复**：补 prometheus.yml + alert rules + Grafana dashboard~~ → **校准降级**：`application.yml` 已无 `ops` profile，悬空引用不复存在；改为"**若要引入可观测性，从零建 `deploy/ops/`**"，优先级下调
7. **前端错误监控 + 性能埋点**（✅ 复核仍缺）
8. ~~**立即清理 .env.gitee-real + .aioa_login.json（已泄漏的凭据）**~~ → **校准：风险等级下调**。实测`.env.gitee-real`（及新增的 `.env.gitea-real`）**从未被 git 跟踪**（`git log --all -- .env.gitee-real` 为空）、且被 `.gitignore:34 .env.*` 覆盖 ⇒ **不属于"已泄漏"，无需 `filter-branch` / BFG**。仍建议从 disk 删除或轮换令牌（防御性）
9. ~~**.gitignore 补丁**：`scripts/_*` / `*.probe*.txt` / `e2e_*_exit.txt` / `.env.*real` / `.env.*local` / `.aioa_login.json` / `.workbuddy/artifacts/`~~ → **校准：大部分已落地**。实测已具备：`.env` + `.env.*` + `!.env.example`（覆盖 `.env.*real` / `.env.*local`）、`scripts/_diag_*`、`scripts/_tmp_*`、`scripts/_*.png`、`e2e_*.py` / `e2e_*.json` / `e2e_*.sh`、`.workbuddy/*.png|txt|doc_*.json|probe_*.py`、`ux-review/*.png`、根目录临时脚本 `/_*_inspect.py` 等。**仍缺**：`*.probe*.txt`、`e2e_*_exit.txt`、`.workbuddy/artifacts/`（若交付档需入库则不应忽略）
10. **README 重写 §1 定位、§2 仓库结构、§5 里程碑**——**复核仍未做，仍是第一优先**：README 现仍写"公司内部 AI OA 基座（一期 M1 骨架）"、§2 仍列 7 个后端模块且把 `aioa-bridge` 标为"M2 完整，M1 骨架"、完全未提 `aioa-resource`/`aioa-org`/`aioa-gitee`/`user-client` 与 V50+ 的 Gitea 接线

### 短期（1-2 月）

11. LangGraph 集成 + checkpoint + HITL 挂起恢复
12. ~~通用工作流引擎（workflow_definition/node/instance/task + JSON DSL）~~ → **校准：已由 V45 以"引擎内嵌 + `steps_json` DSL"路线交付**（策略族 + 条件路由 + 会签/抢占 + levels + cc），**无需再引 Camunda**；剩余仅"加签 / 子流程 / 模板版本对比"三项增量
13. Bucket4j 全局限流 + Resilience4j 熔断（✅ 复核仍缺）
14. ~~通知多通道 Sender SPI~~ → **✅ 已交付（V52）**，从本清单移除
15. ES / Meilisearch 全文检索（✅ 复核仍缺；`KbService` 自述"现阶段 MySQL LIKE"）
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
- ~~通用工作流引擎（WorkflowDefinition + JSON DSL + 流程编辑器）~~ → **校准：主体已由 V45 交付**，只剩"加签 / 子流程 / 模板版本对比"
- ~~通知多通道 Sender SPI 端到端~~ → **校准：已由 V52 交付，本项完成**
- MCP Server 暴露（spring-ai-mcp-server）
- OAuth2/OIDC 服务端
- ES 全文检索
- ER 图（**77 表**）+ 5 张时序图 + ADR 起步
- 独立"模型网关规范"文档

完成第 3 步后，AIOA 才能真正对外宣称"agent 协同办公 + 接入其他业务系统的 AI OA 基座"。

> **三步走校准（2026-09-15）**：第 1 步的"止血"三件事里，**`.gitignore` 补丁与凭据清理已基本到位（且凭据从未入库，风险等级下调）**，**唯 README 重写仍未做**；bridge 网关仍未实现。第 3 步的"通用工作流引擎"与"通知多通道"**已提前交付**。⇒ **真正剩余的两条主线不变：① README + bridge（Java 侧叙事命门）② Python agent 骨架（LangGraph / checkpoint / HITL / 真 streaming）**。

---

## 10. 用户确认的 P0 改造线 + 推荐实施顺序

用户已确认四条 P0 改造线全部要启动。按依赖与 ROI 排序：

### Phase A — 基建止血（Day 1-5，可单人并行）

1. .gitignore 补丁：`scripts/_*` / `*.probe*.txt` / `e2e_*_exit.txt` / `.env.*real` / `.env.*local` / `.aioa_login.json` / `.workbuddy/artifacts/` —— **校准：已完成约 6/7**（见 §8 第 9 条；只剩 `*.probe*.txt` / `e2e_*_exit.txt` / `.workbuddy/artifacts/`）。另注：`e2e_*.py` 已在忽略列表 ⇒ **回归套件按设计不入库**（跑前先 `ls scripts/ | grep -E "^e2e_"` 确认本地存在）
2. 清理已泄漏凭据：`.env.gitee-real` / `.aioa_login.json`（从 disk 删除）+ 检查 git 历史是否曾 tracked —— **校准：`git log --all -- .env.gitee-real` 为空 ⇒ 从未 tracked，`filter-branch` / BFG 步骤取消**；文件仍在 disk（另有新增 `.env.gitea-real`），均被 `.gitignore:34 .env.*` 覆盖。**降级为防御性清理 + 令牌轮换**
3. scripts/ 下划线脚本归档 —— **校准：已以另一种方式落地**：`_diag_*` / `_tmp_*` / `_*.png` 直接进 `.gitignore`（不归档、不入库）；**而 `_check_*.py` 被明确保留入库**（长期回归探针，如 `_check_gitea_ui_provider.py` / `_check_menu_scroll.py`），`.gitignore` 内附注释说明该纪律。当前 `scripts/` 共 77 项、其中 **37 项入库**
4. README §1-2-5 重写，与 **V58** 现实对齐（声明 aioa-bridge 真实状态、添加 aioa-resource/org/gitee 三个模块、补 user-client 与消息中心）—— **仍未做，仍是第一优先**
5. 根目录临时文件清理：bind_probe.txt / probe*.txt / e2e_v50_*.txt → **校准：已完成**（根目录已无 `*.txt` / `*.json` 临时件）
6. 暂时禁用 profile=ops 或补 deploy/ops/prometheus.yml —— **校准：已自然消解**（`application.yml` 已无 `ops` profile；`deploy/ops/` 仍不存在，属"未建"而非"悬空引用"）

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

后续 P1（~~通知多通道~~ ✅已交付 / ~~通用工作流引擎~~ ✅主体已交付 / K8s / ES / MCP Server / OAuth2）视 Phase A-D 完成后启动
```

### 验证方式（Phase A-D 完成后）

1. **bridge 真实化验收**：用 scripts/SMOKE_v48.py 跑通 tool 注册 → permission 校验 → invoke → 审批挂起 → 恢复 全链路
2. **LangGraph 验收**：用 agent/tests/test_agent_runtime.py + 新增 test_graph_checkpoint.py + test_hitl_resume.py 跑通 checkpoint 持久化 + HITL 中断恢复
3. **SDK 安全验收**：用 scripts/_diag_real_gitee_*.py 跑通"跨子应用代理调用基座 API + 篡改 appCode 被拒绝" —— **校准：该组脚本仍在 `scripts/`（未归档），共 10 个 `_diag_real_gitee_*` / `_diag_gitee_*` / `_diag_gitea_*`**
4. **整体 e2e**：`scripts/_run_all_regression.sh` 覆盖 admin / org / resource / chat / gitee / agent 六域回归 —— **校准：脚本仍在（未归档），且已纳入 `_check_menu_scroll.py`**。注意 `e2e_*.py` 被 gitignore（不入库，但本地存在 20+ 套），跑前先 `ls scripts/ | grep -E "^e2e_"`

---

## 11. 一句话结论（回答用户问题）

> **AIOA 是个"骨架没长大、业务旁路野蛮生长、Python agent 是 while 循环"的 AI 办公平台。**

- **项目识别**：Vue3 + wujie + Spring Boot 3.3 + FastAPI + MyBatis-Plus 的 AI OA 基座，已完成 **V58** 迁移 · **10 模块 / 339 .java / 77 表 / 41 Controller / 256 端点** · **21 份文档** · **29 个管理端视图 + 1 个 H5 用户端**，但 README 严重过时（仍写"M1 骨架"）
- **缺失模块**（**校准后**，已剔除误判）：aioa-bridge 真实网关、@aioa/sdk.getToken、postMessage origin 白名单、K8s、ES 全文检索、MCP Server、OAuth2/OIDC、CI/CD、表级 ER 图 / ADR / 5 张时序图、国际化、暗色、前端监控、通用任务调度面板、加签/子流程/流程模板版本对比
  - ~~通用工作流引擎~~ ✅ 主体已由 V45 交付 ｜ ~~通知多通道~~ ✅ 已由 V52 交付 ｜ ~~ER/时序图~~ ◐ 已有 class/sequence mermaid
- **优化方向**（**校准后**）：①**README 重写 + bridge 真实化**（Java 侧叙事命门）②**Python 引入 LangGraph + checkpoint + HITL + 真 streaming**（Python 侧骨架）③SDK token + origin 安全 ④tool call / citation UI 气泡 ⑤K8s 部署 ⑥ES 全文检索 ⑦~~ops profile 修复~~（该 profile 已不存在，降级为"按需从零建 observability"）
- **Python agent 实现度**：**3.5/10**（复核不变）——单 agent while 循环工具调用完善；state graph / checkpoint / HITL / 多 agent / 真 streaming / OpenTelemetry / Anthropic driver / 并行调用 / prompt caching 全部缺失；与 LangGraph 11 项核心能力仅 1/11。**唯一变化**：代码量 1902 → **2514 行**（增量在 `config.py` / `schemas.py` / `gateway.py` / `tools_client.py`，能力矩阵未变）
- **结构标准度**：与 LangGraph / OpenAI Agents SDK / Anthropic Agent SDK / MCP 全面差距；亮点是 model_gateway 的 Provider 注册表 + 热加载 + 工具下沉 Java 的工程纪律，**以及后端在 V45-V58 期间把"工作流引擎 / 消息中心 / 通知通道 / Gitea 托管方切换"四块硬骨头逐块啃下**——这正是"骨架没长大但业务在长"的实证

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
- `server/aioa-boot/src/main/resources/db/migration/`（**V1-V58**，58 个文件）

**前端**：
- `web/apps/shell/src/stores/assistant.ts`（AI 助手 store 193 行）
- `web/apps/shell/src/components/assistant/MessageList.vue`（**仍缺 tool call UI**；同目录仅 AssistantDrawer / ContextBar / ConversationList / MessageList 4 个组件）
- `web/packages/aioa-sdk/src/bridge.ts`（SDK 桥接 **143 行**；**L89-91 `getToken() { return null }`**、**L127 `postMessage(..., '*')`**）
- `web/apps/shell/src/micro/bridge.ts`（主应用消息监听；**L76 `postMessage(payload, '*')`**）

**部署 / 配置**：
- `deploy/docker-compose.yml`
- `deploy/nginx/nginx.conf`（SSE 关键配置）
- `deploy/ops/`（**仍不存在**；但 `application.yml` 已无 `ops` profile，属"未建"而非"悬空引用"）

**文档**：
- `docs/01-架构设计.md`（总纲）
- `docs/02-子应用接入规范.md`
- `docs/03-工具注册规范.md`
- `docs/04-接口契约/openapi.yaml` + `internal-agent.yaml`
- `docs/05-部署手册.md`
- `docs/28-未开工项规划与实施计划.md`（**口径纠正：这是"未开工项已全部收口"的验收文，不是待办清单**）
- `docs/class-diagram.mermaid` / `docs/sequence-diagram.mermaid`（**已存在**，首轮称"缺"）
- `docs/10 / 14 / 15 / 16 / 19-30`（职责边界 / 账号 / 权限矩阵 / 组织作用域 / 七项审计 / 全链路 E2E / 层级流转 / 登录口径 / 权限审批改造 / 增量 PRD·架构·验收 / Gitee 联动 / 企业 Gitea 初始化与消息中心）

**首轮遗漏的关键路径（本轮补入）**：
- `user-client/index.html`（**H5 单文件用户端 4070 行 / 241KB**）+ `user-client/serve.py`
- `server/aioa-resource/src/main/java/cn/aioa/resource/service/notify/`（**通知多通道 10 个类 / 1001 行**）
- `server/aioa-org/src/main/java/cn/aioa/org/support/approver/` 族 + `ApproverResolver.java`（**工作流策略族**）
- `server/aioa-resource/src/main/java/cn/aioa/resource/controller/ToolGatewayController.java`（工具网关对外入口）
- `server/aioa-gitee/src/main/java/cn/aioa/gitee/client/GiteaProviderClient.java` + `RepoProviderClient.java`（**托管方抽象**）
- `server/aioa-boot/src/main/resources/db/migration/V54__gitee_account_provider.sql` ~ `V58__gitee_project_backfill_reason_neutralize.sql`（**Gitea 切换真机修复链**）
- `web/apps/shell/src/views/NotificationCenterView.vue` / `KpiView.vue` / `ResultsView.vue` / `CostAllocView.vue` / `GiteeProjectsView.vue` / `GiteeProjectDetailView.vue`（**首轮未列的业务视图**）

> **继续阅读 →「§12 补全总账」**：本轮"对照当前系统已有功能与模块补全功能"的交付面（规模真相 / 首轮误判 4 项 / 首轮遗漏 13 项 / 仍成立的短板清单）。

---

## 12. 补全总账：当前系统已实现功能（首轮遗漏 / 误判）

> 本章是本轮"**对照当前系统已有功能和模块，补全功能**"的交付面。
> 取证口径：**只认代码/迁移/SQL 表/视图文件是否真实存在并能闭环**，不认文档宣称。

### 12.1 规模真相（首轮 → 校准）

| 指标 | 首轮 | 校准（2026-09-15 · `HEAD 30f235b`） |
|---|---|---|
| Flyway 迁移 | 53（V1-V53） | **58（V1-V58）** |
| Maven 模块 | 10 | 10（不变） |
| `.java` 文件 | 320 | **339** |
| Controller / 端点 | 30 / — | **41 / 256** |
| 数据库表 | 26（§7）/ 65（docs/19） | **77** |
| 管理端视图 | 28 | **29** |
| 文档 .md | 30+ | **21**（+ 1 接口契约目录 + 2 mermaid） |
| Python agent 行数 | 1902 | **2514** |
| 用户端 | 未提 | **H5 单文件 4070 行** |
| 前端 shell | — | **15519 行** |

### 12.2 首轮"缺失/雏形/硬编码"→ 实际已交付（① 类，共 4 项）

| # | 首轮判断 | 实际状态 | 证据 |
|---|---|---|---|
| 1 | 通用工作流引擎缺失：ApprovalService 硬编码、仅支持知会 | **V45 已交付大半** | `ApproverResolver` + `ApproverStrategy` + `ApproverStrategyConfig` + `DutyApproverStrategy`(抽象) / `DeptDutyApproverStrategy` / `UnitDutyApproverStrategy` / `DeptLeaderApproverStrategy`；`ApprovalFlowService` 的 `node_mode` = `single`/`parallel`/`grab`；条件路由（`ConditionPlan` / `firstUnconditional`）；`levels`（向上几级）+ `cc`（知会，`task_role='CC'`）；迁移 V45 加 `node_mode` / `node_duty` 列。`docs/28` 记 F4 / F5 / F3-1 / F3-2 全"已完成" |
| 2 | 通知多通道只是"notify 子目录雏形" | **V52 完整交付端到端** | `service/notify/` 10 类 1001 行：`NotificationChannel`(SPI) + `InApp` / `Email` / `Sms` / `Push` / `HttpGateway` 5 实现 + `NotificationDispatcher`（领域事件异步分发）+ `NotificationChannelConfigService` + `NotificationPreferenceService` + `DeliveryContext`；表 `notification_channel_config` / `notification_delivery` / `notification_preference`；`NotificationChannelController` + `NotificationCenterView.vue`；`docs/30` §2 标"已实现" |
| 3 | ER 图 + 时序图"缺" | **有两张图，但不在所需域** | `docs/class-diagram.mermaid`(96 行) = **审批域类图**（`ApprovalFlowService`/`PermissionGrantService`/`OrgGuard`/`OrgStatMapper` 方法签名），非表级 ER；`docs/sequence-diagram.mermaid`(43 行) = **2 条权限域序列**（部门名义申请、知会自动已读）。**首轮要的"77 表 ER + 登录/提问/HITL/RAG/Gitee OAuth 5 张时序图"确实一张都没有** ⇒ 结论实质成立，表述须由"缺图"改为"**图在别的域**" |
| 4 | `docs/28` 是"未开工清单" | **口径反了** | `docs/28` 自我定位"本轮未开工项的**唯一进度权威**"，且 §1 总表 F4/F5/F3-1/F3-2/D-1..D-8/G-1..G-3 **全部"已完成/已核销"**，§6 为验收结果 ⇒ 它是"已收口"文，不是待办 |

### 12.3 首轮未覆盖、但系统已实现的功能面（③ 类，共 13 项）

| # | 功能面 | 证据 |
|---|---|---|
| 1 | **H5 单文件用户端** | `user-client/index.html` 4070 行 / 241KB；`localStorage['aioa_session']`、`go('page-xxx')` 页面路由、:5181 仅绑 127.0.0.1 |
| 2 | **统一消息中心（多通道触达）** | V52 + `notification_*` 3 表 + `NotificationCenterView.vue` + `docs/30` §2 |
| 3 | **企业 Gitea/Gitee 主动初始化** | V51 + `gitee_tenant_config` + `docs/30` §1（口径：**不自动初始化**，企业显式提供企业级令牌 + 组织名） |
| 4 | **Gitea 托管方切换真机修复链（V54-V58）** | V54 provider-scoped 身份绑定（解唯一键 + AEAD 密钥冲突）· V55 令牌列放宽（Gitea 发 JWT）· V56 CREATING 卡死回填 FAILED · V57 webhook 事件词表按托管方回填 · V58 回填文案中立化（不泄露上一任托管方） |
| 5 | **请假 / 假种 / 余额** | `LeaveService` / `LeaveType` / `LeaveBalance` + `LeaveTypeProvisioner`（新租户自动播种）+ `leave_*` 3 表 |
| 6 | **成本分摊** | `CostAllocService` / `CostAllocRule` / `CostAllocBill` + `CostAllocView.vue` |
| 7 | **配额体系（租户→机构→部门→个人）** | `QuotaService` / `QuotaExpandService` / `DeptQuota` / `OrgQuota` / `TenantResourcePool` / `QuotaAllocLog` + `quota_package` / `dept_quota` / `org_quota` / `tenant_quota` 表 |
| 8 | **资源授权 / 权限申请发放** | `ResourceGrantService` / `PermissionGrantService` + `permission_grant` / `resource_grant` + V36 终态回调才置 ACTIVE |
| 9 | **经营看板 / KPI** | `DashboardService` / `KpiController` / `AdminKpiController` + `biz_kpi` / `biz_kpi_insight` / `biz_kpi_trend` + `KpiView.vue` |
| 10 | **成果沉淀 / 项目与仓库** | `ResultController` / `AdminResultController` + `ResultsView.vue`；`GiteeProjectsView.vue` / `GiteeProjectDetailView.vue` |
| 11 | **组织域全景** | `org_institution` / `org_department` / `org_member` / `org_duty`（**职务字典是"谁是部门负责人"的唯一权威口径**）+ `DutyProvisioner` / `ApprovalFlowProvisioner` / `AccountProvisioner` |
| 12 | **哈希链审计 + 审计查询** | `AuditRecorder`（SHA-256，微秒截断 + 自哈希可复算）+ `AuditQueryService` + `AuditView.vue` + `client_activity_log` / `sys_login_log` |
| 13 | **内容审核 / 审核记录** | `ContentReviewController` + `ReviewRecordsView.vue` / `ContentReviewView.vue`；V34 起租户管理员建的内容 `audit_status=PENDING`，成员不可见、不被调度 |

### 12.4 校准后"仍然成立"的短板（② 类 · 真正要动手的清单）

| 优先级 | 短板 | 校准证据 |
|---|---|---|
| **P0** | aioa-bridge 网关未实现 | `InternalToolController#invoke` → `throw notImplemented("tool invoke 将在 M2 实现")`；模块仅 9 个 .java |
| **P0** | `tool_permission` / `requires_approval` / `idempotency_required` 无 service 读取 | `ToolGatewayService` 全文只有 `requiredRoles`（L50-51 / L127） |
| **P0** | aioa-tool-sdk 空壳 | `server/aioa-tool-sdk/src/main/java/cn/aioa/tool/sdk/PageContext.java` —— **全模块仅此 1 个 .java** |
| **P0** | @aioa/sdk.getToken 恒 null | `aioa-sdk/src/bridge.ts:89-91` |
| **P0** | postMessage origin 无白名单 | `shell/src/micro/bridge.ts:76`、`aioa-sdk/src/bridge.ts:127` 双侧 `'*'` |
| **P0** | README 与现实错位 | 仍写"一期 M1 骨架"、7 模块、bridge "M2 完整" |
| **P1** | Python agent 无 StateGraph / checkpoint / HITL / 多 agent / 真 streaming / OTEL | `agent_runtime.py` 336 行，`for _round in range(MAX_TOOL_ROUNDS+1)` + `_post_non_stream`；`pyproject.toml` 无 LangGraph / SQLAlchemy / OTEL |
| **P1** | assistant 无 tool call / citation UI | `components/assistant/` 4 文件，全目录 0 处 `tool_call` / `citation` |
| **P1** | 无 K8s / Helm / CI | 无 `k8s/`、`helm/`、`.github/workflows` |
| **P1** | 无 i18n / 暗色 / 前端监控 | 无 `vue-i18n`；`dark` 仅命中 Element Plus 色阶变量与 `effect="dark"` 标签 |
| **P1** | KB 检索仍 MySQL `LIKE` | `KbService` 自述"现阶段为 MySQL 实现（LIKE 检索）" |
| **P2** | 无 ADR / 模型网关规范 / 通用调度面板 / ES / MCP Server / OAuth2 / 应用市场 | 逐项 `ls` 均不存在 |
| **P2** | 工作流剩余 3 项：加签 / 子流程 / 模板版本对比 | 代码中无"加签 / 子流程"实现，`approval_flow_def` 无 version 列 |

### 12.5 一句话

**首轮把"业务已长成的部分"低估了，又恰好把"两块真正没长的骨架"估准了。**
校准后的真实画像是：**后端业务面（11 域 / 77 表 / 256 端点）持续扩张且质量在线，工作流引擎与消息中心两块硬骨头已啃下；而 `aioa-bridge`（接入叙事）与 Python agent（智能骨架）仍是原样未动。**
⇒ 剩余工作可以收敛为**两条并行主线**：
- **线 1（Java / 叙事）**：README 重写 → bridge 网关真实化（`tool_permission` + `requires_approval` + `idempotency`）→ tool-sdk 注解契约
- **线 2（Python / 骨架）**：LangGraph StateGraph + checkpointer + HITL 挂起恢复 + 真 streaming + OTEL
- **并行的第三方安全项**：`getToken` 真实化 + origin 白名单 + appCode 签名
