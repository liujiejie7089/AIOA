# -*- coding: utf-8 -*-
"""企业微信双模式连接器：数据模型与模式常量。

模式定义（与 docs/60 一致）：
- A  ：企微 App 内 OAuth 网页授权（scope=snsapi_privateinfo），获得 userid / biz_mail 身份；
       消息与通讯录工具是应用级 API（access_token），授权态的价值是身份与审计。
- B  ：企业邮箱客户端专用密码绑定，获得 IMAP/SMTP 邮件收发能力。
- AB ：两种都绑，工具全集可用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODE_A = "A"
MODE_B = "B"
MODE_AB = "AB"
MODES = (MODE_A, MODE_B, MODE_AB)

STATUS_CONNECTED = "CONNECTED"
STATUS_NEED_AUTH = "NEED_AUTH"
STATUS_DISCONNECTED = "DISCONNECTED"

# 授权形态（对齐 Octop catalog 的 auth_kind 命名）
AUTH_KIND_OAUTH = "oauth2_privateinfo"
AUTH_KIND_MAIL = "imap_app_password"
AUTH_KINDS = (AUTH_KIND_OAUTH, AUTH_KIND_MAIL)

# OAuth state 一次性有效期（分钟）
STATE_TTL_MINUTES = 10
# access_token 缓存刷新阈值（秒）：剩余不足即刷新，防 45009 频率限制
TOKEN_REFRESH_MARGIN_SECONDS = 300


@dataclass
class Identity:
    """调用方身份。tenant_id + user_id 是连接态与租户配置的存储主键。"""

    tenant_id: str
    user_id: str
    username: str = ""
    roles: list[str] = field(default_factory=list)
    mock: bool = False

    @property
    def is_admin(self) -> bool:
        return any(r in self.roles for r in ("ROLE_ADMIN", "ROLE_TENANT_ADMIN"))


@dataclass
class TenantConfig:
    """租户级连接器配置（corpId/secret/agentid），密文存储，掩码视图外不下发。"""

    tenant_id: str
    corp_id: str
    corp_secret: str
    agent_id: str
    redirect_uri: str | None = None
    updated_by: str | None = None

    def masked(self) -> dict:
        from .crypto import mask

        return {
            "tenantId": self.tenant_id,
            "corpId": mask(self.corp_id),
            "corpSecret": mask(self.corp_secret),
            "agentId": mask(self.agent_id),
            "redirectUri": self.redirect_uri,
            "configured": True,
        }


@dataclass
class Connection:
    """用户级连接态。credential 为解密后的内存对象，绝不直接外泄。

    注意 mode 默认空串：新行不代表任何模式，由 merge_mode 按实际绑定写入
    （曾经默认 MODE_AB 导致「只绑了 A 却显示 AB」的 bug）。
    """

    tenant_id: str
    user_id: str
    mode: str = ""
    status: str = STATUS_DISCONNECTED
    account_label: str | None = None
    a_credential: dict[str, Any] | None = None
    b_credential: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # 仅内存：本次操作是否成功把连接态同步到 Java（真相源）。不落库、不参与比较，
    # 用于把「本地连上了但 manifest 闸门不知道」这件事显式暴露给调用方（docs/63 §9.2）。
    synced: bool | None = field(default=None, compare=False, repr=False)

    def public_view(self) -> dict:
        """脱敏视图：H5 与管理端只拿这个，绝不包含任何凭据明文/密文。"""
        view: dict[str, Any] = {
            "code": "wechat_work",
            "mode": self.mode,
            "status": self.status,
            "accountLabel": self.account_label,
        }
        if self.a_credential:
            view["a"] = {
                "userid": self.a_credential.get("userid"),
                "name": self.a_credential.get("name"),
                "bizMail": self.a_credential.get("biz_mail"),
                "boundAt": self.a_credential.get("bound_at"),
                # 敏感字段是否真的授权到手（false ⇒ 只有 userid，界面上别把空邮箱当正常）
                "sensitiveAuthorized": self.a_credential.get("sensitive_authorized"),
                "sensitiveNote": self.a_credential.get("sensitive_note"),
            }
        if self.b_credential:
            view["b"] = {
                "email": self.b_credential.get("email"),
                "boundAt": self.b_credential.get("bound_at"),
            }
        if self.synced is not None:
            # false ⇒ 本地已连上但 Java 侧未收到 ⇒ manifest 闸门看不到本次连接（必须让调用方知道）
            view["stateSynced"] = self.synced
        return view
