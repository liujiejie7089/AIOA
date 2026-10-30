# -*- coding: utf-8 -*-
"""调用方身份模型。

原来的双模式/群机器人数据模型（{@code Connection} / {@code TenantConfig} / 模式常量）
随连接器一并删除（2026-10-30，见 docs/64 §9.7）；现在只剩 {@code Identity}：
它是 hub 侧所有 REST/工具调用的身份载体，与具体连接器无关。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Identity:
    """调用方身份（由 Java `/api/v1/auth/me` 判定，Python 侧不持有密钥）。"""

    tenant_id: str
    user_id: str
    username: str = ""
    roles: list[str] = field(default_factory=list)
    mock: bool = False

    @property
    def is_admin(self) -> bool:
        return any(r in self.roles for r in ("ROLE_ADMIN", "ROLE_TENANT_ADMIN"))
