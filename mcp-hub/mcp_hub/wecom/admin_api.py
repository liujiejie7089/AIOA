# -*- coding: utf-8 -*-
"""hub 侧 REST 面（非 MCP 协议）：给 H5 连接器面板与管理端配置页用。

路由（父 ASGI 按 /api/v1/wecom/ 前缀分流进来）：
- GET  /api/v1/wecom/tenant-config          租户配置掩码视图
- PUT  /api/v1/wecom/tenant-config           upsert 租户配置（仅管理员）
- GET  /api/v1/wecom/connections             我的连接态（脱敏）
- GET  /api/v1/wecom/oauth/authorize-url     生成授权链接（交付物②：URL 模板 + Scheme）
- GET  /api/v1/wecom/oauth/callback          企微授权回调（A 模式落地入口）

安全纪律：
- 租户配置 PUT 仅放行 ROLE_ADMIN / ROLE_TENANT_ADMIN（经 Java /auth/me 判定，mock 模式除外）；
- 任何响应都不含凭据明文/密文，只有掩码与状态；
- 回调地址必须与 state 绑定，伪造/过期 state 一律拒绝且不写库。
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlencode

from . import identity, oauth, store
from .crypto import mask
from .server import complete_oauth

logger = logging.getLogger("mcp_hub.wecom")

_PREFIX = "/api/v1/wecom"


def _result_url(status: str, reason: str = "") -> str:
    base = os.environ.get(
        "WECOM_OAUTH_RESULT_URL", "http://127.0.0.1:5173/#/connectors"
    )
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}wecom={status}" + (f"&reason={reason}" if reason else "")


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
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8")]})
    await send({"type": "http.response.body", "body": data})


async def _redirect(send, location: str):
    await send({"type": "http.response.start", "status": 302,
                "headers": [(b"location", location.encode("utf-8")),
                            (b"content-type", b"text/plain; charset=utf-8")]})
    await send({"type": "http.response.body", "body": b""})


def _query(scope) -> dict:
    from urllib.parse import parse_qs

    raw = scope.get("query_string", b"") or b""
    out = {}
    for k, v in parse_qs(raw.decode("utf-8")).items():
        out[k] = v[0] if v else ""
    return out


async def handle(scope, receive, send):
    path = scope.get("path", "")
    method = scope.get("method", "GET")
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    query = _query(scope)

    try:
        if path == f"{_PREFIX}/tenant-config" and method == "GET":
            return await _get_config(headers, send)
        if path == f"{_PREFIX}/tenant-config" and method == "PUT":
            body = await _read_body(receive)
            return await _put_config(headers, body, send)
        if path == f"{_PREFIX}/connections" and method == "GET":
            return await _get_connections(headers, query, send)
        if path == f"{_PREFIX}/oauth/authorize-url" and method == "GET":
            return await _authorize_url(headers, query, send)
        if path == f"{_PREFIX}/oauth/callback":
            return await _callback(query, send)
    except Exception as e:  # noqa: BLE001 —— REST 面绝不裸抛 500
        logger.exception("wecom REST 处理失败")
        return await _send_json(send, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    return await _send_json(send, 404, {"ok": False, "error": "not found"})


# ---------- 各路由 ----------


async def _get_config(headers, send):
    ident = await identity.resolve_headers(headers)
    cfg = await store.get_tenant_config(ident.tenant_id)
    if cfg is None:
        return await _send_json(send, 200, {"ok": True, "configured": False,
                                            "corpId": "", "corpSecret": "", "agentId": "",
                                            "redirectUri": None})
    return await _send_json(send, 200, {"ok": True, **cfg.masked()})


async def _put_config(headers, body: bytes, send):
    ident = await identity.resolve_headers(headers)
    if not ident.mock and not ident.is_admin:
        return await _send_json(send, 403, {"ok": False, "error": "仅租户管理员可配置企业微信应用凭据"})
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return await _send_json(send, 400, {"ok": False, "error": "请求体不是合法 JSON"})
    corp_id = (data.get("corpId") or "").strip()
    corp_secret = (data.get("corpSecret") or "").strip()
    agent_id = (data.get("agentId") or "").strip()
    redirect_uri = (data.get("redirectUri") or "").strip() or None
    if not corp_id or not corp_secret or not agent_id:
        return await _send_json(send, 400, {"ok": False, "error": "corpId / corpSecret / agentId 均必填"})
    await store.upsert_tenant_config(ident.tenant_id, corp_id, corp_secret, agent_id,
                                     redirect_uri, ident.username or ident.user_id)
    logger.info("[wecom] 租户 %s 更新连接器配置 by %s", ident.tenant_id, ident.user_id)
    return await _send_json(send, 200, {"ok": True, "message": "已保存"})


async def _get_connections(headers, query, send):
    ident = await identity.resolve_headers(headers)
    conn = await store.get_connection(ident.tenant_id, ident.user_id)
    view = None
    if conn is not None:
        view = conn.public_view()
        view["connected"] = conn.status == "CONNECTED"
    return await _send_json(send, 200, {"ok": True, "connection": view})


async def _authorize_url(headers, query, send):
    ident = await identity.resolve_headers(headers)
    cfg = await store.get_tenant_config(ident.tenant_id)
    if cfg is None:
        return await _send_json(send, 200, {"ok": False, "error": "租户未配置企业微信应用凭据"})
    try:
        redirect_uri = oauth.redirect_uri_of(cfg)
    except ValueError as e:
        return await _send_json(send, 200, {"ok": False, "error": str(e)})
    ua = headers.get("user-agent", "")
    state = await oauth.issue_state(ident.tenant_id, ident.user_id, "A",
                                    {"redirect_uri": redirect_uri, "ua": ua})
    if oauth.is_wecom_builtin(ua):
        url = oauth.build_authorize_url(cfg.corp_id, cfg.agent_id, redirect_uri, state)
        kind = "oauth_authorize"
    else:
        url = oauth.build_qr_connect_url(cfg.corp_id, cfg.agent_id, redirect_uri, state)
        kind = "qr_connect"
    return await _send_json(send, 200, {
        "ok": True, "kind": kind, "authorizeUrl": url, "state": state,
        "redirectUri": redirect_uri, "expiresInSeconds": 600,
        "templates": {
            "authorize": "https://open.weixin.qq.com/connect/oauth2/authorize"
                         "?appid={corpId}&redirect_uri={redirectUri}&response_type=code"
                         "&scope=snsapi_privateinfo&agentid={agentId}&state={state}#wechat_redirect",
            "qrConnect": "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
                         "?appid={corpId}&agentid={agentId}&redirect_uri={redirectUri}&state={state}",
        },
    })


async def _callback(query, send):
    """企微授权回调：code + state → 换身份 → 落库 → 302 回前端结果页。"""
    state = query.get("state") or ""
    code = query.get("code") or ""
    consumed = await oauth.consume_state(state)
    if consumed is None:
        logger.info("[wecom] 回调拒绝：state 无效/已用/过期 state=%r", state[:12])
        return await _redirect(send, _result_url("fail", "bad-state"))
    if not code:
        return await _redirect(send, _result_url("fail", "no-code"))
    try:
        await complete_oauth(consumed["tenant_id"], consumed["user_id"], code)
    except Exception as e:  # noqa: BLE001
        logger.info("[wecom] 回调失败：%s", e)
        return await _redirect(send, _result_url("fail", type(e).__name__))
    logger.info("[wecom] 回调成功：tenant=%s user=%s", consumed["tenant_id"], consumed["user_id"])
    return await _redirect(send, _result_url("ok"))
