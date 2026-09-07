# AIOA 智能办公基座

> Agent-era Office Automation · 公司内部 AI OA 基座（一期 M1 骨架）
> 各后台业务系统（票务、统一调度等）统一接入后自动获得 AI agent 能力。

本仓库是唯一开工说明。架构决策以《docs/01-架构设计.md》为准，接入方式见《docs/02-子应用接入规范.md》与《docs/03-工具注册规范.md》。

## 1. 这是什么

一套"前端 + 后端 + Agent"三部分的 AI 办公基座：

- **统一工作台（Vue3 + wujie 微前端）**：各业务系统作为子应用嵌入，全局 AI 助手面板感知页面上下文，"在哪问就答哪"。
- **Java 业务后端（Spring Boot 3.3）**：认证/RBAC/会话/审批/审计，内含**中间层 `aioa-bridge`（工具注册表）**——业务系统把操作注册为标准工具，agent 经中间层鉴权后调用，新系统接入 = 注册新工具。
- **Python Agent 服务（FastAPI + LangGraph）**：主 agent 编排 + 业务域子 agent，复杂任务自动拆解分派；高风险写操作挂起等待人工审批（HITL）。
- **统一模型网关**：云端大模型 API 与私有化模型（vLLM/Ollama）双模式，配置切换不改代码。
- **基座不存业务数据**：业务真值永远在各业务系统；基座只存账号权限、会话、配置、知识库索引与审计日志。

## 2. 仓库结构

```
aioa/
├── docs/                 # 架构设计 / 接入规范 / 接口契约 / 部署手册
├── deploy/               # docker-compose + nginx + Dockerfile + .env.example
├── web/                  # pnpm workspace
│   ├── apps/shell/           # 主应用：工作台 + AI 助手面板（Vue3 + Element Plus）
│   ├── apps/demo-ticket/     # 示例子应用：票务（wujie 接入）
│   ├── apps/demo-dispatch/   # 示例子应用：调度（iframe 模拟遗留系统）
│   └── packages/aioa-sdk/    # 子应用接入 SDK
├── server/               # Java（Maven 多模块）
│   ├── aioa-common/          # 统一响应/异常/工具
│   ├── aioa-security/        # JWT + RBAC
│   ├── aioa-bridge/          # ★ 中间层：工具注册表 + 工具网关（M2 完整，M1 骨架）
│   ├── aioa-tool-sdk/        # ★ 注解式工具 SDK（给业务系统用，M2）
│   ├── aioa-chat/            # 会话 / runs / SSE 中转
│   ├── aioa-admin/           # 用户/角色/权限/应用注册/审计
│   └── aioa-boot/            # 启动模块 + Flyway 迁移
├── agent/                # Python（FastAPI）
│   └── app/                  # core/（runtime 门面、graph、事件协议）+ model_gateway/ + tools/
└── tools/                # 工具声明 YAML 样例（M2）
```

## 3. 快速启动

### 3.1 一键私有化部署（Docker Compose）

```bash
cd deploy
cp .env.example .env        # 按需修改：模型 API Key、JWT 密钥等
docker compose up -d        # 全部服务：minio/server/agent/web/nginx（MySQL/Redis 已迁至远程 192.168.31.129，不在此托管）
docker compose ps           # 健康检查应全绿
```

> 数据库与 Redis 已迁至远程主机 **192.168.31.129**（MySQL 8 + Redis 7，账号 `root / yjiud`），
> `server`/`agent` 通过 `SPRING_DATASOURCE_*` / `SPRING_DATA_REDIS_HOST` 直连，compose 不再起本地库。
> 若需本地调试数据库，可取消 `deploy/docker-compose.yml` 中 `mysql` 服务的注释。

访问 `http://localhost`（nginx 统一入口）。默认账号：`admin / Admin@123`（仅开发默认值，生产必须修改）。

可选 profile：

```bash
docker compose --profile model up -d   # 附加本地模型（vllm / ollama）
docker compose --profile ops up -d     # 附加观测（prometheus / grafana / loki）
```

### 3.2 本地开发

| 模块 | 命令 | 端口 |
|---|---|---|
| 前端主应用 | `cd web && pnpm install && pnpm --filter shell dev` | 5173 |
| 示例：票务 | `pnpm --filter demo-ticket dev` | 5174 |
| 示例：调度 | `pnpm --filter demo-dispatch dev` | 5175 |
| Java 后端 | `cd server && ../.tools/mvnw.sh spring-boot:run -pl aioa-boot`（需可达 192.168.31.129 的 MySQL/Redis） | 8080 |
| Python agent | `cd agent && uvicorn app.main:app --reload --port 8000` | 8000 |

> 本机无 Docker 时，最小数据依赖为远程 **MySQL 8**（192.168.31.129:3306，库 `aioa`，账号 `root/yjiud`）与 **Redis 7**（192.168.31.129:6379）；应用通过 `application.yml` 默认连接，无需本地起库。

## 4. 分支与提交规范

```
main        # 受保护：可运行、可演示的稳定版，只接受 PR
develop     # 日常集成主干
feat/*      # 功能分支，如 feat/m1-shell-skeleton
fix/*       # 修复分支
```

- Commit 格式：`[模块] 动作 描述`，如 `[bridge] feat 工具注册表数据模型`
- 每完成一个里程碑按《docs/01-架构设计.md》第 10 节门禁逐条验收。

## 5. 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M1 骨架 | 前端嵌入集成（wujie）、登录、回声对话全链路、Compose 一键部署 | **已完成** |
| M2 核心链路 | 工具注册表 + 主/子 agent 编排 + 真实模型 + mock 业务系统 | 待启动 |
| M3 权限与 HITL | RBAC 完整 + 高风险操作人工审批 + 审计哈希链 | 待启动 |
| M4 知识库与开放 | RAG 引用溯源 + 附件解析 + 模型双模式验证 + 开放 API | 待启动 |

## 6. 参考文档

- 《docs/01-架构设计.md》：总体架构、技术选型、数据模型、API、风险
- 《docs/02-子应用接入规范.md》：业务系统前端如何嵌入工作台
- 《docs/03-工具注册规范.md》：业务系统如何把操作注册为 agent 工具
- 《docs/05-部署手册.md》：私有化部署与运维
- 《docs/06-交接包借鉴说明.md》：与"AIOA 五域 41 实体"蓝图的借鉴/裁剪对照
