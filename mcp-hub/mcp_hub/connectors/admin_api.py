# -*- coding: utf-8 -*-
"""连接器统一管理面（REST，非 MCP 协议）。

一个入口覆盖全部连接器，前端不需要认识具体连接器：

  GET    /api/v1/connectors                    连接器清单（含凭证字段 schema 与就绪状态）
  GET    /api/v1/connectors/{code}             单个连接器详情
  GET    /api/v1/connectors/{code}/credentials 掩码视图（绝无明文）
  PUT    /api/v1/connectors/{code}/credentials 保存（仅管理员；空串/掩码值=保留旧值）
  DELETE /api/v1/connectors/{code}/credentials 清除（仅管理员）

provider 决定凭据落哪儿，调用方无感：
- vault ⇒ 通用凭证保险库（connectors/vault.py，任意第三方应用）
- none  ⇒ 该连接器没有应用级凭据（用户自填 / 扫码自授权），PUT 会被明确拒绝而不是静默成功

> 2026-10-30：`wecom` 这个 provider（企业微信自建应用专用加密表）随连接器一起物理删除，
> 见 docs/64 §9.7。新增需要「管理员配置应用凭据」的连接器请一律用 vault。
"""

from __future__ import annotations

import json
import logging

from ..wecom import identity
from . import registry, vault

logger = logging.getLogger("mcp_hub.connectors")

_PREFIX = "/api/v1/connectors"


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
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8")]})
    await send({"type": "http.response.body", "body": data})


async def handle(scope, receive, send):
    path = scope.get("path", "")
    method = scope.get("method", "GET")
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

    try:
        rest = path[len(_PREFIX):].strip("/")
        parts = [p for p in rest.split("/") if p]

        if not parts and method == "GET":
            return await _list(headers, send)
        if len(parts) == 1 and method == "GET":
            return await _detail(headers, parts[0], send)
        if len(parts) == 2 and parts[1] == "credentials" and method == "GET":
            return await _get_credentials(headers, parts[0], send)
        if len(parts) == 2 and parts[1] == "credentials" and method == "PUT":
            body = await _read_body(receive)
            return await _put_credentials(headers, parts[0], body, send)
        if len(parts) == 2 and parts[1] == "credentials" and method == "DELETE":
            return await _delete_credentials(headers, parts[0], send)
    except Exception as e:  # noqa: BLE001 —— 管理面绝不裸抛 500 堆栈
        logger.exception("连接器管理面处理失败")
        return await _send_json(send, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    return await _send_json(send, 404, {"ok": False, "error": "not found"})


# ---------- 身份与状态 ----------


async def _ident(headers):
    """解析调用方身份；失败直接抛 IdentityError（由 handle 统一转 401/500）。"""
    return await identity.resolve_headers(headers)


def _require_admin(ident) -> str | None:
    """返回拒绝原因（None 表示放行）。mock 模式（哨兵/联调）放行。"""
    if getattr(ident, "mock", False) or ident.is_admin:
        return None
    return "仅租户管理员可修改连接器凭据"


async def _status(manifest, tenant_id: str) -> dict:
    """按 provider 汇总「是否已配置」。返回值一律不含明文。"""
    fields = manifest.schema()
    required = [f.name for f in manifest.required_fields]

    if manifest.provider == "none":
        return {"configured": True, "enabled": True, "values": {},
                "hint": "该连接器无应用级凭据，由每位用户自行授权"}

    plain = await vault.get_values(tenant_id, manifest.code)
    masked = vault.mask_view(plain, fields)
    configured = all(plain.get(k) for k in required)
    return {"configured": configured, "enabled": bool(plain), "values": masked,
            "hint": "" if configured else "待管理员配置"}


# ---------- 路由实现 ----------


async def _list(headers, send):
    ident = await _ident(headers)
    items = []
    for m in registry.all_manifests():
        st = await _status(m, ident.tenant_id)
        items.append({**m.public(), **st,
                      "configReady": st["configured"],
                      "canEdit": _require_admin(ident) is None})
    return await _send_json(send, 200, {"ok": True, "count": len(items), "connectors": items})


async def _detail(headers, code, send):
    ident = await _ident(headers)
    m = registry.get(code)
    if m is None:
        return await _send_json(send, 404, {"ok": False, "error": f"未知连接器：{code}"})
    st = await _status(m, ident.tenant_id)
    return await _send_json(send, 200, {"ok": True, **m.public(), **st,
                                        "configReady": st["configured"],
                                        "canEdit": _require_admin(ident) is None})


async def _get_credentials(headers, code, send):
    ident = await _ident(headers)
    m = registry.get(code)
    if m is None:
        return await _send_json(send, 404, {"ok": False, "error": f"未知连接器：{code}"})
    st = await _status(m, ident.tenant_id)
    return await _send_json(send, 200, {
        "ok": True, "code": code, "authMode": m.auth_mode, "provider": m.provider,
        "credentialFields": m.schema(), **st,
    })


async def _put_credentials(headers, code, body: bytes, send):
    ident = await _ident(headers)
    denied = _require_admin(ident)
    if denied:
        return await _send_json(send, 403, {"ok": False, "error": denied})

    m = registry.get(code)
    if m is None:
        return await _send_json(send, 404, {"ok": False, "error": f"未知连接器：{code}"})
    if m.provider == "none":
        return await _send_json(send, 400, {
            "ok": False, "error": f"连接器 {code} 无应用级凭据，无需管理员配置"})

    try:
        payload = json.loads(body or b"{}")
    except Exception:
        return await _send_json(send, 400, {"ok": False, "error": "请求体不是合法 JSON"})
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        return await _send_json(send, 400, {"ok": False, "error": "缺少 values 对象"})

    # 只接受 schema 里声明过的字段，杜绝写入任意键
    allowed = {f.name for f in m.credential_fields}
    extra = sorted(set(values) - allowed)
    if extra:
        return await _send_json(send, 400, {"ok": False, "error": f"未声明的字段：{', '.join(extra)}"})
    values = {k: ("" if v is None else str(v)) for k, v in values.items()}
    required = [f.name for f in m.required_fields]

    try:
        await vault.put_values(ident.tenant_id, code, values,
                               updated_by=ident.username or ident.user_id,
                               required=required)
    except ValueError as e:
        return await _send_json(send, 400, {"ok": False, "error": str(e)})

    logger.info("[connectors] %s 凭据已保存 tenant=%s user=%s", code, ident.tenant_id, ident.user_id)
    st = await _status(m, ident.tenant_id)
    return await _send_json(send, 200, {"ok": True, "message": "已保存（密文落库）", **st})


async def _delete_credentials(headers, code, send):
    ident = await _ident(headers)
    denied = _require_admin(ident)
    if denied:
        return await _send_json(send, 403, {"ok": False, "error": denied})

    m = registry.get(code)
    if m is None:
        return await _send_json(send, 404, {"ok": False, "error": f"未知连接器：{code}"})
    if m.provider == "none":
        return await _send_json(send, 400, {
            "ok": False, "error": f"连接器 {code} 无应用级凭据可清除"})

    await vault.clear(ident.tenant_id, code)

    logger.info("[connectors] %s 凭据已清除 tenant=%s user=%s", code, ident.tenant_id, ident.user_id)
    st = await _status(m, ident.tenant_id)
    return await _send_json(send, 200, {"ok": True, "message": "已清除", **st})
