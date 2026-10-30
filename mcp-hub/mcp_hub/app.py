# -*- coding: utf-8 -*-
"""
ASGI 入口：把 /mcp/<serverCode> 路由到对应内置服务器的 FastMCP streamable-http 应用。

已知坑：FastMCP.streamable_http_app() 内部路由默认在 streamable_http_path（这里设为 "/"），
直接 Mount("/mcp/<code>", ...) 会变成 "/mcp/<code>/<path>" 匹配不到。
解决方案（方案 b）：用一个薄 ASGI 包装器，请求 /mcp/<code> 时把 scope["path"] 改写为 "/"
再交给该 code 的 app；并把所有子 app 的 lifespan（session manager 初始化）串到父 lifespan 里启动。

其它路由：
- GET /health                        健康探测（无状态自报）
- POST /internal/mcp/probe           Java 信任前存活探测（见 probe.py）
- /api/v1/connectors*                连接器统一管理面（见 connectors/admin_api.py）
- /api/v1/wecom_cli/*                企业微信（扫码）连接器（见 wecom_cli/admin_api.py）

设计原则：代理服务器无状态、不落盘、不读凭据、不持有密钥。
唯一例外是 `wecom_cli`——它需要在本地维护每个用户的 CLI 配置目录（扫码凭据由官方 CLI
自己加密存放），hub 只负责「按调用者身份算出该用哪个目录」，见 docs/64。
"""

import asyncio
import json
import logging

from . import builtin, probe
from .connectors import admin_api as connectors_admin_api
from .connectors import vault as connector_vault
from .wecom import store as wecom_store

logger = logging.getLogger("mcp_hub")

# 每个内置服务器一个 FastMCP 实例，及其 streamable-http ASGI app（路由在 "/"）
APPS = {code: mcp.streamable_http_app() for code, mcp in builtin.SERVERS.items()}


class _ChildLife:
    """独立驱动一个子 app 的 lifespan（启动 session manager，退出时停止）。"""

    def __init__(self, app):
        self.app = app
        self._q: "asyncio.Queue" = asyncio.Queue()
        self._task = None
        self._started = asyncio.Event()
        self._scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": {}}

    async def _receive(self):
        return await self._q.get()

    async def _send(self, msg):
        if msg.get("type") == "lifespan.startup.complete":
            self._started.set()

    async def start(self):
        await self._q.put({"type": "lifespan.startup"})
        self._task = asyncio.create_task(self.app(self._scope, self._receive, self._send))
        await asyncio.wait_for(self._started.wait(), timeout=10)

    async def stop(self):
        await self._q.put({"type": "lifespan.shutdown"})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except Exception:  # noqa: BLE001
                self._task.cancel()


_CHILDREN = [_ChildLife(app) for app in APPS.values()]


async def _lifespan(receive, send):
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            # 连接器共享底座先就绪（生产模式缺密钥在此 fail fast，见 wecom/crypto.py）
            try:
                wecom_store.init()
            except Exception as e:  # noqa: BLE001
                logger.error("连接器存储初始化失败：%s", e)
                raise
            # 通用连接器凭证库与它共用同一 SQLite 文件与同一把密钥
            try:
                connector_vault.init()
            except Exception as e:  # noqa: BLE001
                logger.error("连接器凭证库初始化失败：%s", e)
                raise
            for child in _CHILDREN:
                try:
                    await child.start()
                except Exception as e:  # noqa: BLE001
                    logger.exception("子 app lifespan 启动失败：%s", e)
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            for child in _CHILDREN:
                try:
                    await child.stop()
                except Exception as e:  # noqa: BLE001
                    pass
            await send({"type": "lifespan.shutdown.complete"})
            return


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


async def _health(send):
    await _send_json(send, 200, {"ok": True, "servers": builtin.SERVER_INFO})


async def _handle_http(scope, receive, send):
    path = scope.get("path", "")
    method = scope.get("method", "")

    if path == "/health":
        await _health(send)
        return

    if path == "/internal/mcp/probe" and method == "POST":
        await probe.handle(scope, receive, send)
        return

    # ⚠️ 旧的 /api/v1/wecom/* REST 面（自建应用 OAuth）已随连接器物理删除
    # （2026-10-30，docs/64 §9.7）。这里不再有前缀包含关系的分流问题。
    if path.startswith("/api/v1/wecom_cli"):
        from .wecom_cli import admin_api as wecom_cli_admin_api

        await wecom_cli_admin_api.handle(scope, receive, send)
        return

    if path.startswith("/api/v1/connectors"):
        await connectors_admin_api.handle(scope, receive, send)
        return

    if path.startswith("/mcp/"):
        code = path[len("/mcp/"):].strip("/").split("/")[0]
        app = APPS.get(code)
        if app is not None:
            new_scope = dict(scope)
            new_scope["path"] = "/"  # 子 app 的 streamable_http_path 是 "/"
            await app(new_scope, receive, send)
            return

    await _send_json(send, 404, {"ok": False, "error": "not found"})


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        await _lifespan(receive, send)
    elif scope["type"] == "http":
        await _handle_http(scope, receive, send)
    else:
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})
