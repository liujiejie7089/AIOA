# web/ 前端工作区

pnpm workspace，包含 1 个公共库 + 3 个应用。

| 路径 | 包名 | 说明 | 端口 |
|---|---|---|---|
| `packages/aioa-sdk` | `@aioa/sdk` | 子应用接入 SDK（框架无关，postMessage 桥） | - |
| `apps/shell` | `shell` | 工作台主应用（微前端宿主 + 全局 AI 助手） | 5173 |
| `apps/demo-ticket` | `demo-ticket` | 票务示例子应用（wujie 接入，已接 SDK） | 5174 |
| `apps/demo-dispatch` | `demo-dispatch` | 调度示例子应用（iframe 接入，未接 SDK） | 5175 |

## 快速开始

```bash
pnpm install          # 安装依赖
pnpm -r build         # 全量构建（拓扑序：SDK → 应用）
pnpm dev              # 并行启动三个 dev server
```

> 构建子应用前会先构建 `@aioa/sdk`（workspace 依赖，pnpm 自动按拓扑序执行）。

## 后端依赖

shell 的 `/api` 请求通过 Vite devServer 代理到 `http://localhost:8080`，
需要先启动 aioa-server，否则登录、应用列表、会话等接口会失败（页面按空态展示）。
