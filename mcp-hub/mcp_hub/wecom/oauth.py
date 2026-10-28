# -*- coding: utf-8 -*-
"""方案A：企微 OAuth（snsapi_privateinfo）辅助。

两条分支（UA 分流）：
- 企微内置浏览器（UA 含 wxwork / MicroMessenger）：网页授权
  open.weixin.qq.com/connect/oauth2/authorize?scope=snsapi_privateinfo&agentid=...
  回调 code 可换 userid + user_ticket → getuserdetail 拿姓名/biz_mail。
- 其它环境（PC 浏览器等）：扫码 open.work.weixin.qq.com/wwopen/sso/qrConnect，
  只能拿 userid（无 user_ticket/biz_mail），仅作兜底。

state：一次性、10 分钟 TTL，落 wecom_oauth_state 表（store 管）。
access_token：进程内缓存，剩余不足 5 分钟即刷新（防 45009 频率限制）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from urllib.parse import urlencode

from . import store
from .models import TOKEN_REFRESH_MARGIN_SECONDS

logger = logging.getLogger("mcp_hub.wecom")

OAUTH_AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"
QR_CONNECT_URL = "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
SCOPE = "snsapi_privateinfo"

# 企微内置浏览器 UA 特征（命中即走网页授权分支）
_BUILTIN_UA_MARKS = ("wxwork", "micromessenger")


def is_wecom_builtin(user_agent: str | None) -> bool:
    ua = (user_agent or "").lower()
    return any(m in ua for m in _BUILTIN_UA_MARKS)


def user_agent_of(ctx) -> str:
    try:
        return ctx.request_context.request.headers.get("user-agent", "") or ""
    except Exception:
        return ""


def build_authorize_url(corp_id: str, agent_id: str, redirect_uri: str, state: str) -> str:
    """网页授权 URL（snsapi_privateinfo，固定 scope，不用 snsapi_base）。"""
    params = {
        "appid": corp_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "agentid": agent_id,
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}#wechat_redirect"


def build_qr_connect_url(corp_id: str, agent_id: str, redirect_uri: str, state: str) -> str:
    """PC 扫码 URL（兜底分支，仅 userid）。"""
    params = {
        "appid": corp_id,
        "agentid": agent_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{QR_CONNECT_URL}?{urlencode(params)}"


def redirect_uri_of(cfg) -> str:
    """回调地址：配置优先，否则按 hub 外部地址推导。"""
    if cfg.redirect_uri:
        return cfg.redirect_uri
    base = os.environ.get("WECOM_PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        raise ValueError("租户未配置 redirectUri，且未设置 WECOM_PUBLIC_BASE_URL，无法构造授权链接")
    return f"{base}/api/v1/wecom/oauth/callback"


# ---------- state ----------


async def issue_state(tenant_id: str, user_id: str, mode: str, payload: dict) -> str:
    return await store.issue_state(tenant_id, user_id, mode, payload)


async def consume_state(state: str) -> dict | None:
    return await store.consume_state(state)


# ---------- access_token 进程内缓存 ----------

_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = asyncio.Lock()


async def get_access_token(corp_id: str, secret: str, fetcher) -> str:
    """fetcher(corp_id, secret) -> (token, expires_in)，由 wecom_api 注入（mock/real）。"""
    cache_key = corp_id
    async with _token_lock:
        hit = _token_cache.get(cache_key)
        now = time.time()
        if hit and hit[1] - TOKEN_REFRESH_MARGIN_SECONDS > now:
            return hit[0]
        token, expires_in = await fetcher(corp_id, secret)
        _token_cache[cache_key] = (token, now + max(int(expires_in) - 60, 60))
        return token


def reset_token_cache() -> None:
    _token_cache.clear()
