# -*- coding: utf-8 -*-
"""
为每个已注册连接器构建一台独立的 FastMCP 实例。

工具来源由连接器注册表决定（本文件不认识任何具体连接器）：
- 声明了 server_factory 的连接器 ⇒ 由它自己构建原生服务器（工具逻辑在 hub 侧）；
- 其余 ⇒ 按 specs 声明的工具表构建通用代理，调用原样转发给 Java 的
  /api/v1/mcp/builtin/{code}/call。

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

from .connectors import registry as connector_registry

logger = logging.getLogger("mcp_hub")

# JSON Schema 类型 -> Python 注解（仅用于让 FastMCP 推断出与 specs 一致的 JSON Schema）
_JSON_TYPE_TO_PY = {
    "string": str, "integer": int, "boolean": bool,
    "number": float, "array": list, "object": dict,
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


def _make_tool_fn(server_code: str, tool_name: str, schema: dict, defaults: dict, read_only: bool):
    """按 specs 声明生成工具函数：参数顺序 = properties 顺序，类型取自 JSON Schema，默认值取自 defaults。"""
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    async def _fn(ctx: Context, **kwargs):
        return await _dispatch(server_code, tool_name, kwargs, ctx)

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for pname, prop in properties.items():
        annotation = _JSON_TYPE_TO_PY.get((prop or {}).get("type"), str)
        if pname in defaults:
            default = defaults[pname]
        elif pname not in required:
            # 声明为可选却漏给默认值 ⇒ FastMCP 会判成 required（inspect 的已知坑），补 None 兜住
            default = None
        else:
            default = inspect.Parameter.empty
        kind = inspect.Parameter.KEYWORD_ONLY
        if default is inspect.Parameter.empty:
            params.append(inspect.Parameter(pname, kind, annotation=annotation))
        else:
            params.append(inspect.Parameter(pname, kind, default=default, annotation=annotation))
    _fn.__name__ = f"{server_code}__{tool_name}"
    _fn.__signature__ = inspect.Signature(params)
    _fn.__doc__ = f"{server_code}.{tool_name}"
    return _fn


def build_servers() -> "dict[str, FastMCP]":
    """为每个已注册连接器构建一台 FastMCP 实例（streamable_http_path='/'，便于父 ASGI 改写路径）。

    本函数**不认识任何具体连接器**：
    - 连接器声明了 server_factory（原生实装，如 wechat_work 的双模式闸门）⇒ 交给它自己构建；
    - 否则按 specs 里声明的工具表构建通用代理，调用原样转给 Java 的 builtin/{code}/call。
    新增连接器只需在 connectors/registry 里 register 一份 manifest，本文件不改。
    """
    servers: "dict[str, FastMCP]" = {}
    for manifest in connector_registry.all_manifests():
        code = manifest.code
        native = connector_registry.build_server(code)
        if native is not None:
            servers[code] = native
            continue

        tool_list = connector_registry.tool_specs(code)
        if tool_list is None:
            raise RuntimeError(
                f"连接器 {code} 既无原生实现，specs.BUILTIN_SERVERS 里也没有工具目录；"
                f"请在 specs.py 补齐工具声明，或为其提供 server_factory"
            )
        mcp = FastMCP(code, streamable_http_path="/")
        for tool in tool_list:
            name = tool["name"]
            fn = _make_tool_fn(
                code, name,
                schema=tool["input_schema"],
                defaults=tool.get("defaults") or {},
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

# 端点信息（run.py 启动横幅、/health 用）：工具数一律取注册表声明
SERVER_INFO = {m.code: m.tool_count for m in connector_registry.all_manifests()}
