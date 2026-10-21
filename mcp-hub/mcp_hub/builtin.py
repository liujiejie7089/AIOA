# -*- coding: utf-8 -*-
"""
为每个内置服务器构建一个独立的 FastMCP 实例，工具按 specs 动态注册，
调用时把请求原样转发给 Java 的 /api/v1/mcp/builtin/{code}/call。

关键纪律：
- Authorization 从入站 MCP 请求里取（ctx.request_context.request.headers），原样透传给 Java；
  绝不复述、不记录。
- 不读数据库、不落盘、不持有任何密钥。进程内存里只有工具规格。
- Java 返回 ok=false ⇒ 返回 isError=True 的 CallToolResult，绝不抛未捕获异常、绝不返回空串当成功。
"""

import inspect
import json
import logging
import os
import time

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import specs

logger = logging.getLogger("mcp_hub")

# 参数名 -> Python 类型（仅用于 FastMCP 推断 JSON Schema 的类型）
_TYPE_BY_PARAM = {
    "folder": str, "query": str, "to": str, "subject": str, "body": str,
    "cc": str, "touser": str, "content": str, "requestId": str,
    "limit": int, "uid": int, "draftId": int, "unreadOnly": bool,
}

# 可选参数的默认值（有默认值 ⇒ 不在 required 里）。顺序与 V97 种子描述一致。
_DEFAULTS = {
    "list_messages": {"folder": "INBOX", "limit": 10, "unreadOnly": False},
    "read_message": {"folder": "INBOX"},
    "search_messages": {"folder": "INBOX", "limit": 10},
    "create_draft": {"cc": None},
}

# 各工具参数顺序（必须与 V97 种子 properties 顺序一致）
_PROPS_ORDER = {
    "list_folders": [],
    "list_messages": ["folder", "limit", "unreadOnly"],
    "read_message": ["uid", "folder"],
    "search_messages": ["query", "folder", "limit"],
    "create_draft": ["to", "subject", "body", "cc"],
    "send_draft": ["draftId", "requestId"],
    "check_connection": [],
    "send_text_message": ["touser", "content"],
}


def _base_url() -> str:
    return os.environ.get("AIOS_SERVER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _get_auth_header(ctx: Context) -> "str | None":
    """从入站 MCP 请求取 Authorization，原样透传（只在缺 `Bearer ` 前缀时补上）。失败返回 None。

    补前缀不是洁癖：MCP 客户端可能把「已拼好的凭据」塞进 header（如直接把 env 里的
    `Bearer xxx` 传进来），原样透传会变成 `Bearer Bearer xxx`，Java 的 JWT 过滤器
    只会静默 401 —— 现象是「工具调了但全部失败」，没有更具体的报错。
    """
    try:
        request = ctx.request_context.request
        auth = request.headers.get("authorization")
        if auth and not auth.lower().startswith("bearer "):
            return "Bearer " + auth
        return auth
    except Exception:
        return None


async def _dispatch(server_code: str, tool_name: str, arguments: dict, ctx: Context) -> CallToolResult:
    auth = _get_auth_header(ctx)
    url = f"{_base_url()}/api/v1/mcp/builtin/{server_code}/call"
    headers = {}
    if auth:
        headers["Authorization"] = auth

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json={"tool": tool_name, "arguments": arguments})
        duration_ms = int((time.time() - t0) * 1000)

        try:
            body = resp.json()
        except Exception:
            logger.info("%s/%s ok=false %dms", server_code, tool_name, duration_ms)
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=f"后端返回无法解析（HTTP {resp.status_code}），连接器本轮不可用")],
            )

        inner = body.get("data", {}) if isinstance(body, dict) else {}
        if inner.get("ok") is True:
            logger.info("%s/%s ok=true %dms", server_code, tool_name, duration_ms)
            data = inner.get("data")
            text = json.dumps(data, ensure_ascii=False, default=str)
            return CallToolResult(content=[TextContent(type="text", text=text)])
        else:
            logger.info("%s/%s ok=false %dms", server_code, tool_name, duration_ms)
            err = inner.get("error") or f"HTTP {resp.status_code}"
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=f"调用失败：{err}")],
            )
    except httpx.HTTPError as e:
        duration_ms = int((time.time() - t0) * 1000)
        logger.info("%s/%s ok=false %dms", server_code, tool_name, duration_ms)
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text=f"后端不可达：{type(e).__name__}")],
        )


def _make_tool_fn(server_code: str, tool_name: str, props: list, defaults: dict, read_only: bool):
    async def _fn(ctx: Context, **kwargs):
        return await _dispatch(server_code, tool_name, kwargs, ctx)

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for pname in props:
        annotation = _TYPE_BY_PARAM.get(pname, str)
        if pname in defaults:
            params.append(
                inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, default=defaults[pname], annotation=annotation)
            )
        else:
            params.append(
                inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
            )
    _fn.__name__ = f"{server_code}__{tool_name}"
    _fn.__signature__ = inspect.Signature(params)
    _fn.__doc__ = f"{server_code}.{tool_name}"
    return _fn


def build_servers() -> "dict[str, FastMCP]":
    """为每个内置服务器构建一个 FastMCP 实例（streamable_http_path='/'，便于父 ASGI 改写路径）。"""
    servers: "dict[str, FastMCP]" = {}
    for code, spec in specs.BUILTIN_SERVERS.items():
        mcp = FastMCP(code, streamable_http_path="/")
        for tool in spec["tools"]:
            name = tool["name"]
            fn = _make_tool_fn(
                code, name,
                props=_PROPS_ORDER.get(name, list(tool["input_schema"].get("properties", {}).keys())),
                defaults=_DEFAULTS.get(name, {}),
                read_only=tool["read_only"],
            )
            mcp.add_tool(
                fn,
                name=name,
                description=tool["description"],
                annotations=ToolAnnotations(read_only_hint=tool["read_only"]),
            )
        servers[code] = mcp
    return servers


# 模块导入时即构建（供 app.py / run.py 使用）
SERVERS = build_servers()

# 端点信息（run.py 启动横幅、/health 用）
SERVER_INFO = {code: specs.tool_count(code) for code in specs.BUILTIN_SERVERS}
