# mcp-hub

MCP（Model Context Protocol）网关，位于 **agent（LangGraph）↔ Java 后端** 之间。

## 为什么存在

Java 后端是全系统唯一能解密用户凭据的地方；agent 需要「按 MCP 协议」发现并调用工具。
hub 夹在中间，**无状态、不落盘、不读数据库、不持有任何密钥**，只做协议转换与转发。

两条链路：

1. **对内（agent → hub）**：每个内置服务器一个 MCP 端点
   `http://<hub>:<port>/mcp/<serverCode>`，Streamable HTTP 传输。
   agent 用官方 MCP 客户端连上来，`tools/list` 拿工具目录，`tools/call` 真正执行。
2. **对外（Java → hub 探测）**：`POST /internal/mcp/probe`，Java 在你这里做「信任前存活探测」，
   判断某 MCP 服务器是否活着并取出工具目录。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康探测，返回 `{"ok":true,"servers":{...}}` |
| POST | `/internal/mcp/probe` | Java 信任前探测：`{transport, code|url|command...}` → `{ok, tools, error}` |
| * | `/mcp/<serverCode>` | Streamable HTTP（MCP 协议；`Authorization` 透传给 Java） |

## 工具怎么执行

内置服务器的工具逻辑**不在 Python 里实现**，转发给 Java：

```
POST {AIOS_SERVER_BASE_URL}/api/v1/mcp/builtin/{serverCode}/call
Headers: Authorization: <入站 MCP 请求带的用户 token，原样透传>
Body:   {"tool": "<工具名>", "arguments": {...}}
Resp:   {"data": {"ok": true, "data": <结果>}}
        或 {"data": {"ok": false, "error": "..."}}
```

- `Authorization` 从**入站 MCP 请求**取（`ctx.request_context.request.headers`），原样透传。
- 用 `httpx` 转发，超时 20s。Java 返回 `ok=false` ⇒ 返回 `isError=True` 的 `CallToolResult`。
- 目标地址来自环境变量 `AIOS_SERVER_BASE_URL`，本地默认 `http://127.0.0.1:8080`。
- **绝不**把 Authorization、收件人、正文写进日志。日志只记 `server/tool/ok/duration_ms`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `MCP_HUB_PORT` | `8099` | hub 监听端口 |
| `MCP_HUB_HOST` | `0.0.0.0` | hub 监听地址 |
| `AIOS_SERVER_BASE_URL` | `http://127.0.0.1:8080` | Java 后端地址（工具转发目标） |

## 启动

```bash
# 用 agent/.venv 的解释器（已装 mcp==1.30.0 / httpx / uvicorn / starlette）
D:/aios/agent/.venv/Scripts/python.exe D:/aios/mcp-hub/run.py
```

## 为什么无状态

hub 进程内存在启动时只装载**工具规格**（`mcp_hub/specs.py`，与 Java V97 种子逐字对齐）。
任何用户请求都不写库、不落盘、不缓存凭据；凭据只在单次请求内存里随 `Authorization` 头透传。
这样 hub 可以随意水平扩展、重启无副作用，且审计/鉴权完全由 Java 承担。
