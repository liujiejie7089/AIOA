# aioa-agent（M1 骨架，回声模式）

Python agent 服务。M1 只打通链路：`POST /internal/v1/runs` 接收 `RunRequest`，以 SSE 逐字符回显输入文本。

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

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SERVICE_JWT_SECRET` | 空 | 服务 JWT 密钥（M1 不校验，M2 启用） |
| `AIOA_SERVER_BASE_URL` | `http://aioa-server:8080` | Java 后端回调地址 |
| `MODEL_DEFAULT` | `echo` | 默认模型引用，覆盖 `providers.yaml` 的 `default_chat` |
| `PG_DSN` | 空 | 数据库（M2+ 使用，M1 不连接） |
| `HOST` / `PORT` / `LOG_LEVEL` | `0.0.0.0` / `8000` / `INFO` | 监听与日志 |

## 扩展点

- `app/core/runtime.py`：运行时门面，M2 换成 langgraph 实现时接口不变。
- `app/model_gateway/gateway.py` + `providers.yaml`：模型解析与云端/本地双模式切换。
- `app/tools/gateway_client.py`：Java 工具回调（M1 抛 `NotImplementedError("M2")`）。
