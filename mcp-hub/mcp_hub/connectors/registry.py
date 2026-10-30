# -*- coding: utf-8 -*-
"""连接器注册表（唯一发现入口）。

纪律：
- 本表是「连接器」的唯一注册点，`builtin.py` / `probe.py` 不再认识任何具体 code
  （历史遗留的 `NATIVE_SERVERS` 硬编码映射已删除）。
- 工具 schema 不在本表重复定义：原生型取连接器自身的 tool_catalog（如 wecom/catalog.py），
  代理型取 `specs.BUILTIN_SERVERS`。两处各自做事实源，避免同一份 schema 抄两遍而漂移。
- 内置连接器在此登记；第三方扩展可在启动后调用 `register()` 追加（同一 code 重复注册即报错，
  要替换请显式先 `unregister()`，避免静默覆盖）。
- 顺序稳定（按 group、name 排序），便于管理端与哨兵做确定性断言。
"""

from __future__ import annotations

import logging

from .. import specs
from ..wecom import catalog as wecom_catalog
from .manifest import AUTH_API_KEY, AUTH_CREDENTIAL, AUTH_OAUTH2, ConnectorManifest, CredentialField

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


def _build_wecom_server():
    """惰性导入：registry 被 admin_api 导入时不连带拉起 wecom 的运行时依赖。"""
    from ..wecom import server as wecom_server

    return wecom_server.build_server()


def _build_wecom_group_server():
    from ..wecom import group_server

    return group_server.build_server()


def _register_builtin() -> None:
    # 企业微信：管理员配应用凭据（corpId/agentId/corpSecret），用户走 OAuth。
    # 凭据落在 wecom 自己的加密表（provider=wecom），历史数据与 20 项哨兵不受影响。
    register(
        ConnectorManifest(
            code=wecom_catalog.SERVER_CODE,
            name=wecom_catalog.SERVER_NAME,
            group="协作与办公",
            auth_mode=AUTH_OAUTH2,
            provider="wecom",
            summary="以自建应用身份发消息、查通讯录、拿成员身份；可叠加企业邮箱（IMAP/SMTP）",
            help_url="https://developer.work.weixin.qq.com/document/path/90665",
            credential_fields=(
                CredentialField(name="corpId", label="企业ID（CorpID）", required=True,
                                placeholder="wwxxxxxxxxxxxxxxxx",
                                help="管理端 → 我的企业 → 企业信息 → 企业ID"),
                CredentialField(name="agentId", label="应用 AgentId", required=True,
                                placeholder="1000002",
                                help="管理端 → 应用管理 → 点进自建应用 → AgentId"),
                CredentialField(name="corpSecret", label="应用 Secret", type="password",
                                required=True, sensitive=True,
                                help="同一页面点「查看」；只存密文，永不回显"),
                CredentialField(name="redirectUri", label="OAuth 回调地址", type="url",
                                required=False, placeholder="https://你的域名/api/v1/wecom/oauth/callback",
                                help="可留空：留空则按 env WECOM_PUBLIC_BASE_URL + /api/v1/wecom/oauth/callback 推导；"
                                     "域名必须与企微应用「OAuth2.0 网页授权可信域名」一致"),
            ),
            tool_count=wecom_catalog.tool_count(),
            server_factory=_build_wecom_server,
            tool_catalog=lambda: wecom_catalog.TOOLS,
        )
    )
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
    # 企业微信群机器人：唯一不要求可信 IP / 域名的企微通道，只认 webhook key。
    # 凭据落通用保险库（provider=vault，租户级），管理员填、AI 用。
    from ..wecom import group_server

    register(
        ConnectorManifest(
            code=group_server.SERVER_CODE,
            name=group_server.SERVER_NAME,
            group="协作与办公",
            auth_mode=AUTH_API_KEY,
            provider="vault",
            summary="往企业微信群发消息（群机器人 Webhook）；不要求可信 IP、域名、企业认证",
            help_url="https://developer.work.weixin.qq.com/document/path/91770",
            credential_fields=(
                CredentialField(name="webhookKey", label="群机器人 Webhook Key", type="password",
                                required=True, sensitive=True,
                                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                                help="企微群 → 右上角 … → 消息推送/群机器人 → 复制 Webhook 地址，"
                                     "取 key= 之后那段（36 位 UUID）。只存密文，永不回显"),
            ),
            tool_count=group_server.tool_count(),
            server_factory=_build_wecom_group_server,
            tool_catalog=lambda: group_server.TOOLS,
        )
    )


_register_builtin()
