# -*- coding: utf-8 -*-
"""调用方身份解析。

纪律：鉴权仍归 Java。本模块自己不验签 JWT，而是把入站 Authorization 原样转发到
Java `GET /api/v1/auth/me`，用 Java 的判定结果（userId / tenantId / roles）作为
连接态存储主键。这保住了「Java 是唯一身份权威」的既有边界，Python 侧不持有任何密钥。

mock 模式（WECOM_MOCK=1，仅开发/哨兵）：允许从请求头 X-Wecom-Mock-User 直接取
身份（JSON：{"tenantId":"t1","userId":"u1","roles":[...]}），默认合成身份，
让 E2E 不依赖 Java 后端也能跑通。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import httpx

from .models import Identity
from .store import is_mock

logger = logging.getLogger("mcp_hub.wecom")

_MOCK_HEADER = "x-wecom-mock-user"
_CACHE_TTL = 60  # 秒：token → identity 的进程内缓存，避免每次工具调用都打 Java
_cache: dict[str, tuple[float, Identity]] = {}


class IdentityError(RuntimeError):
    pass


def _base_url() -> str:
    return os.environ.get("AIOS_SERVER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _mock_identity(headers) -> Identity:
    raw = headers.get(_MOCK_HEADER)
    if raw:
        try:
            data = json.loads(raw)
            return Identity(
                tenant_id=str(data.get("tenantId", "mock-tenant")),
                user_id=str(data.get("userId", "mock-user")),
                username=str(data.get("username", "mock-user")),
                roles=[str(r) for r in (data.get("roles") or [])],
                mock=True,
            )
        except Exception:
            pass
    return Identity(tenant_id="mock-tenant", user_id="mock-user", username="mock-user", mock=True)


def _headers_of(ctx) -> dict:
    """从 MCP Context 取出站请求头（小写键）。"""
    try:
        request = ctx.request_context.request
        return {k.lower(): v for k, v in request.headers.items()}
    except Exception:
        return {}


async def resolve(ctx) -> Identity:
    return await resolve_headers(_headers_of(ctx))


async def resolve_headers(headers: dict) -> Identity:
    """从请求头解析身份。headers 键应为小写。"""
    if is_mock():
        return _mock_identity(headers)

    auth = headers.get("authorization")
    if not auth:
        raise IdentityError("缺少 Authorization 头，无法识别调用方身份")
    if not auth.lower().startswith("bearer "):
        auth = "Bearer " + auth

    token_hash = hashlib.sha256(auth.encode()).hexdigest()[:16]
    hit = _cache.get(token_hash)
    now = time.time()
    if hit and hit[0] > now:
        return hit[1]

    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(f"{_base_url()}/api/v1/auth/me", headers={"Authorization": auth})
    except httpx.HTTPError as e:
        raise IdentityError(f"身份解析后端不可达：{type(e).__name__}") from e
    if resp.status_code != 200:
        raise IdentityError(f"身份解析失败：HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception as e:
        raise IdentityError("身份解析响应不是合法 JSON") from e
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        data = body if isinstance(body, dict) else {}
    user_id = data.get("id") or data.get("userId")
    if user_id is None:
        raise IdentityError("身份解析响应缺少用户标识")
    identity = Identity(
        tenant_id=str(data.get("tenantId", 0)),
        user_id=str(user_id),
        username=str(data.get("username") or data.get("nickname") or ""),
        roles=[str(r) for r in (data.get("roles") or [])],
    )
    _cache[token_hash] = (now + _CACHE_TTL, identity)
    return identity
