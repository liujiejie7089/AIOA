# -*- coding: utf-8 -*-
"""连接器声明模型：一个连接器 = 一组元数据 + 一份凭证字段 schema + 工具计数。

设计目标（对齐 WorkBuddy 的连接器抽象）：
- 管理端不需要认识具体连接器，只要按 schema 渲染表单；
- 新增第三方应用 = 注册一份 manifest + 提供一个工具实现，不改动网关主体；
- 凭证字段的「是否敏感」「是否必填」由声明决定，代码里不出现任何具体字段名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# 授权形态：决定「谁来配凭据」
AUTH_OAUTH2 = "OAUTH2"        # 管理员配应用凭据，用户走 OAuth 授权
AUTH_CREDENTIAL = "CREDENTIAL"  # 用户自填凭据（如邮箱授权码），无应用级配置
AUTH_API_KEY = "API_KEY"      # 管理员配 API Key，服务端直连
AUTH_QR = "QR"                # 用户扫码绑定（官方 CLI 通道，docs/64）

_PROVIDERS = {"wecom", "vault", "none"}


@dataclass(frozen=True)
class CredentialField:
    """一个凭证字段的声明。type 仅用于前端渲染，不参与服务端校验。"""

    name: str
    label: str
    type: str = "text"          # text | password | email | url | number
    required: bool = True
    sensitive: bool = False     # true ⇒ 永不明文回显，只回「已配置」
    placeholder: str = ""
    help: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "sensitive": self.sensitive,
            "placeholder": self.placeholder,
            "help": self.help,
        }


@dataclass(frozen=True)
class ConnectorManifest:
    """连接器清单项。provider 决定凭证落在哪：wecom=企微原生存储、vault=通用保险库、none=无应用级凭据。"""

    code: str
    name: str
    group: str
    auth_mode: str
    provider: str
    summary: str = ""
    help_url: str = ""
    credential_fields: tuple[CredentialField, ...] = field(default_factory=tuple)
    tool_count: int = 0
    # 工具来源。两者都为 None ⇒ 本连接器由 Java 侧实装，hub 只做代理转发（如 qq_mail）。
    # 传了 factory ⇒ 原生实装（工具逻辑在 hub 的 Python 侧，如 wechat_work）。
    # 用「工厂函数」而不是模块常量，既避免 builtin/probe 认识具体连接器，
    # 也避免 registry 在导入期就把 wecom.server 拉起来（省掉一层潜在循环依赖）。
    server_factory: Callable[[], Any] | None = field(default=None, compare=False, repr=False)
    tool_catalog: Callable[[], list[dict]] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("连接器 code 不能为空")
        if self.provider not in _PROVIDERS:
            raise ValueError(f"未知 provider: {self.provider}（允许 {sorted(_PROVIDERS)}）")
        if self.auth_mode not in (AUTH_OAUTH2, AUTH_CREDENTIAL, AUTH_API_KEY, AUTH_QR):
            raise ValueError(f"未知 auth_mode: {self.auth_mode}")
        if self.provider == "none" and self.credential_fields:
            raise ValueError("provider=none 的连接器不应声明应用级凭证字段")
        names = [f.name for f in self.credential_fields]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.code} 的凭证字段重名")
        if (self.server_factory is None) != (self.tool_catalog is None):
            raise ValueError(
                f"{self.code}：原生实现必须同时提供 server_factory 与 tool_catalog（否则探测与实装会漂移）"
            )

    @property
    def is_native(self) -> bool:
        """True ⇒ 工具逻辑在本进程；False ⇒ 代理转发给 Java。"""
        return self.server_factory is not None

    @property
    def required_fields(self) -> tuple[CredentialField, ...]:
        return tuple(f for f in self.credential_fields if f.required)

    def schema(self) -> list[dict[str, Any]]:
        return [f.public() for f in self.credential_fields]

    def public(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "group": self.group,
            "authMode": self.auth_mode,
            "provider": self.provider,
            "summary": self.summary,
            "helpUrl": self.help_url,
            "toolCount": self.tool_count,
            "credentialFields": self.schema(),
        }
