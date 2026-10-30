# -*- coding: utf-8 -*-
"""调用方身份解析（wecom_cli 专用）。

与 `wecom/identity.py` 的唯一差别、也是必须差别：**只要有 Authorization，就一定走真实身份**，
不看 `WECOM_MOCK`。

理由：扫码绑定是「按真人账号」绑的 —— 一台机器上 `WECOM_MOCK=1` 时如果退回 mock 身份，
就会出现「用户 A 扫的码被记到 mock 用户名下」，连接态与配置目录双双错位，
而且这种错位在开发环境里恰好不会报错，只会在生产暴露。所以这里把优先级钉死：
Authorization → 真实；无 Authorization 且 mock 开启 → 才允许合成身份（哨兵/离线联调用）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("mcp_hub.wecom_cli")

_CACHE_TTL = 60
_cache: dict[str, tuple[float, "Identity"]] = {}
_MOCK_HEADER = "x-wecom-mock-user"


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str
    username: str = ""
    mock: bool = False


class IdentityError(RuntimeError):
    pass


def _base_url() -> str:
    return os.environ.get("AIOS_SERVER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _mock(headers: dict) -> Identity:
    raw = headers.get(_MOCK_HEADER)
    if raw:
        try:
            d = json.loads(raw)
            return Identity(str(d.get("tenantId", "mock-tenant")),
                            str(d.get("userId", "mock-user")),
                            str(d.get("username", "mock-user")), mock=True)
        except Exception:  # noqa: BLE001
            pass
    return Identity("mock-tenant", "mock-user", "mock-user", mock=True)


async def resolve(ctx) -> Identity:
    try:
        headers = {k.lower(): v for k, v in ctx.request_context.request.headers.items()}
    except Exception:  # noqa: BLE001
        headers = {}
    return await resolve_headers(headers)


async def resolve_headers(headers: dict) -> Identity:
    auth = headers.get("authorization")
    if auth:
        if not auth.lower().startswith("bearer "):
            auth = "Bearer " + auth
        return await _from_java(auth)
    if os.environ.get("WECOM_MOCK", "0") == "1":
        return _mock(headers)
    raise IdentityError("缺少 Authorization 头，无法识别调用方身份")


async def _from_java(auth: str) -> Identity:
    token_hash = hashlib.sha256(auth.encode()).hexdigest()[:16]
    now = time.time()
    hit = _cache.get(token_hash)
    if hit and hit[0] > now:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(f"{_base_url()}/api/v1/auth/me", headers={"Authorization": auth})
    except httpx.HTTPError as e:
        raise IdentityError(f"身份解析后端不可达：{type(e).__name__}") from e
    if resp.status_code != 200:
        raise IdentityError(f"身份解析失败：HTTP {resp.status_code}")
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        data = body if isinstance(body, dict) else {}
    uid = data.get("id") or data.get("userId")
    if uid is None:
        raise IdentityError("身份解析响应缺少用户标识")
    ident = Identity(str(data.get("tenantId", 0)), str(uid),
                     str(data.get("username") or data.get("nickname") or ""))
    _cache[token_hash] = (now + _CACHE_TTL, ident)
    return ident
