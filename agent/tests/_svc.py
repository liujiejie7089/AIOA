"""测试用的服务间令牌头。

为什么单独抽一个模块：`/internal/v1/*` 自 2026-10-18 起强制校验服务间令牌
（`app/main.py` 的 `_require_service_jwt`），于是**所有**打内部端点的用例都必须带票，
否则会集体 401。票的口径必须与生产一致（不是伪造一个 `Bearer x`）：直接调
`aioa_ai.security.service_jwt.issue` 用当前 settings 的同一个密钥签发。

文件名不以 `test_` 开头 —— pytest 不会把它当用例收集。
"""
from __future__ import annotations

from aioa_ai.config import settings
from aioa_ai.security.service_jwt import issue


def svc_headers(svc: str = "server", ttl: int = 300, secret: str | None = None) -> dict[str, str]:
    """按生产口径签一张票并包成请求头。"""
    return {"Authorization": "Bearer " + issue(svc, secret or settings.service_jwt_secret, ttl)}
