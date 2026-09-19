# AIOA 智能办公基座

> Agent-era Office Automation · 地级市 AI 公共服务平台基座
> 各业务系统（票务、调度、OA…）接入后自动获得 AI 能力，业务真值仍留在各业务系统。

本仓库是唯一开工说明。架构决策以《docs/01-架构设计.md》为准，架构决策的过程记录见
`docs/adr/`；接入方式见《docs/02-子应用接入规范.md》《docs/03-工具注册规范.md》。

## 1. 它现在是什么状态

不是骨架：四端可跑、60 个 Flyway 迁移、30 个端到端套件全绿。

- **统一工作台（Vue3 + wujie 微前端）**：业务系统作为子应用嵌入，全局 AI 助手感知
  「用户在哪一页、选中了哪个实体」，在哪问就答哪。
- **Java 业务后端（Spring Boot 3.3 / JDK 21，10 个 Maven 模块）**：认证 / RBAC /
  多租户组织域 / 审批引擎 / 会话 / 计费 / 审计。
- **Python Agent 服务（FastAPI）**：模型网关（多 provider）、真实流式推理、工具调用
  循环、**多任务协同编排器**（依赖分层 + 同层并发 + 依赖失败跳过）。
- **中间层 `aioa-bridge`**：工具注册表 + 定义驱动的调用网关（权限 / 幂等 / HITL /
  审计），业务系统把操作注册为标准工具，新系统接入 = 注册新工具。
- **HITL（人机协同）**：高风险工具调用挂起 → 走审批流 → 终态回调自动恢复执行。

## 2. 仓库结构

```
aioa/
├── docs/                 # 架构设计 / 接入规范 / 接口契约 / 部署手册 / ADR
│   └── adr/              # 架构决策记录（为什么这么做，而不是只写做了什么）
├── deploy/               # docker-compose + nginx + Dockerfile + k8s 清单
├── web/                  # pnpm workspace（前端三应用 + 接入 SDK）
│   ├── apps/shell/           # 工作台主应用（Vue3 + Element Plus）
│   ├── apps/demo-ticket/     # 示例子应用：票务（wujie 接入）
│   ├── apps/demo-dispatch/   # 示例子应用：调度（iframe 模拟遗留系统）
│   └── packages/aioa-sdk/    # 子应用接入 SDK（postMessage 桥接）
├── server/               # Java（Maven 多模块）
│   ├── aioa-common/          # 统一响应 / 异常 / 上下文
│   ├── aioa-security/        # JWT + RBAC + 服务间令牌
│   ├── aioa-resource/        # 专家 / 技能 / 知识库 / 额度 / 账本 / 工具网关
│   ├── aioa-org/             # 多租户组织域 + 审批引擎（加签 / 子流程 / 版本）
│   ├── aioa-chat/            # 会话 / runs / SSE 中转 / 多任务计划中转
│   ├── aioa-admin/           # 用户 / 角色 / 权限 / 应用注册 / 审计
│   ├── aioa-bridge/          # ★ 工具注册表 + 定义驱动调用网关
│   ├── aioa-tool-sdk/        # ★ 注解式工具 SDK（@AioaTool / @AioaToolParam）
│   ├── aioa-gitee/           # 代码托管联动（Gitee / Gitea 双实现）
│   └── aioa-boot/            # 启动模块 + Flyway 迁移（V1..V60）
├── agent/                # Python（FastAPI）
│   └── app/core/             # runtime 门面 / agent_runtime / orchestrator / multi_task
├── user-client/          # 用户端单文件 H5
├── scripts/              # 端到端验收套件（30 个，见第 5 节）
└── start-all.sh          # 一键起全部服务（幂等，按端口探测）
```

## 3. 快速启动

### 3.1 一键启动（本地开发，推荐）

```bash
bash start-all.sh      # 幂等：已运行的服务自动跳过，日志写入 logs/
```

| 服务 | 地址 | 说明 |
|---|---|---|
| 用户端 H5 | http://127.0.0.1:5181 | 只绑 127.0.0.1 |
| 管理端工作台 | http://localhost:5173 | |
| 工单应用 | http://localhost:5174 | 子应用，可独立打开 |
| 调度应用 | http://localhost:5175 | 子应用，可独立打开 |
| Java 后端 | http://localhost:8080 | 健康：`/actuator/health` |
| Agent 服务 | http://localhost:8000 | 健康：`/health` |

### 3.2 各模块单独启动

| 模块 | 命令 |
|---|---|
| Java 后端 | `cd server && bash mvnw -DskipTests -q clean package` 然后 `java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar` |
| Python agent | `cd agent && uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| 前端 | `cd web && pnpm install && pnpm -r --parallel dev` |
| 用户端 H5 | `cd user-client && python serve.py` |

> **重打包前必须先停掉 8080**：否则 fat-jar 被占用，会被 rename 成 20KB 的 stripped-jar，
> 运行中的 JVM 随即 `NoClassDefFoundError` 崩溃。系统 `mvn` 不可用，只能用 `./mvnw`；
> 清理用 `mvnw clean`，不要 `rm -rf target`。

### 3.3 容器部署

```bash
cd deploy
cp .env.example .env      # 模型 API Key、JWT 密钥等
docker compose up -d
docker compose --profile model up -d   # 可选：附加本地模型（vllm / ollama）
docker compose --profile ops   up -d   # 可选：附加观测（prometheus / grafana / loki）
```

Kubernetes 清单见 `deploy/k8s/`（未经真机集群验证，按自身环境调整存储与 ingress）。

## 4. 演示账号

| 角色 | 账号 | 口令 |
|---|---|---|
| 平台管理员 | `admin` | `Admin@123` |
| 租户侧（全租户通用） | `dsj_admin` / `fagai_admin` / `fagai_liu` / `fagai_li` / `zhangsan` | `User@123` |

登录需带租户名时填：`某某市某某区大数据管理局`。开发与演示口令的归一化说明见
《docs/22-管理端登录口径与演示口令归一化.md》。

## 5. 测试

**判据是端到端套件，不是单测覆盖率。** Java 侧几乎没有单测，Python 侧有 pytest，
真正拦回归的是 `scripts/` 下 30 个套件：

```bash
# Python agent 单测（79 条）
cd agent && python -m pytest -q

# 全链路回归（每次收口必跑，155 条）
python scripts/e2e_full_system.py

# 分模块套件（按需）
python scripts/e2e_v59_bridge_tool_invoke.py    # 批次1：工具网关（52）
python scripts/e2e_v59b_tool_sdk.py             # 批次2：注解式工具 SDK（45）
python scripts/e2e_v60_workflow_ext.py          # 批次3：加签/子流程/版本对比（62）
python scripts/e2e_agent_orchestrator.py        # 批次4：多任务协同（33）
python scripts/e2e_sdk_token_origin.py          # 批次5：SDK token 与 origin 白名单（14，Playwright）
```

前端改动后必须跑类型检查（少 import 一个常量在页面上表现为「整页空白」）：

```bash
cd web && pnpm -r typecheck
```

> 套件文件被 gitignore，不入库。**跑之前先 `ls scripts/` 确认还在**，别照抄文档里的名字。

### 写新套件的几条纪律

- 禁止断言「固定页长 / 绝对条数」：用 `len(items) == min(total, size)`。
- 审批用例先确认申请人所在部门的负责人，用错审批人会表现为 `decided=0`。
- 配额类套件必须自治（自己把状态顶到位），撤销链路用不占额度的假种。
- **绝不为转绿而放宽断言**：先分清「真回归」「环境漂移」「历史遗留数据」，
  可回填的数据用 Flyway 回填修，断言原样保留。

## 6. 分支与提交规范

```
main        # 受保护：可运行、可演示的稳定版，只接受 PR
develop     # 日常集成主干
feat/*      # 功能分支
fix/*       # 修复分支
```

- Commit 格式：`[模块] 动作 描述`，如 `[bridge] feat 工具注册表数据模型`
- 重构后按《docs/01-架构设计.md》的门禁逐条验收。

## 7. 参考文档

| 文档 | 内容 |
|---|---|
| docs/01-架构设计.md | 总体架构、技术选型、数据模型、风险 |
| docs/02-子应用接入规范.md | 业务系统前端如何嵌入工作台 |
| docs/03-工具注册规范.md | 业务系统如何把操作注册为 agent 工具 |
| docs/04-接口契约/ | 内部接口契约（OpenAPI） |
| docs/05-部署手册.md | 私有化部署与运维 |
| docs/16-组织与员工作用域模型.md | 多租户组织域与作用域 |
| docs/19-七项优先事项覆盖度审计与补齐计划.md | 优先事项进度（**进度只回写此文**） |
| docs/20-系统整体总结汇报与全链路端到端测试报告.md | 整体总结与测试报告 |
| docs/31-模型网关规范.md | 模型 provider、配置、用量计量 |
| docs/adr/ | 架构决策记录（ADR） |
