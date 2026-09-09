# AIOA 项目长期记忆

## 项目本质
- AIOA = 地级市 AI 公共服务平台 · AI 工作台（左老师设计交接包为蓝图）。仓库当前实现 = **管理端/基座工作台**：Vue3 微前端 shell (`web/apps/shell`) + Java Spring Boot 单体 (`server/`, 7 个 Maven 模块) + MySQL 8 本地库 + Python FastAPI echo agent (`:8000`)。
- 与设计文档（uni-app 小程序 + AgentScope 2.0 Python + PostgreSQL + 8 微服务域 + 41 实体）**严重偏离**。偏差属"规格 vs 代码"。**用户已于 2026-09-07 确认方向：改代码对齐设计文档**，按五层架构演进（接入与交互层 / API网关与安全层 / 智能体运行层 / AI能力与连接层 / 平台底座层）。Layer 3 Agent Runtime M2（真实 LLM 流式推理 + DeepSeek Harness + token 计量）已实现并验证。正式核对报告：`AIOA_设计文档与运行代码核对报告.md`。

## 对齐路线（五层，2026-09-07 起）
- 接入与交互层：web ChatBox 组件 + IM 网关（#53 待做）
- API 网关与安全层：server 已有 aioa-security，演进网关+SSO+审计（#54）
- 智能体运行层：agent `runtime.py` 门面 + `agent_runtime.py`(M2 真实推理) + `model_gateway`(DeepSeek Harness)；多Agent编排（#59 待做）
- AI 能力与连接层：server `aioa-tool-sdk` + agent `tools/gateway_client`（#56）
- 平台底座层：server `aioa-admin` 计费/RBAC/租户（#57）

## 本地运行方式
- 后端：`cd server && bash mvnw -DskipTests -q package`（绕开系统 `mvn` 损坏）→ 用真实 JDK 路径
  `C:/Users/刘尖尖/.jdks/ms-21.0.8/bin/java -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`（**禁止把 python 路径当 java 用**）。
  监听 :8080。Flyway V1~V6 已落库。
- 联调代理（用户端 H5）：`C:/Users/刘尖尖/.workbuddy/binaries/python/versions/3.13.12/python.exe user-client/serve.py 5181`。
  同源静态托管 + `/api/*` 反代 :8080；SSE 走 `resp.read(1)` 逐字节。
- 登录：admin / Admin@123（ROLE_ADMIN，V2 seed）、zhangsan / User@123（ROLE_USER，V6 seed）。
  统一响应 `{code,message,data}`，JWT 鉴权；登出清 localStorage.aioa_session。

## 关键坑（已修）
- 前端 `web/apps/shell/src/api/index.ts` 的 `unwrap` 只剥 axios 信封、返回 ApiResponse 包装；store 按内层读 `result.accessToken` 得 undefined → token 存成 `"undefined"` → `/apps` 401 → 登录后卡 `/login?redirect=/home`。修复：unwrap 在 body 含 code+data 时再剥一层取 body.data。影响 login/me/apps/conversations/runs 所有 unwrapped 接口。
- 系统 `mvn` 损坏，必须用 `server/mvnw`（bundled maven 3.9.11，通过 java + plexus-classworlds 启动 launcher）。
- PG→MySQL 迁移后 `SysUser/SysTenant.status` 由 Integer 改 String（ENABLED/ACTIVE 字符串枚举）。
- **repackage 期间后端必须先停**：跑着的 JVM 占用 fat-jar 时 `mvnw package` 半路会成功 rename 出 20KB stripped-jar，
  原 fat-jar 消失，JVM 立刻 NoClassDefFoundError 崩。流程：先 `Stop-Process <pid>`（按 `netstat -ano | grep :8080`）→
  删 target → rebuild → 后台启动。
- **`@RestControllerAdvice(Exception.class)` 兜底会吞 AccessDeniedException** 成 HTTP 500：
  HandlerExceptionResolver 比 ExceptionTranslationFilter 先匹配，导致 @PreAuthorize / controller 内抛的
  AccessDeniedException 走不到 SecurityConfig 的 accessDeniedHandler。本项目 `aioa-common` 明确不引入
  spring-security 依赖，故统一改 `BizException.forbidden(...)` 由 `GlobalExceptionHandler.handleBiz` 映射为 403。
  若 common 允许 spring-security，加 `@ExceptionHandler(AccessDeniedException.class)` 是更直接的解。
- **GCM 在 headless 沙箱静默挂死**：Git Credential Manager 无缓存 GitHub 凭证时卡在 Schannel 吊销检查
  `CRYPT_E_NO_REVOCATION_CHECK`。解决：用户给 classic PAT(repo)，一次性内联 URL 推：
  `git -c http.sslVerify=false -c http.lowSpeedLimit=1 -c http.lowSpeedTime=30 push "https://<user>:<PAT>@github.com/<repo>.git" main`
  验证远端 `ls-remote` 必须带 `sslVerify=false`，否则报错信息里 URL 会被 git 自动抹凭证。PAT 用完即弃，不持久化。

## 启动与冒烟约定（2026-09-09 复核）
- 一键启动：`bash start-all.sh`（幂等，按端口探测自动 skip，日志落 `logs/`）。六端端口：
  后端 :8080 / agent :8000 / 用户端 H5 :5181（**只绑 127.0.0.1**，用 localhost 可能因解析到 ::1 不通，探活用 127.0.0.1）/
  管理端 shell :5173、工单 :5174、调度 :5175。健康：`/actuator/health`、`/health`。
- **后端 API 基址是 `/api/v1`**（不是 `/api`）。登录 `POST /api/v1/auth/login` → `data.accessToken`。
  两个易误诊点：① 少写 `v1` 段时 Security 直接返回 401 "未认证或令牌无效"，看着像密码错，实为路径/未放行；
  ② token 字段是 `accessToken`，按 `token` 取会得空串，同样误判为认证失败。
- 探测端口不要接 `| head -20`：MySQL 的 ESTABLISHED 行会占满前 20 行，把目标端口行挤掉（曾据此误判 5181 未启动）。
  用 `netstat -ano | grep LISTENING | grep ":<port> "` 精确过滤。
