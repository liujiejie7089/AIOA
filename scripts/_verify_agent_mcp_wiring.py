"""MCP 连接器接入 LangGraph 的接线哨兵（不需要 Java 后端）。

契约：docs/59 §10（AIOS_MCP_HUB 默认 false、`mcp__<serverCode>__<toolName>` 前缀、
判据 4「失败不静默」）。本脚本用**同进程**起一个本地 FastMCP echo 服务，并**注入** manifest
绕过不可达的 Java 后端，逐条证明接线正确，且具备分辨力。

运行：D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_agent_mcp_wiring.py
依赖：mcp / langchain-mcp-adapters（已装），以及 aios_ai（脚本自动把 agent/ 加进 sys.path）。

任一断言 FAIL ⇒ sys.exit(1)。全部 PASS ⇒ 退出码 0。
"""
from __future__ import annotations

import os as _os
# 本机存在 http_proxy，httpx 默认 trust_env=True 会把 127.0.0.1 也代理出去（实测表现为 502），
# 哨兵统一在进程内关掉代理，保证可复跑（不依赖外部 shell 环境）。
_os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
_os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import asyncio
import os
import socket
import sys
import threading
import time

# 让 `import aios_ai` 可用（脚本位于 scripts/，运行时不自动带 agent/ 到 sys.path）。
_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent"))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from aios_ai.config import settings  # noqa: E402
from aios_ai.tools.client import ToolClient  # noqa: E402

ECHO_HOST = "127.0.0.1"
ECHO_PORT = 8098
ECHO_URL = f"http://{ECHO_HOST}:{ECHO_PORT}/mcp"
# 故意不可达的 Java 后端（manifest / 网关都不会真连，仅用于负向与降级判据）。
DEAD_JAVA = "http://127.0.0.1:1"
TOKEN = "test-token"

# 注入用 manifest：键名与契约 §10.3 一致。
MANIFEST = [{
    "code": "echo",
    "name": "Echo",
    "transport": "streamable_http",
    "url": ECHO_URL,
    "toolCount": 1,
}]


# --------------------------------------------------------------------------- echo server
mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> str:
    """回显输入文本（仅用于接线自测）。"""
    return "echo:" + text


def _wait_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _start_echo_server():
    app = mcp.streamable_http_app()  # 端点默认挂在 /mcp
    config = uvicorn.Config(app, host=ECHO_HOST, port=ECHO_PORT,
                            log_level="warning")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    return srv


# --------------------------------------------------------------------------- 断言辅助
_FAILED = []


def check(label: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}: {detail}")
    if not cond:
        _FAILED.append(label)


# --------------------------------------------------------------------------- 主流程
async def main() -> int:
    srv = _start_echo_server()
    if not _wait_port(ECHO_HOST, ECHO_PORT):
        print("[FAIL] echo server 未能在超时内监听，终止")
        srv.should_exit = True
        return 1

    # W1：开关关闭 ⇒ 返回 [] 且 mcp_error is None（与改造前逐字节一致）。
    settings.mcp_hub_enabled = False
    tc = ToolClient(DEAD_JAVA, TOKEN, mcp_manifest=MANIFEST)
    tools_w1 = await tc.list_mcp_tools()
    check("W1", tools_w1 == [] and tc.mcp_error is None,
          f"tools={tools_w1!r}, mcp_error={tc.mcp_error!r}")

    # W2：开启 + 注入 manifest ⇒ 工具名恰好 mcp__echo__echo，parameters.properties 含 text。
    settings.mcp_hub_enabled = True
    tc2 = ToolClient(DEAD_JAVA, TOKEN, mcp_manifest=MANIFEST)
    tools_w2 = await tc2.list_mcp_tools()
    names = [t.get("function", {}).get("name") for t in tools_w2]
    has_text = any(
        "text" in (t.get("function", {}).get("parameters", {}).get("properties", {}))
        for t in tools_w2
    )
    check("W2", names == ["mcp__echo__echo"] and has_text,
          f"names={names!r}, has_text={has_text}")

    # W3：invoke(mcp__echo__echo, {text:"hi"}) ⇒ ok=True 且 data 含 "echo:hi"。
    outcome = await tc2.invoke("mcp__echo__echo", {"text": "hi"})
    data_str = outcome.data if isinstance(outcome.data, str) else repr(outcome.data)
    check("W3", outcome.ok and "echo:hi" in data_str,
          f"ok={outcome.ok}, data={data_str!r}, error={outcome.error!r}")

    # W4：hub 指向死端口 ⇒ 返回 []、mcp_error 非空、不抛异常。
    settings.mcp_hub_enabled = True
    tc4 = ToolClient(DEAD_JAVA, TOKEN)  # 无注入 manifest ⇒ 真的去拉 dead 端口的 manifest
    try:
        tools_w4 = await tc4.list_mcp_tools()
        raised = False
    except Exception as exc:  # noqa: BLE001
        tools_w4 = []
        raised = True
        print(f"   W4 意外抛异常: {exc!r}")
    check("W4", (not raised) and tools_w4 == [] and bool(tc4.mcp_error),
          f"tools={tools_w4!r}, mcp_error={tc4.mcp_error!r}")

    # W5：未知 MCP 工具名 ⇒ ok=False 且 error 含「不存在或服务器未就绪」。
    outcome5 = await tc2.invoke("mcp__echo__nope", {"text": "x"})
    check("W5", (not outcome5.ok) and "不存在或服务器未就绪" in (outcome5.error or ""),
          f"ok={outcome5.ok}, error={outcome5.error!r}")

    # W6（负向对照）：带 mcp__ 前缀但映射为空时，不能回落到 Java 网关。
    # 计数 httpx.AsyncClient 的实例化（Java 网关与 manifest 都会用它），断言 invoke 全程 0 次。
    java_calls = []

    class _CountingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            java_calls.append(1)

    orig = httpx.AsyncClient
    httpx.AsyncClient = _CountingAsyncClient
    try:
        # 关闭 hub ⇒ list_mcp_tools 直接返回 []（不连 Java、不拉 manifest），映射为空。
        settings.mcp_hub_enabled = False
        tc6 = ToolClient(DEAD_JAVA, TOKEN, mcp_manifest=[])  # 空 manifest：映射必空
        await tc6.list_mcp_tools()
        outcome6 = await tc6.invoke("mcp__foo__bar", {})
    finally:
        httpx.AsyncClient = orig
    check("W6", (not outcome6.ok) and "不存在或服务器未就绪" in (outcome6.error or "")
          and len(java_calls) == 0,
          f"ok={outcome6.ok}, error={outcome6.error!r}, java_calls={len(java_calls)}")

    srv.should_exit = True
    return 1 if _FAILED else 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    if rc == 0:
        print("\nALL PASS ✅ (退出码 0)")
    else:
        print(f"\n存在 FAIL ❌: {_FAILED} (退出码 1)")
    sys.exit(rc)
