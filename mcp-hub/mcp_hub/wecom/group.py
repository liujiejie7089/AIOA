# -*- coding: utf-8 -*-
"""企微群机器人（消息推送）发送实现。

为什么单独一条通道：自建应用的业务接口要求「企业可信 IP」，而企微的硬规则是
「配置可信 IP 前，必须先设置可信域名或接收消息服务器 URL」，两者都要求备案域名。
群机器人只认 webhook 里的 key —— 不要求可信 IP、域名、企业认证（官方 path/91770
只列了两条限制：仅群消息、20 条/分钟）。实测同一出口 IP：自建应用 60020，webhook 正常。

纪律：
- 绝不记录完整 webhook（key 即凭证）；日志只打尾 4 位。
- 失败必须把企微的 errcode/errmsg 原样带出，不吞成"成功"。
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger("mcp_hub.wecom")

WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


class _RedactKeyFilter(logging.Filter):
    """把日志里出现的 `key=<凭证>` 抹成 `key=***`。

    <p>为什么需要：我们自己的 logger 只打尾 4 位，但 **httpx 会在 INFO 级别把完整请求 URL
    打出来**（`HTTP Request: POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=8fc8e8c4-… "200 OK"`），
    key 等于凭证，于是「守纪律的代码 + 不守纪律的依赖」把凭据漏进了 logs/mcp-hub.log。
    2026-10-30 实测抓到（验收时正是靠日志取第二源才看到这一行）。</p>

    <p>替代方案为什么不行：把 httpx 整体降到 WARNING 会同时丢掉所有 HTTP 状态码诊断；
    只在本请求前后临时改级别，则并发请求会互相串级。过滤器只改「消息文本」，不改变级别，
    对并发安全，且顺带把 `access_token=` 也 Cover（企微自建应用接口的同款风险）。</p>
    """

    _PATTERN = re.compile(r"(key|access_token|corpsecret|secret)=[^&\s\"']+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:      # 占位符与参数不匹配时 getMessage 会抛，不能因此吞日志
            return True
        cleaned = self._PATTERN.sub(lambda m: f"{m.group(1)}=***", msg)
        if cleaned != msg:
            record.msg = cleaned
            record.args = ()
        return True


def _install_redaction() -> None:
    """幂等挂载（模块被多次 import 也只挂一次）。"""
    hx = logging.getLogger("httpx")
    if not any(isinstance(f, _RedactKeyFilter) for f in hx.filters):
        hx.addFilter(_RedactKeyFilter())


_install_redaction()

# errcode -> 人话（只列真机最常见的几个）
ERRCODE_HINTS = {
    93000: "webhook key 无效：可能建的是「智能机器人」（无 webhook），或复制了示例地址",
    45009: "超过 20 条/分钟，稍后重试",
    45033: "机器人已被移出群或已停用",
    40008: "消息内容过长（text 限 2048 字节）",
}


def _tail(key: str) -> str:
    return f"…{key[-4:]}" if key and len(key) > 4 else "(空)"


async def send(webhook_key: str, msgtype: str, content: str,
               at_mobiles: list[str] | None = None, at_all: bool = False) -> dict:
    """发一条群消息。返回 {ok, errcode, errmsg}，不抛异常（由调用方转成 isError）。"""
    payload: dict
    if msgtype == "markdown":
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
    else:
        payload = {"msgtype": "text", "text": {"content": content}}
        mobiles = [m.strip() for m in (at_mobiles or []) if m and m.strip()]
        if mobiles:
            payload["text"]["mentioned_mobile_list"] = mobiles

    try:
        # trust_env=False：本机有 http_proxy，走代理会让出口变成代理地址（也可能是 IPv6）
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(f"{WEBHOOK_URL}?key={webhook_key}", json=payload)
    except httpx.HTTPError as e:
        logger.info("wecom_group send ok=false net=%s key=%s", type(e).__name__, _tail(webhook_key))
        return {"ok": False, "errcode": None,
                "errmsg": f"连接企微失败：{type(e).__name__}"}

    try:
        body = resp.json()
    except Exception:
        logger.info("wecom_group send ok=false http=%s key=%s", resp.status_code, _tail(webhook_key))
        return {"ok": False, "errcode": None,
                "errmsg": f"企微返回无法解析（HTTP {resp.status_code}）"}

    code = body.get("errcode")
    ok = code == 0
    logger.info("wecom_group send ok=%s errcode=%s key=%s", ok, code, _tail(webhook_key))
    if ok:
        return {"ok": True, "errcode": 0, "errmsg": "ok"}
    hint = ERRCODE_HINTS.get(code)
    errmsg = body.get("errmsg") or "未知错误"
    return {"ok": False, "errcode": code,
            "errmsg": f"{errmsg}（{hint}）" if hint else errmsg}
