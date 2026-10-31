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

# 连接器共享底座（SQLite + 主密钥）初始化失败的原因；None = 正常。
# 只为观测而存在：失败时进程仍起来（纯代理连接器还能用），但 /health 转 503，
# 让 `docker compose ps` / HEALTHCHECK 立刻看得见，而不是「健康着却什么都不可用」。
_INIT_ERROR: "str | None" = None

# 每个内置服务器一个 FastMCP 实例，及其 streamable-http ASGI app（路由在 "/"）
APPS = {code: mcp.streamable_http_app() for code, mcp in builtin.SERVERS.items()}


class _ChildLife:
    """独立驱动一个子 app 的 lifespan（启动 session manager，退出时停止）。

    `ok` / `error` 是给**路由层**看的：子 app 没起来时不能再把请求丢进去——那只会
    换回一个没有任何线索的裸 500（见 `_handle_http` 里 `/mcp/` 分支的注释）。
    """

    def __init__(self, code: str, app):
        self.code = code
        self.app = app
        self.ok = False
        self.error = "尚未启动"
        self._q: "asyncio.Queue" = asyncio.Queue()
        self._task = None
        self._started = asyncio.Event()
        self._scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": {}}

    async def _receive(self):
        return await self._q.get()

    async def _send(self, msg):
        # 三种结束信号都要放行：只认 startup.complete 的话，失败时事件永远不会被 set，
        # 只能干等 10s 超时，日志里剩一句 TimeoutError——看不出是哪个子服务、为什么。
        if msg.get("type") == "lifespan.startup.complete":
            self.ok = True
            self._started.set()
        elif msg.get("type") == "lifespan.startup.failed":
            self.error = msg.get("message") or "lifespan.startup.failed"
            self._started.set()

    async def start(self):
        await self._q.put({"type": "lifespan.startup"})
        self._task = asyncio.create_task(self.app(self._scope, self._receive, self._send))
        try:
            await asyncio.wait_for(self._started.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.error = "lifespan 启动超时（10s 内未回 startup.complete）"
            raise RuntimeError(f"子服务 {self.code} {self.error}")
        if not self.ok:
            raise RuntimeError(f"子服务 {self.code} 启动失败：{self.error}")

    async def stop(self):
        await self._q.put({"type": "lifespan.shutdown"})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except Exception:  # noqa: BLE001
                self._task.cancel()


_CHILDREN = {code: _ChildLife(code, app) for code, app in APPS.items()}


async def _lifespan(receive, send):
    global _INIT_ERROR
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            # 连接器共享底座（SQLite + 主密钥）。
            # ★ 失败**不再中断启动**：只有 wecom_cli 依赖它，qq_mail 只是把调用转给 Java。
            #   2026-10-31 生产事故的直接成因就是这里的 `raise`：真正的错只有一行
            #   `Permission denied: '/app/data'`，异常抛出后 uvicorn 把它当成
            #   「ASGI 'lifespan' protocol appears unsupported.」**照常开始服务**，
            #   于是所有 /mcp/<code> 都落到从未启动的子 app 上 —— 现象是「连接器全线不可用」，
            #   而根因被埋在一行 ERROR 里。现在改成：记下来、继续起子服务、把原因透出去。
            errs = []
            for name, fn in (("连接器存储", wecom_store.init),
                             ("连接器凭证库", connector_vault.init)):
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    errs.append(f"{name}初始化失败：{type(e).__name__}: {e}")
                    logger.exception(
                        "%s初始化失败 —— 依赖它的连接器（wecom_cli）会在调用时报错，"
                        "不依赖它的（qq_mail 等纯代理连接器）不受影响；/health 会转为 503",
                        name)
            if errs:
                _INIT_ERROR = "；".join(errs)
            for child in _CHILDREN.values():
                try:
                    await child.start()
                    logger.info("MCP 子服务已就绪：%s", child.code)
                except Exception as e:  # noqa: BLE001
                    child.ok = False
                    if not child.error or child.error == "尚未启动":
                        child.error = f"{type(e).__name__}: {e}"
                    logger.exception(
                        "子 app lifespan 启动失败：%s —— 该连接器的 /mcp 请求此后会明确报 503",
                        child.code,
                    )
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            for child in _CHILDREN.values():
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
    # 底座起不来时**不要**回 200：HEALTHCHECK 用的是 urlopen，非 2xx 即失败 ⇒
    # `docker compose ps` 直接显示 unhealthy。否则会出现「健康但连接器全废」
    # （2026-10-31 生产就是这种状态，白白多排查了一轮）。
    if _INIT_ERROR:
        await _send_json(send, 503, {
            "ok": False,
            "error": "init_failed",
            "message": _INIT_ERROR,
            "servers": builtin.SERVER_INFO,
        })
        return
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
        child = _CHILDREN.get(code)
        if child is not None:
            if not child.ok:
                # 子服务没起来就直说「未就绪」并给出原因；往死 app 里丢请求只会得到裸 500。
                await _send_json(send, 503, {
                    "ok": False,
                    "error": "mcp_server_unavailable",
                    "message": f"{code} 未就绪：{child.error}",
                })
                return
            new_scope = dict(scope)
            new_scope["path"] = "/"  # 子 app 的 streamable_http_path 是 "/"
            sent = {"started": False}

            async def _send(msg, _inner=send, _flag=sent):
                if msg.get("type") == "http.response.start":
                    _flag["started"] = True
                await _inner(msg)

            try:
                await child.app(new_scope, receive, _send)
            except Exception as e:  # noqa: BLE001
                # 裸 500 是最没用的失败形态：ASGI 层不把栈透给调用方，容器日志里也未必有
                # （2026-10-31 生产 /mcp/qq_mail 恒 500 时正是卡在这里查不下去）。所以这里
                # 必须 ① 打出完整栈；② 回一个**带 message** 的 JSON —— Java 侧
                # renderReason() 只在响应缺 message 时才拼成「连接器返回异常（HTTP 500）」，
                # 带上 message 就能把真实原因透到前端，不用再猜。
                logger.exception("MCP 子服务 %s 处理请求失败：%s", code, e)
                if not sent["started"]:
                    await _send_json(send, 500, {
                        "ok": False,
                        "error": "mcp_server_failed",
                        "message": f"{code} 处理失败：{type(e).__name__}: {e}",
                    })
                return
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
