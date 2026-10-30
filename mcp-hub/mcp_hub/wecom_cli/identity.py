# -*- coding: utf-8 -*-
"""调用方身份解析（wecom_cli 专用）。

与 `wecom/identity.py` 的差别只有**策略**，实现复用那边的 `from_authorization()`：
**只要有 Authorization，就一定走真实身份**，不看 `WECOM_MOCK`。

理由：扫码绑定是「按真人账号」绑的 —— 一台机器上 `WECOM_MOCK=1` 时如果退回 mock 身份，
就会出现「用户 A 扫的码被记到 mock 用户名下」，连接态与配置目录双双错位，
而且这种错位在开发环境里恰好不会报错，只会在生产暴露。所以这里把优先级钉死：
Authorization → 真实；无 Authorization 且 mock 开启 → 才允许合成身份（哨兵/离线联调用）。

（2026-10-30 清理：原先这里有一份和 `wecom/identity.py` 几乎逐行相同的 httpx 调用 +
缓存 + 解析。两份并存只会「改一处漏一处」—— 比如 token 缓存键、`data` 兜底这些细节。）
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from ..wecom import identity as base_identity

logger = logging.getLogger("mcp_hub.wecom_cli")

_MOCK_HEADER = "x-wecom-mock-user"


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str
    username: str = ""


class IdentityError(RuntimeError):
    pass


def _mock(headers: dict) -> Identity:
    raw = headers.get(_MOCK_HEADER)
    if raw:
        try:
            d = json.loads(raw)
            return Identity(str(d.get("tenantId", "mock-tenant")),
                            str(d.get("userId", "mock-user")),
                            str(d.get("username", "mock-user")))
        except Exception:  # noqa: BLE001
            pass
    return Identity("mock-tenant", "mock-user", "mock-user")


async def resolve(ctx) -> Identity:
    try:
        headers = {k.lower(): v for k, v in ctx.request_context.request.headers.items()}
    except Exception:  # noqa: BLE001
        headers = {}
    return await resolve_headers(headers)


async def resolve_headers(headers: dict) -> Identity:
    auth = headers.get("authorization")
    if auth:
        try:
            ident = await base_identity.from_authorization(auth)
        except base_identity.IdentityError as e:
            # 换成本包自己的异常类型：调用方 (admin_api / server) 只认这一种
            raise IdentityError(str(e)) from e
        return Identity(ident.tenant_id, ident.user_id, ident.username)
    if os.environ.get("WECOM_MOCK", "0") == "1":
        return _mock(headers)
    raise IdentityError("缺少 Authorization 头，无法识别调用方身份")
