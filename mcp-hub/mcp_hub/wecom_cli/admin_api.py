# -*- coding: utf-8 -*-
"""wecom_cli 的 REST 面（给「连接器」面板用）：发起扫码、查状态、绑定、解绑。

路由（父 ASGI 按 /api/v1/wecom_cli 前缀分流）：
- GET  /api/v1/wecom_cli/status        我的绑定状态（含显示名）
- POST /api/v1/wecom_cli/qr            发起扫码，返回二维码 PNG（data URL）
- POST /api/v1/wecom_cli/bind          扫码完成后确认绑定（校验 + 回写 Java 连接态）
- POST /api/v1/wecom_cli/disconnect    解绑（删本地配置目录 + 回写 NEED_AUTH）

⚠️ 前缀陷阱：`/api/v1/wecom_cli` 以 `/api/v1/wecom` 开头，
在 `app.py` 里必须**排在 wecom_admin_api 之前**判断，否则请求会被旧连接器吞掉、
表现为「扫码接口 404 或返回企业微信应用配置」。这一点已在 app.py 里显式注明。
"""

from __future__ import annotations

import base64
import json
import logging

from ..wecom import sync
from . import auth as cli_auth
from . import identity, profiles, runner

logger = logging.getLogger("mcp_hub.wecom_cli")

_PREFIX = "/api/v1/wecom_cli"
CODE = "wecom_cli"


async def _read_body(receive) -> bytes:
    body = b""
    more = True
    while more:
        msg = await receive()
        if msg["type"] == "http.disconnect":
            break
        body += msg.get("body", b"")
        more = msg.get("more_body", False)
    return body


async def _send_json(send, status: int, payload: dict):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8")]})
    await send({"type": "http.response.body", "body": data})


# 注意：这两个 helper 必须是 **async**，调用处必须 `await`。
# 写成同步函数 `def _ok(...): return _send_json(...)` 时，`_send_json` 返回的是协程，
# 而 `return _ok(...)` 只是把这个协程当返回值丢出去 —— 既没 await、也不会有人消费它，
# 现象是 uvicorn 报 "ASGI callable returned without starting response" + 客户端拿到 500，
# 但业务逻辑其实已经跑完了（实测：库里已 CONNECTED，接口却回 500，最容易误判成写库失败）。
async def _ok(send, data: dict):
    return await _send_json(send, 200, {"code": 0, "message": "ok", "data": data})


async def _fail(send, status: int, message: str):
    return await _send_json(send, status, {"code": status, "message": message})


async def handle(scope, receive, send):
    path = scope.get("path", "")
    method = scope.get("method", "GET")
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

    try:
        ident = await identity.resolve_headers(headers)
    except identity.IdentityError as e:
        return await _fail(send, 401, str(e))

    sub = path[len(_PREFIX):].strip("/")

    try:
        if sub in ("", "status") and method == "GET":
            return await _status(send, ident)

        if sub == "qr" and method == "POST":
            await _read_body(receive)
            png, reused = await cli_auth.start_qr(ident.tenant_id, ident.user_id)
            return await _ok(send, {
                "qr": "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii"),
                "reused": reused,
                "expiresIn": 300,
                "hint": "用企业微信扫码完成授权；扫码后本页自动刷新",
            })

        if sub == "bind" and method == "POST":
            await _read_body(receive)
            res = await cli_auth.bind(ident.tenant_id, ident.user_id)
            synced = await sync.report_connected(
                ident.tenant_id, ident.user_id, CODE, res.get("accountLabel"),
                {"binding": "cli-qr"})
            return await _ok(send, {"bound": True, "accountLabel": res.get("accountLabel"),
                              "botName": res.get("botName"), "sharedProfile": res.get("shared"),
                              "stateSynced": synced})

        if sub == "disconnect" and method == "POST":
            await _read_body(receive)
            wiped = profiles.wipe(ident.tenant_id, ident.user_id)
            synced = await sync.report_disconnected(ident.tenant_id, ident.user_id, CODE)
            return await _ok(send, {"bound": False, "wiped": wiped, "stateSynced": synced})

    except profiles.NotBound as e:
        return await _fail(send, 400, str(e))
    except runner.CliError as e:
        return await _fail(send, 400, str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("wecom_cli 接口异常：%s", e)
        return await _fail(send, 500, f"服务端异常：{type(e).__name__}")

    return await _fail(send, 404, f"未知路由：{method} {path}")


async def _status(send, ident):
    """绑定状态。以本地配置目录为准（文件在=真授权过），不用数据库自述。"""
    label = None
    shared = False
    try:
        d, shared = profiles.resolve(ident.tenant_id, ident.user_id)
    except profiles.NotBound:
        return await _ok(send, {"authorized": False, "accountLabel": None, "sharedProfile": False})
    st = await cli_auth.status(d)
    if st == "authorized":
        label = profiles.account_label(ident.tenant_id, ident.user_id)
        if not label:
            try:
                names = await cli_auth.whoami(d)
                label = names.get("userName")
            except runner.CliError:
                label = None
    return await _ok(send, {"authorized": st == "authorized", "accountLabel": label,
                      "sharedProfile": shared})
