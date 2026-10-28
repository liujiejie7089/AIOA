# -*- coding: utf-8 -*-
"""方案A 后端：企微开放 API 客户端（Mock + 实装）。

Mock（WECOM_MOCK=1）：内置一家虚拟企业（corp=mock-corp / agent=1000002 / 两名成员），
授权码 "mock-code-<userid>" 换身份，让 E2E 不依赖真机与真实企业。

实装（WECOM_MOCK=0）：qyapi.weixin.qq.com 四件套——
gettoken / user/getuserinfo（换 code）/ auth/getuserdetail（换 biz_mail）/ message/send；
错误码映射成可读中文（排查清单 docs/60 §七 同源）。

出口双保险（2026-10-28 实测坑）：企微「企业可信IP」只支持 IPv4（官方文档明确暂不
支持 IPv6），而本机双栈 + anyio Happy Eyeballs 优先 IPv6、沙箱系统代理出口也是
IPv6 —— 一旦走 IPv6，企微侧看到的源 IP 永远加不进白名单，所有业务接口恒定 60020。
故：httpx 客户端 trust_env=False（绕开系统代理），并对 qyapi 域名强制 AF_INET 解析。
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Protocol

import httpx

from . import store

logger = logging.getLogger("mcp_hub.wecom")

QY_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

ERRCODE_REASONS = {
    40001: "access_token 无效或过期（secret 可能配错）",
    40003: "redirect_uri 不在企微管理端可信域名内",
    40013: "corpId 不存在或格式错误（到管理端-我的企业-企业ID 核对）",
    40014: "access_token 格式不合法",
    40029: "授权 code 无效或已使用（code 仅一次性且 5 分钟内有效）",
    41001: "缺少 access_token",
    45009: "接口调用频率超限（access_token 需缓存，勿每次现取）",
    60011: "应用无该接口权限（检查管理端-应用-API 权限，或通讯录可见范围）",
    60020: "请求 IP 不在应用「可信IP」内（管理端-应用-可信IP 添加入口 IP；仅支持 IPv4，勿走 IPv6 或代理出口）",
    301002: "corpId 错误（到管理端-我的企业-企业ID 核对）",
    301025: "corpSecret 错误（gettoken 被拒）",
    81013: "user_ticket 无效或已过期（5 分钟内有效）",
    81014: "非本企业成员",
}


class WeComApiError(RuntimeError):
    def __init__(self, reason: str, errcode: int | None = None):
        super().__init__(reason)
        self.errcode = errcode
        self.reason = reason


class WeComApi(Protocol):
    async def get_access_token(self, corp_id: str, secret: str) -> tuple[str, int]: ...
    async def exchange_code(self, access_token: str, code: str) -> dict[str, Any]: ...
    async def get_user_detail(self, access_token: str, user_ticket: str) -> dict[str, Any]: ...
    async def send_text(self, access_token: str, agent_id: str, touser: str, content: str) -> dict[str, Any]: ...
    async def search_contact(self, access_token: str, query: str, limit: int) -> list[dict[str, Any]]: ...


# ---------- Mock ----------

_MOCK_MEMBERS = [
    {"userid": "zhangsan", "name": "张三", "biz_mail": "zhangsan@mock-corp.com",
     "department": [1], "position": "产品经理", "mobile": "13800000001"},
    {"userid": "lisi", "name": "李四", "biz_mail": "lisi@mock-corp.com",
     "department": [1], "position": "工程师", "mobile": "13800000002"},
    {"userid": "wangwu", "name": "王五", "biz_mail": "wangwu@mock-corp.com",
     "department": [2], "position": "设计师", "mobile": "13800000003"},
]
_MOCK_TICKETS = {"mock-code-zhangsan": "zhangsan", "mock-code-lisi": "lisi", "mock-code-wangwu": "wangwu"}


class MockWeComApi:
    """虚拟企业：任意 mock-code-<userid> 均视为合法授权码。"""

    async def get_access_token(self, corp_id: str, secret: str) -> tuple[str, int]:
        if secret != "mock-secret":
            raise WeComApiError(ERRCODE_REASONS[301025], 301025)
        return ("mock-access-token", 7200)

    async def exchange_code(self, access_token: str, code: str) -> dict[str, Any]:
        if not code.startswith("mock-code-"):
            raise WeComApiError(ERRCODE_REASONS[40029], 40029)
        userid = code[len("mock-code-"):]
        member = next((m for m in _MOCK_MEMBERS if m["userid"] == userid), None)
        if member is None:
            raise WeComApiError(ERRCODE_REASONS[81014], 81014)
        return {"userid": userid, "user_ticket": f"mock-ticket-{userid}"}

    async def get_user_detail(self, access_token: str, user_ticket: str) -> dict[str, Any]:
        if not user_ticket.startswith("mock-ticket-"):
            raise WeComApiError(ERRCODE_REASONS[81013], 81013)
        userid = user_ticket[len("mock-ticket-"):]
        member = next((m for m in _MOCK_MEMBERS if m["userid"] == userid), None)
        if member is None:
            raise WeComApiError(ERRCODE_REASONS[81014], 81014)
        return dict(member)

    async def send_text(self, access_token: str, agent_id: str, touser: str, content: str) -> dict[str, Any]:
        if not content:
            raise WeComApiError("消息正文不能为空")
        known = {m["userid"] for m in _MOCK_MEMBERS}
        for uid in touser.split("|"):
            if uid and uid not in known:
                raise WeComApiError(f"成员不存在：{uid}")
        return {"errcode": 0, "errmsg": "ok", "mock_sent_to": touser}

    async def search_contact(self, access_token: str, query: str, limit: int) -> list[dict[str, Any]]:
        q = (query or "").lower()
        hits = [
            m for m in _MOCK_MEMBERS
            if q in m["name"].lower() or q in m["userid"].lower() or q in m["biz_mail"].split("@")[0].lower()
        ]
        return [
            {"userid": m["userid"], "name": m["name"], "bizMail": m["biz_mail"],
             "position": m["position"], "department": m["department"]}
            for m in hits[: max(1, min(limit, 30))]
        ]


# ---------- 实装 ----------

# 企微「企业可信IP」仅支持 IPv4：双栈主机上 anyio 的 Happy Eyeballs 优先 IPv6，
# 走 IPv6 时企微侧看到的源 IP 永远加不进白名单 → 业务接口恒定 60020。
# 这里对 qyapi 域名强制 AF_INET 解析（P2 邮件实装时把 exmail 域名一并加进来）。
_IPV4_ONLY_SUFFIXES = ("qyapi.weixin.qq.com",)
_IPV4_ONLY_SUFFIXES_B = tuple(s.encode("ascii") for s in _IPV4_ONLY_SUFFIXES)
_ipv4_dns_installed = False


def _install_ipv4_only_dns() -> None:
    """包装 socket.getaddrinfo：qyapi 域名的解析强制 family=AF_INET。幂等，可重复调用。

    实测依据（2026-10-28）：asyncio 经 run_in_executor 调 socket.getaddrinfo 时
    六个参数全按位置传（host, port, family, type, proto, flags），故包装函数同时
    兼容位置/关键字两种传法；anyio 只用解析出的 IP，端口用原始 remote_port，
    因此替换 family 不会影响连接端口。
    """
    global _ipv4_dns_installed
    if _ipv4_dns_installed:
        return
    original = socket.getaddrinfo

    def _ipv4_only(host, port=None, family=0, type=0, proto=0, flags=0, *extra):
        if isinstance(host, str) and host.endswith(_IPV4_ONLY_SUFFIXES):
            family = socket.AF_INET
        elif isinstance(host, bytes) and host.endswith(_IPV4_ONLY_SUFFIXES_B):
            family = socket.AF_INET
        return original(host, port, family, type, proto, flags, *extra)

    socket.getaddrinfo = _ipv4_only
    _ipv4_dns_installed = True


class RealWeComApi:
    def __init__(self) -> None:
        _install_ipv4_only_dns()
        self._client = httpx.AsyncClient(timeout=15.0, trust_env=False)

    @staticmethod
    def _check(resp_json: dict, what: str) -> dict:
        errcode = resp_json.get("errcode")
        if errcode not in (0, None):
            raise WeComApiError(ERRCODE_REASONS.get(errcode, f"{what}失败：errcode={errcode}"), errcode)
        return resp_json

    async def get_access_token(self, corp_id: str, secret: str) -> tuple[str, int]:
        resp = await self._client.get(
            f"{QY_BASE}/gettoken", params={"corpid": corp_id, "corpsecret": secret}
        )
        data = self._check(resp.json(), "gettoken")
        return data["access_token"], int(data.get("expires_in", 7200))

    async def exchange_code(self, access_token: str, code: str) -> dict[str, Any]:
        resp = await self._client.get(
            f"{QY_BASE}/user/getuserinfo",
            params={"access_token": access_token, "code": code},
        )
        data = self._check(resp.json(), "code 换身份")
        return {"userid": data.get("userid") or data.get("UserId"), "user_ticket": data.get("ticket")}

    async def get_user_detail(self, access_token: str, user_ticket: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"{QY_BASE}/auth/getuserdetail",
            params={"access_token": access_token},
            json={"user_ticket": user_ticket},
        )
        data = self._check(resp.json(), "getuserdetail")
        return {
            "userid": data.get("userid"),
            "name": data.get("name"),
            "biz_mail": data.get("biz_mail"),
            "position": data.get("position"),
            "department": data.get("department"),
        }

    async def send_text(self, access_token: str, agent_id: str, touser: str, content: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"{QY_BASE}/message/send",
            params={"access_token": access_token},
            json={
                "touser": touser,
                "msgtype": "text",
                "agentid": int(agent_id),
                "text": {"content": content},
            },
        )
        return self._check(resp.json(), "发送消息")

    async def search_contact(self, access_token: str, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await self._client.get(
            f"{QY_BASE}/user/list",
            params={"access_token": access_token, "department_id": 1, "fetch_child": 1},
        )
        data = self._check(resp.json(), "通讯录列表")
        q = (query or "").lower()
        out = []
        for u in data.get("userlist", []):
            name = str(u.get("name") or "").lower()
            uid = str(u.get("userid") or "").lower()
            alias = str(u.get("alias") or "").lower()
            if q in name or q in uid or q in alias:
                out.append({
                    "userid": u.get("userid"), "name": u.get("name"),
                    "bizMail": u.get("biz_mail"), "position": u.get("position"),
                    "department": u.get("department"),
                })
                if len(out) >= max(1, min(limit, 30)):
                    break
        return out


_backend: WeComApi | None = None


def get_backend() -> WeComApi:
    global _backend
    if _backend is None:
        _backend = MockWeComApi() if store.is_mock() else RealWeComApi()
    return _backend
