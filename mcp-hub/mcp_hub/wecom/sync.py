# -*- coding: utf-8 -*-
"""把用户连接态回写 Java（唯一真相源对齐）。

存在理由（docs/63 §9.2，2026-10-30 修）：
用户连接态原先存在**两个互不同步的地方** ——
- Java `connector_connection`：由 `WeComOAuthService.callback` 写，**`/api/v1/mcp/manifest` 的闸门读它**；
- hub `wecom_connection`：由本文件的调用方（`server.complete_oauth`）写，**工具执行读它**。

于是「用 MCP 的 connect 工具连上」这条路，Java 侧仍停在 NEED_AUTH ⇒ 下一轮 manifest 判未连接
⇒ 工具从模型手里消失（连上了反而不能用）。反向走 Java 回调则 hub 没有凭据 ⇒ 执行报「凭据缺失」。
本模块把 hub 侧的成功/断开同步过去，让两边同源。

纪律：
- **不回滚**：企微那边已授权成功，同步失败只告警、不撤销本地连接（否则用户白点一次）；
  但要把「未同步」暴露到工具结果/跳转参数里，绝不静默。
- **不抛异常**：状态同步是旁路，不能把用户授权搞挂。
- **三态，不要压成 bool**（2026-10-30 修）：`True`=已同步 / `False`=**真失败** /
  `None`=**按设计跳过**（mock 身份不是数据库主键、或本进程没配服务令牌）。
  压成 bool 的后果：dev 默认 `WECOM_MOCK=1` 下每次授权都算出 `state-unsynced`，
  把「正常跳过」当成故障报给用户（S4b 因此假失败），真正的失败反而被噪声淹没。
"""

from __future__ import annotations

import logging
import os

import httpx

from .. import service_jwt

logger = logging.getLogger("mcp_hub.wecom")

_warned_no_secret = False


def _base_url() -> str:
    return os.environ.get("AIOS_SERVER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _as_long(value) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _skip_reason(tenant_id, user_id) -> str | None:
    """返回「为什么不同步」；None 表示可以同步。"""
    if _as_long(tenant_id) is None or _as_long(user_id) is None:
        return "调用方身份不是数据库主键（mock 模式），跳过状态同步"
    if not service_jwt.configured():
        return f"未设置 {service_jwt.ENV_SECRET}，跳过状态同步"
    return None


async def _post(path: str, body: dict) -> bool:
    global _warned_no_secret
    try:
        token = service_jwt.issue()
    except service_jwt.ServiceTokenError as e:
        if not _warned_no_secret:
            logger.warning("%s（连接态不会同步到 Java，manifest 闸门将看不到本次连接）", e)
            _warned_no_secret = True
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            resp = await client.post(_base_url() + path, json=body,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        logger.warning("连接态同步失败（%s）：%s", path, type(e).__name__)
        return False
    if resp.status_code not in (200, 201):
        logger.warning("连接态同步被拒（%s）：HTTP %s %s", path, resp.status_code, resp.text[:200])
        return False
    return True


async def report_connected(tenant_id, user_id, code: str,
                           account_label: str | None,
                           credential: dict | None) -> bool | None:
    """告知 Java：该用户已在该连接器上完成授权（status=CONNECTED）。

    返回 True=已同步；False=同步失败（要暴露给用户）；None=按设计跳过（mock 身份/无密钥）。
    """
    reason = _skip_reason(tenant_id, user_id)
    if reason:
        logger.info("%s（tenant=%s user=%s）", reason, tenant_id, user_id)
        return None
    # 只传白名单字段：这是「用户已授权的身份」，不是密码；Java 侧会再加密一次。
    # 值统一转字符串（Java 侧是 Map<String,String>）：布尔要小写，否则前端会看到 "False"。
    cred: dict[str, str] = {}
    for k, v in (credential or {}).items():
        if v is None or v == "":
            continue
        cred[k] = ("true" if v else "false") if isinstance(v, bool) else str(v)
    return await _post(
        f"/internal/v1/connectors/{code}/connection",
        {
            "tenantId": _as_long(tenant_id),
            "userId": _as_long(user_id),
            "status": "CONNECTED",
            "accountLabel": account_label,
            "credential": cred,
        },
    )


async def report_disconnected(tenant_id, user_id, code: str) -> bool | None:
    """告知 Java：该用户已断开（status=NEED_AUTH + 清凭据）。三态同 report_connected。"""
    reason = _skip_reason(tenant_id, user_id)
    if reason:
        logger.info("%s（tenant=%s user=%s）", reason, tenant_id, user_id)
        return None
    return await _post(
        f"/internal/v1/connectors/{code}/connection/disconnect",
        {"tenantId": _as_long(tenant_id), "userId": _as_long(user_id)},
    )
