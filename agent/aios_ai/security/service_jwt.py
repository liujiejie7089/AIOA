"""服务间令牌（Java aios-server ⇄ Python agent）：签发与校验。

为什么要有这个模块
------------------
`/internal/v1/*` 是**服务间**接口：`models/apply` 能把模型密钥热加载进进程、`runs` 会消耗额度与
执行工具。审计（docs/45 C-1 同类）实测这些端点此前**零鉴权**：任何能连到 agent 端口的进程都能调。

Java 侧的唯一权威实现在 `cn.aios.security.ServiceTokenProvider`：HS256、claim `svc`、
默认 5 分钟有效期、`svc ∈ {agent, server}`。本模块按**同一口径**校验，不引入第二套语义。

为什么用标准库而不是 PyJWT：这只是一次 HS256 验签（30 行），而多一个运行时依赖就多一处
「容器里没装」的失败面（本项目已因类似原因出过 `faster-whisper` 缺失的事故）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

ALG = "HS256"
SVCS = {"agent", "server"}

# 与 Java `ServiceJwtProperties.secret` 的默认值逐字相同。
# 生产必须用 AIOS_SERVICE_JWT_SECRET / SERVICE_JWT_SECRET 覆盖；留着它只影响本地开发。
DEV_SECRET = "aios-dev-service-jwt-secret-please-change"


class ServiceTokenError(ValueError):
    """令牌缺失/格式错/签名不符/过期/claim 非法 —— 一律 401，不区分具体原因给外部。"""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue(svc: str, secret: str, ttl_seconds: int = 300) -> str:
    """签发（测试与本地脚本用）。生产 token 由 Java 签发。"""
    if svc not in SVCS:
        raise ServiceTokenError(f"invalid svc: {svc}")
    if not secret:
        raise ServiceTokenError("empty secret")
    now = int(time.time())
    header = {"alg": ALG, "typ": "JWT"}
    payload = {"sub": svc, "svc": svc, "iat": now, "exp": now + int(ttl_seconds)}
    signing_input = (
        _b64e(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
        + "."
        + _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    )
    sig = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return signing_input + "." + _b64e(sig)


def verify(token: str, secret: str, leeway: int = 30) -> str:
    """校验并返回 `svc`；任何不合规抛 ``ServiceTokenError``。

    安全要点（逐条都是攻击面）：
      - **算法钉死**：header.alg 必须逐字等于 HS256。拒绝 `none`、拒绝 RS256 混淆
        （否则攻击者可把公钥当 HMAC 密钥，即经典的 alg confusion）。
      - **常量时间比较**：`hmac.compare_digest`，不用 `==`。
      - **exp 必填**：没有 exp 的令牌等价于永不过期，一律拒绝（Java 侧总会带）。
      - **svc 白名单**：只接受 agent / server，避免「任意服务名」都能进。
    """
    if not token:
        raise ServiceTokenError("missing token")
    if not secret:
        # 配置缺失时**失败关闭**：宁可 401 也不放行（旧行为是根本不校验）。
        raise ServiceTokenError("service jwt secret not configured")
    parts = token.split(".")
    if len(parts) != 3:
        raise ServiceTokenError("malformed token")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64d(header_b64))
        payload = json.loads(_b64d(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise ServiceTokenError(f"bad json segment: {exc}") from exc
    if not isinstance(header, dict) or header.get("alg") != ALG:
        raise ServiceTokenError(f"unsupported alg: {header.get('alg') if isinstance(header, dict) else '?'}")
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual = _b64d(sig_b64)
    except Exception as exc:  # noqa: BLE001
        raise ServiceTokenError(f"bad signature encoding: {exc}") from exc
    if not hmac.compare_digest(expected, actual):
        raise ServiceTokenError("signature mismatch")
    if not isinstance(payload, dict):
        raise ServiceTokenError("bad payload")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        raise ServiceTokenError("missing exp")
    if time.time() > float(exp) + leeway:
        raise ServiceTokenError("token expired")
    svc = payload.get("svc") or payload.get("sub")
    if svc not in SVCS:
        raise ServiceTokenError(f"invalid svc claim: {svc}")
    return str(svc)


def bearer_value(header_value: str | None) -> str:
    """从 `Authorization: Bearer xxx` 取出 token；不合格式返回空串。"""
    if not header_value:
        return ""
    value = header_value.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def payload_of(token: str) -> dict[str, Any]:
    """只解不验（诊断/日志用，**不得**用于鉴权判断）。"""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        obj = json.loads(_b64d(parts[1]))
        return obj if isinstance(obj, dict) else {}
    except Exception:  # noqa: BLE001
        return {}
