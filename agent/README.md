# aioa-agent（M1 骨架；M2 真实推理 · DeepSeek Harness 已就绪）

Python agent 服务（智能体运行层 / AI 大脑）。M1 打通链路：`POST /internal/v1/runs` 接收 `RunRequest`，以 SSE 逐字符回显输入文本。
M2 已接入真实 LLM（DeepSeek / 通义 / 本地 vLLM / Ollama，均 OpenAI 兼容）：配置对应 `DEEPSEEK_API_KEY` 等密钥并把 `MODEL_DEFAULT` 指向该 provider，即切换为流式推理；事件序列与 M1 完全一致，无需前端改动。

## 环境

```bash
# 建 venv（仅首次）
"C:/Users/刘尖尖/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m venv "C:/Users/刘尖尖/WorkBuddy/aioa/agent/.venv"

# 装依赖
agent/.venv/Scripts/python.exe -m pip install -e agent           # 或在 agent/ 下：python -m pip install fastapi "uvicorn[standard]" pydantic pyyaml httpx pytest
```

## 启动

```bash
cd agent
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 自测

```bash
# 单元测试（仓库根目录执行）
agent/.venv/Scripts/python.exe -m pytest agent/tests -q
```

冒烟：

```bash
curl -s http://127.0.0.1:8000/health                     # {"status":"UP"}
curl -N -X POST http://127.0.0.1:8000/internal/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id":"run_1","conversation_id":10001,"text":"你好","context":{"appCode":"ticket","page":"ticket-list"},"user_context":{"user_id":1,"tenant_id":0,"roles":["ROLE_ADMIN"],"trace_id":"t-1"}}'
```

帧格式：`id: <seq>` / `event: <type>` / `data: <json>`，seq 从 1 递增；
事件序列 `run.started → message.delta×N → message.completed → run.completed`。

## 环境变量

敏感凭据推荐写在 `agent/.env`（模板见 `.env.example`，已被 gitignore；已有环境变量优先）。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SERVICE_JWT_SECRET` | 空 | 服务 JWT 密钥（M1 不校验，M2 启用） |
| `AIOA_SERVER_BASE_URL` | `http://aioa-server:8080` | Java 后端回调地址 |
| `MODEL_DEFAULT` | `echo` | 默认 provider：`echo` / `deepseek` / `dashscope` / `vllm` / `ollama` |
| `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `VLLM_API_KEY` / `OLLAMA_API_KEY` | 空 | 对应 provider 的密钥（echo 无需）；只走环境变量或 `.env`，不入库不入 git |
| `{KEY}_BASE_URL` / `{KEY}_MODEL` | 内置值 | 覆盖 provider 的端点与模型名（如 `DEEPSEEK_MODEL=deepseek-chat`） |
| `PG_DSN` | 空 | 数据库（M2+ 使用，M1 不连接） |
| `HOST` / `PORT` / `LOG_LEVEL` | `0.0.0.0` / `8000` / `INFO` | 监听与日志 |

**解析与降级规则**（`app/model_gateway`）：
- 显式指定 provider 但缺 key → 保留 provider，会话流内产出干净的 `MODEL_PROVIDER_NOT_CONFIGURED` 错误事件；
- 未指定（走 `MODEL_DEFAULT`）且缺 key → 自动降级 echo，会话链路始终可用；
- 未知 ref → 回退默认并记警告。
- `run.started` 事件携带 `model` / `gateway_key`，前端据此显示真实模型名。

## 扩展点

- `app/core/runtime.py`：运行时门面，M2 换成 langgraph 实现时接口不变。
- `app/model_gateway/__init__.py`：provider 注册表与解析/降级（新增 provider 在 `_REGISTRY_SPEC` 加一行即可）。
- `app/tools/gateway_client.py`：Java 工具回调（M1 抛 `NotImplementedError("M2")`）。
