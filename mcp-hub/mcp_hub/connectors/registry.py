# -*- coding: utf-8 -*-
"""连接器注册表（唯一发现入口）。

纪律：
- 本表是「连接器」的唯一注册点，`builtin.py` / `probe.py` 不再认识任何具体 code
  （历史遗留的 `NATIVE_SERVERS` 硬编码映射已删除）。
- 工具 schema 不在本表重复定义：原生型取连接器自身的 tool_catalog（如 wecom_cli/catalog.py），
  代理型取 `specs.BUILTIN_SERVERS`。两处各自做事实源，避免同一份 schema 抄两遍而漂移。
- 内置连接器在此登记；第三方扩展可在启动后调用 `register()` 追加（同一 code 重复注册即报错，
  要替换请显式先 `unregister()`，避免静默覆盖）。
- 顺序稳定（按 group、name 排序），便于管理端与哨兵做确定性断言。
"""

from __future__ import annotations

import logging

from .. import specs
from .manifest import AUTH_CREDENTIAL, AUTH_QR, ConnectorManifest

logger = logging.getLogger("mcp_hub.connectors")

_MANIFESTS: dict[str, ConnectorManifest] = {}


def register(manifest: ConnectorManifest) -> ConnectorManifest:
    """登记一个连接器。重复 code 直接报错（宁可启动失败，也不要静默覆盖别人的连接器）。"""
    if manifest.code in _MANIFESTS:
        raise ValueError(f"连接器已存在：{manifest.code}（如需替换请先 unregister）")
    _MANIFESTS[manifest.code] = manifest
    logger.info("连接器已注册：%s（%s / %s）", manifest.code, manifest.auth_mode, manifest.provider)
    return manifest


def unregister(code: str) -> None:
    _MANIFESTS.pop(code, None)


def get(code: str) -> ConnectorManifest | None:
    return _MANIFESTS.get(code)


def all_manifests() -> list[ConnectorManifest]:
    return sorted(_MANIFESTS.values(), key=lambda m: (m.group, m.name, m.code))


def codes() -> list[str]:
    return [m.code for m in all_manifests()]


def tool_specs(code: str) -> "list[dict] | None":
    """统一工具目录（name / description / input_schema / read_only）。

    原生连接器读自身的 catalog；代理连接器读 `specs.BUILTIN_SERVERS`。
    调用方（builtin / probe）从此不需要知道某个 code 是原生还是代理。
    返回 None ⇒ 该连接器既没原生实现、specs 里也没有目录（属注册错误，调用方应报错而非静默）。
    """
    manifest = _MANIFESTS.get(code)
    if manifest is not None and manifest.tool_catalog is not None:
        return list(manifest.tool_catalog())
    spec = specs.BUILTIN_SERVERS.get(code)
    if spec is None:
        return None
    return list(spec["tools"])


def build_server(code: str):
    """按注册表构建单台 MCP 服务器；代理型返回 None（由 builtin 用通用代理工厂构建）。"""
    manifest = _MANIFESTS.get(code)
    if manifest is None or manifest.server_factory is None:
        return None
    return manifest.server_factory()


def reset() -> None:
    """仅供测试/哨兵：清空后重新登记内置连接器。"""
    _MANIFESTS.clear()
    _register_builtin()


def _build_wecom_cli_server():
    """企业微信（扫码）：官方 wecom-cli 原生实装，见 docs/64。"""
    from ..wecom_cli import server as wecom_cli_server

    return wecom_cli_server.build_server()


def _wecom_cli_catalog():
    from ..wecom_cli import catalog as wecom_cli_catalog_mod

    return wecom_cli_catalog_mod.TOOLS


def _register_builtin() -> None:
    # ⚠️ 2026-10-30：`wechat_work`（自建应用 + OAuth）与 `wecom_group`（群机器人 webhook）
    # 两个连接器已下线并**物理删除**（V103 停用 + docs/64 §9.7 删码）。企业微信只剩下面一个
    # 扫码连接器。不要把它们加回来：两条通道都要求备案域名 / 可信 IP，凭据又是租户级共享，
    # 与「一个人一个账号、各自只看自己绑定的企微数据」的产品前提冲突。
    # QQ 邮箱：无应用级凭据（config_keys 为空），用户自己填邮箱 + 客户端授权码。
    register(
        ConnectorManifest(
            code="qq_mail",
            name="QQ邮箱",
            group="邮箱",
            auth_mode=AUTH_CREDENTIAL,
            provider="none",
            summary="收发邮件（IMAP/SMTP）；凭据由每位用户自行填写，管理员无需配置",
            help_url="https://open.work.weixin.qq.com/help2/pc/19984",
            tool_count=specs.tool_count("qq_mail"),
        )
    )
    # 企业微信（扫码）：不碰自建应用，走官方 CLI 的「机器人 + 真人扫码」。
    # 一人一账号：每个用户的授权落在各自的 WECOM_CLI_CONFIG_DIR，互相不可见（docs/64）。
    # auth_mode=QR ⇒ 前端据 mode 开二维码弹层；provider=none ⇒ 没有应用级凭证字段，
    # 管理端不会出现配置表单。
    register(
        ConnectorManifest(
            code="wecom_cli",
            name="企业微信（扫码）",
            group="协作与办公",
            auth_mode=AUTH_QR,
            provider="none",
            summary="扫码绑定你自己的企业微信：查通讯录、看群消息、搜企业邮箱；不需要备案域名",
            help_url="https://github.com/WecomTeam/wecom-cli",
            tool_count=len(_wecom_cli_catalog()),
            server_factory=_build_wecom_cli_server,
            tool_catalog=_wecom_cli_catalog,
        )
    )


_register_builtin()
