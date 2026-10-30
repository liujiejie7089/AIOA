# -*- coding: utf-8 -*-
"""服务间令牌（HS256），与 Java `ServiceTokenProvider` / agent `security/service_jwt.py` 同口径。

为什么 hub 也要能签：连接态的唯一真相源在 Java（manifest 闸门读 `connector_connection`），
而 hub 在「企微回调」这一步手里**没有用户 token**（那是浏览器 302，只有 code/state），
所以只能用服务身份把「某某用户已授权」写回 Java。见 docs/63 §9.2。

密钥来源：env `AIOS_SERVICE_JWT_SECRET`，必须与 Java `aios.service-jwt.secret` 一致。
**故意不给默认值**：给了默认值，生产一旦漏配就会静默用开发密钥签票（那等于没有鉴权）。
未配置时 `issue()` 抛错，由调用方转成「未同步」并告警。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

SVC_HUB = "hub"
ENV_SECRET = "AIOS_SERVICE_JWT_SECRET"


class ServiceTokenError(RuntimeError):
    pass


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def secret() -> str:
    return (os.environ.get(ENV_SECRET) or "").strip()


def configured() -> bool:
    return bool(secret())


def issue(svc: str = SVC_HUB, ttl_seconds: int = 300) -> str:
    """签发服务令牌。未配置密钥直接抛错（不静默退化）。"""
    key = secret()
    if not key:
        raise ServiceTokenError(
            f"未设置 {ENV_SECRET}，无法签发服务令牌（需与 Java aios.service-jwt.secret 一致）")
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": svc, "svc": svc, "iat": now, "exp": now + int(ttl_seconds)}
    signing_input = (
        _b64e(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64e(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = hmac.new(key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64e(sig)}"
