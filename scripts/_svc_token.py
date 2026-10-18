"""服务间令牌（回归脚本用）：`/internal/v1/*` 自 2026-10-18 起强制校验。

背景：agent 的内部端点此前**零鉴权**（审计 B-1），补上中间件后，**所有直连 :8000 的脚本**
都必须带票，否则会集体 401 —— 而这批脚本大多把非 2xx 归因成「agent 挂了 / 接口坏了」，
于是缺陷排查会被引到完全错误的方向。

为什么脚本自己签而不是去调 Java 要票：这些是**诊断工具**，必须在后端没起来时也能用；
HS256 一行 HMAC 即可，密钥取值与部署一致（环境变量优先，其次开发占位串）。

用法：
    from _svc_token import svc_headers
    httpx.post(url, json=..., headers=svc_headers())
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

# 与 Java `DevSecretPlaceholders.SERVICE_JWT` / Python `service_jwt.DEV_SECRET` 逐字相同。
DEV_SECRET = "aioa-dev-service-jwt-secret-please-change"


def secret() -> str:
    """按优先级取密钥：SERVICE_JWT_SECRET（agent 侧读这个）> AIOA_SERVICE_JWT_SECRET（后端读这个）。"""
    return (
        os.getenv("SERVICE_JWT_SECRET")
        or os.getenv("AIOA_SERVICE_JWT_SECRET")
        or DEV_SECRET
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def token(svc: str = "server", ttl_seconds: int = 300) -> str:
    now = int(time.time())
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(
        {"sub": svc, "svc": svc, "iat": now, "exp": now + ttl_seconds},
        separators=(",", ":")).encode())
    signing_input = f"{head}.{body}"
    sig = hmac.new(secret().encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(sig)}"


def svc_headers(svc: str = "server") -> dict[str, str]:
    """直接可用的请求头。"""
    return {"Authorization": "Bearer " + token(svc)}
