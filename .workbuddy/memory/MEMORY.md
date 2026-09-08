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
- 后端：`cd server && .tools/mvnw.sh -pl aioa-boot -am clean package -DskipTests` → `java -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar`（启动加 `-Dspring.flyway.validate-on-migrate=false`，因 V1 checksum 已变）。监听 :8080。
- 前端：根 `web/` 下 `pnpm -r --parallel dev`；shell :5173 / demo-ticket :5174 / demo-dispatch :5175。需 `NO_PROXY=localhost,127.0.0.1` 绕过环境 HTTP 代理。
- 登录：admin / Admin@123（Flyway V2 seed）。统一响应 `{code,message,data}`，JWT 鉴权。

## 关键坑（已修）
- 前端 `web/apps/shell/src/api/index.ts` 的 `unwrap` 只剥 axios 信封、返回 ApiResponse 包装；store 按内层读 `result.accessToken` 得 undefined → token 存成 `"undefined"` → `/apps` 401 → 登录后卡 `/login?redirect=/home`。修复：unwrap 在 body 含 code+data 时再剥一层取 body.data。影响 login/me/apps/conversations/runs 所有 unwrapped 接口。
- 系统 `mvn` 损坏，必须用 `server/.tools/mvnw.sh`（bundled maven 3.9.9）。
- PG→MySQL 迁移后 `SysUser/SysTenant.status` 由 Integer 改 String（ENABLED/ACTIVE 字符串枚举）。
