# -*- coding: utf-8 -*-
"""
POST /internal/mcp/probe —— Java 侧的「信任前存活探测」入口（普通 JSON，非 MCP 协议）。

三种 transport：
- builtin：直接读本地 specs（hub 内存），不连外网，不连 Java。
- streamable_http：真连一次（initialize + tools/list），把工具目录转成标准结构。
- stdio：用 mcp SDK 起子进程探测，15s 超时强制 kill（防僵尸）。

纪律：
- 失败**绝不**返回 500，永远 {ok:false, tools:[], error:"可读中文原因"}（HTTP 仍 200）。
- 原因截断 300 字符，**不含 headers 内容**（避免泄露鉴权信息）。
- 只探测，不落盘、不写库、不持有密钥。
"""

import asyncio
import json
import logging

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from . import specs

logger = logging.getLogger("mcp_hub")


async def _read_body(receive) -> bytes:
    body = b""
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        body += message.get("body", b"")
        more = message.get("more_body", False)
    return body


async def _send_json(send, status: int, payload: dict):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": data})


def _tool_entry(tool) -> dict:
    annotations = getattr(tool, "annotations", None)
    read_only = getattr(annotations, "read_only_hint", False) if annotations else False
    return {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "inputSchema": getattr(tool, "inputSchema", {}) or {},
        "readOnly": bool(read_only),
    }


def _truncate(reason: str, limit: int = 300) -> str:
    reason = reason or ""
    if len(reason) > limit:
        reason = reason[:limit] + "…"
    return reason


async def _probe_builtin(req: dict, send):
    code = req.get("code")
    if code in specs.BUILTIN_SERVERS:
        tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["input_schema"],
                "readOnly": t["read_only"],
            }
            for t in specs.BUILTIN_SERVERS[code]["tools"]
        ]
        await _send_json(send, 200, {"ok": True, "tools": tools, "error": None})
    else:
        await _send_json(send, 200, {"ok": False, "tools": [], "error": f"未知内置服务器：{code}"})


async def _probe_streamable(req: dict, send):
    url = req.get("url")
    headers = req.get("headers") or {}
    if not url:
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "缺少 url 参数"})
        return
    try:
        async with streamablehttp_client(url=url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=20)
                result = await asyncio.wait_for(session.list_tools(), timeout=20)
                tools = [_tool_entry(t) for t in result.tools]
        await _send_json(send, 200, {"ok": True, "tools": tools, "error": None})
    except asyncio.TimeoutError:
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "streamable_http 探测超时（20s）"})
    except Exception as e:  # noqa: BLE001 —— 探测失败必须转成 ok:false，绝不 500
        await _send_json(send, 200, {"ok": False, "tools": [], "error": f"探测失败：{_truncate(str(e))}"})


async def _probe_stdio(req: dict, send):
    command = req.get("command")
    args = req.get("args") or []
    env = req.get("env") or None
    if not command:
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "缺少 command 参数"})
        return
    try:
        params = StdioServerParameters(command=command, args=list(args), env=env)
        async with asyncio.timeout(15):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = [_tool_entry(t) for t in result.tools]
        await _send_json(send, 200, {"ok": True, "tools": tools, "error": None})
    except asyncio.TimeoutError:
        # asyncio.timeout 退出上下文会 kill 子进程，避免僵尸
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "stdio 探测超时（15s），已终止子进程"})
    except Exception as e:  # noqa: BLE001
        await _send_json(send, 200, {"ok": False, "tools": [], "error": f"探测失败：{_truncate(str(e))}"})


async def handle(scope, receive, send):
    try:
        body = await _read_body(receive)
    except Exception:  # noqa: BLE001
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "读取请求体失败"})
        return

    try:
        req = json.loads(body) if body else {}
    except Exception:
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "请求体不是合法 JSON"})
        return

    if not isinstance(req, dict):
        await _send_json(send, 200, {"ok": False, "tools": [], "error": "请求体必须是 JSON 对象"})
        return

    transport = req.get("transport")
    if transport == "builtin":
        await _probe_builtin(req, send)
    elif transport == "streamable_http":
        await _probe_streamable(req, send)
    elif transport == "stdio":
        await _probe_stdio(req, send)
    else:
        await _send_json(send, 200, {"ok": False, "tools": [], "error": f"未知 transport：{transport}"})
