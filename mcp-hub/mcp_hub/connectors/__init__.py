# -*- coding: utf-8 -*-
"""通用连接器层：声明（manifest）→ 注册（registry）→ 凭据（vault）→ 管理面（admin_api）。

与 wecom/ 包的分工：
- wecom/ 是「企业微信」这一个连接器的完整实现（OAuth、邮件、闸门、图编排），继续保留；
- connectors/ 是「所有连接器」的公共骨架，企业微信只是其中一份 manifest（provider=wecom）。
新增第三方应用时，只需 registry.register(...) 一份 manifest + 提供工具实现，
不需要改动本包与网关路由。
"""

from . import admin_api, manifest, registry, vault  # noqa: F401

__all__ = ["admin_api", "manifest", "registry", "vault"]
