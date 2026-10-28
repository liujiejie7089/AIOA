#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
企业微信双模式连接器 P0 验收哨兵（mock 模式，全链路真实协议，无 Java 依赖）。

链路（每一步都真打协议）：
  S1  MCP tools/list                 → 原生 13 工具目录（catalog 唯一事实源）
  S2  connection_status              → 未连接
  S3  PUT/GET tenant-config          → 落库 + 掩码视图（无明文 secret）
  S4  connect(mode=A)                → URL elicitation 下发 authorize URL（snsapi_privateinfo）
                                       回调接口接力落库 → 连接态 A + profile
  S4b 同一 state 二次回调            → 302 失败（state 一次性，防重放）
  S5  get_my_profile                 → mock 企业成员身份（userid + biz_mail）
  S6  mail_list_messages（A 模式）    → 闸门拒绝，文案指引导绑邮箱
  S7  send_text_message              → mock 应用级发送成功
  S8  contact_search                 → mock 通讯录搜索
  S9  connect(mode=B)                → 表单 elicitation + 探活 → 合并为 A+B
  S10 邮件闭环                       → list(3 封) → draft → send → Sent；requestId 幂等
  S11 authorize-url（普通 UA）       → qrConnect 兜底分支 URL 形态
  S12 伪造 state 回调                → 302 失败且连接态不被污染
  S13 disconnect(mode=B)             → 回到 A，邮件工具再被拒
  S14 disconnect()                   → 全断，profile 被拒
  S15 /internal/mcp/probe            → Java 信任前探测拿到的是原生 13 工具
  S16 /health                        → wechat_work 计数 = 13
  S17 DB 文件无明文                  → secret / 客户端密码 / state 均密文

用法：D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_wecom_dual_mode_p0.py
退出码 = 失败项数。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse

# 代理纪律：本机有 http_proxy，httpx 默认 trust_env 会把 127.0.0.1 代理出去（实测 502）
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

_MCP_HUB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-hub"))
if _MCP_HUB not in sys.path:
    sys.path.insert(0, _MCP_HUB)

_TMPDIR = tempfile.mkdtemp(prefix="wecom-p0-")
_PORT = int(os.environ.get("WECOM_P0_PORT", "0")) or None
BASE = f"http://127.0.0.1:{_PORT}"
MCP_URL = f"{BASE}/mcp/wechat_work"

os.environ["WECOM_MOCK"] = "1"
os.environ["WECOM_DB_PATH"] = os.path.join(_TMPDIR, "wecom.db")
os.environ["WECOM_CONNECT_WAIT_SECONDS"] = "15"

CORP_ID = "mock-corp"
CORP_SECRET = "mock-secret"
AGENT_ID = "1000002"
MOCK_USERID = "zhangsan"
MOCK_EMAIL = f"{MOCK_USERID}@{CORP_ID}.com"
MOCK_PWD = f"pwd-{MOCK_EMAIL}"

HEADERS = {
    "Authorization": "Bearer p0-test-token",
    "X-Wecom-Mock-User": json.dumps({"tenantId": "t-p0", "userId": "u-p0", "roles": ["ROLE_TENANT_ADMIN"]}),
    "User-Agent": "wxwork",  # 命中企微内置浏览器 → 走网页授权分支
}

EXPECTED_TOOLS = [
    "connect", "disconnect", "connection_status",
    "check_connection", "get_my_profile", "send_text_message", "contact_search",
    "mail_list_folders", "mail_list_messages", "mail_read_message",
    "mail_search_messages", "mail_create_draft", "mail_send_draft",
]

RESULTS: list[tuple[str, bool, str]] = []
CAPTURED: dict = {}


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (" —— " + detail if detail else ""))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = _PORT or _free_port()
BASE = f"http://127.0.0.1:{PORT}"
MCP_URL = f"{BASE}/mcp/wechat_work"
os.environ["WECOM_OAUTH_RESULT_URL"] = f"http://127.0.0.1:{PORT}/oauth-done"
os.environ["WECOM_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{PORT}"


async def _wait_health(client: "httpx.AsyncClient", timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = await client.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return False


async def on_elicit(context, params):
    """哨兵侧elicitation 回调：URL 模式「导航」到授权页（打回调接口）后 accept；
    表单模式回填 mock 邮箱凭据。"""
    url = getattr(params, "url", None)
    if url:
        CAPTURED["elicit_url"] = url
        state = (parse_qs(urlparse(url).query).get("state") or [""])[0]
        CAPTURED["elicit_state"] = state
        r = await HTTP.get(f"{BASE}/api/v1/wecom/oauth/callback",
                           params={"code": f"mock-code-{MOCK_USERID}", "state": state})
        CAPTURED["callback_status"] = r.status_code
        CAPTURED["callback_location"] = r.headers.get("location", "")
        return ElicitResult(action="accept")
    schema = getattr(params, "requestedSchema", None) or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if "client_password" in props:
        return ElicitResult(action="accept",
                            content={"email": MOCK_EMAIL, "client_password": MOCK_PWD})
    return ElicitResult(action="cancel")


import httpx  # noqa: E402
import uvicorn  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402
from mcp.types import ElicitResult  # noqa: E402

HTTP: "httpx.AsyncClient | None" = None


def _call_result_text(result) -> tuple[bool, dict]:
    text = ""
    for block in (result.content or []):
        text += getattr(block, "text", "") or ""
    try:
        data = json.loads(text) if text else {}
    except Exception:
        data = {"_raw": text}
    return bool(getattr(result, "isError", False)), data


async def main() -> int:
    global HTTP
    HTTP = httpx.AsyncClient(trust_env=False, timeout=15)

    from mcp_hub.app import app as hub_app

    config = uvicorn.Config(hub_app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    if not await _wait_health(HTTP):
        print("FATAL: hub 未在 20s 内就绪")
        return 1

    try:
        async with streamablehttp_client(url=MCP_URL, headers=HEADERS) as (read, write, _):
            async with ClientSession(read, write, elicitation_callback=on_elicit) as session:
                await session.initialize()

                # ---------- S1 工具目录 ----------
                listed = await session.list_tools()
                names = sorted(t.name for t in listed.tools)
                rec("S1 原生工具目录 = 13 个", names == sorted(EXPECTED_TOOLS),
                    f"got={names}")

                # ---------- S2 未连接 ----------
                _, data = _call_result_text(await session.call_tool("connection_status", {}))
                rec("S2 初始未连接", data.get("connected") is False, json.dumps(data, ensure_ascii=False)[:80])

                # ---------- S3 租户配置 ----------
                r = await HTTP.put(f"{BASE}/api/v1/wecom/tenant-config", headers=HEADERS,
                                   json={"corpId": CORP_ID, "corpSecret": CORP_SECRET, "agentId": AGENT_ID})
                ok3 = r.status_code == 200 and (r.json() or {}).get("ok") is True
                r = await HTTP.get(f"{BASE}/api/v1/wecom/tenant-config", headers=HEADERS)
                body = r.json() or {}
                masked_ok = (body.get("corpSecret", "").startswith("mo") and "*" in body.get("corpSecret", "")
                             and CORP_SECRET not in json.dumps(body, ensure_ascii=False))
                rec("S3 租户配置落库 + 掩码视图", ok3 and masked_ok, f"masked={body.get('corpSecret')}")

                # ---------- S4 connect A（URL elicitation + 回调接力） ----------
                _, data = _call_result_text(await session.call_tool("connect", {"mode": "A"}))
                url = CAPTURED.get("elicit_url", "")
                url_ok = ("open.weixin.qq.com/connect/oauth2/authorize" in url
                          and "scope=snsapi_privateinfo" in url
                          and f"agentid={AGENT_ID}" in url
                          and f"appid={CORP_ID}" in url
                          and "state=" in url)
                cb_ok = CAPTURED.get("callback_status") == 302 and "wecom=ok" in (CAPTURED.get("callback_location") or "")
                rec("S4 authorize URL 形态（snsapi_privateinfo）", url_ok, url[:110])
                rec("S4b 授权回调 302 成功", cb_ok, f"{CAPTURED.get('callback_status')} {CAPTURED.get('callback_location')}")
                rec("S4c connect 返回 A 已连接", data.get("connected") is True and data.get("mode") == "A",
                    f"connected={data.get('connected')!r} mode={data.get('mode')!r} note={data.get('note')!r}")

                # ---------- S4d state 一次性（同一 state 再回调必须失败） ----------
                r = await HTTP.get(f"{BASE}/api/v1/wecom/oauth/callback",
                                   params={"code": f"mock-code-{MOCK_USERID}", "state": CAPTURED.get("elicit_state")})
                rec("S4d state 一次性（二次回调 302 fail）",
                    r.status_code == 302 and "wecom=fail" in (r.headers.get("location") or ""),
                    r.headers.get("location", ""))

                # ---------- S5 profile ----------
                _, data = _call_result_text(await session.call_tool("get_my_profile", {}))
                rec("S5 get_my_profile = mock 成员身份",
                    data.get("userid") == MOCK_USERID and data.get("bizMail") == MOCK_EMAIL,
                    json.dumps(data, ensure_ascii=False)[:100])

                # ---------- S6 闸门：A 模式拒邮件 ----------
                is_err, data = _call_result_text(await session.call_tool("mail_list_messages", {}))
                rec("S6 模式闸门拒绝跨模式工具", is_err and "企业邮箱" in json.dumps(data, ensure_ascii=False),
                    json.dumps(data, ensure_ascii=False)[:100])

                # ---------- S7 发消息 ----------
                _, data = _call_result_text(await session.call_tool(
                    "send_text_message", {"touser": MOCK_USERID, "content": "P0 冒烟"}))
                rec("S7 send_text_message mock 成功", data.get("errcode") == 0, json.dumps(data, ensure_ascii=False)[:80])

                # ---------- S8 通讯录搜索 ----------
                _, data = _call_result_text(await session.call_tool("contact_search", {"query": "张"}))
                rec("S8 contact_search 命中", data.get("count", 0) >= 1
                    and any(m.get("userid") == MOCK_USERID for m in data.get("members", [])),
                    json.dumps(data, ensure_ascii=False)[:100])

                # ---------- S9 connect B（表单 elicitation）→ A+B ----------
                _, data = _call_result_text(await session.call_tool("connect", {"mode": "B"}))
                rec("S9 connect B 合并为 A+B", data.get("connected") is True and data.get("mode") == "AB",
                    json.dumps(data, ensure_ascii=False)[:110])

                # ---------- S10 邮件闭环 ----------
                _, data = _call_result_text(await session.call_tool("mail_list_messages", {"folder": "INBOX"}))
                inbox_ok = data.get("count") == 3
                _, draft = _call_result_text(await session.call_tool(
                    "mail_create_draft", {"to": "lisi@mock-corp.com", "subject": "P0", "body": "hello"}))
                draft_id = draft.get("draftId")
                _, sent = _call_result_text(await session.call_tool(
                    "mail_send_draft", {"draftId": draft_id, "requestId": "p0-req-1"}))
                _, sent2 = _call_result_text(await session.call_tool(
                    "mail_send_draft", {"draftId": draft_id, "requestId": "p0-req-1"}))
                _, folders = _call_result_text(await session.call_tool("mail_list_folders", {}))
                _, sentbox = _call_result_text(await session.call_tool("mail_list_messages", {"folder": "Sent"}))
                rec("S10 邮件闭环（list/draft/send/幂等/Sent）",
                    inbox_ok and sent.get("sent") is True and sent2.get("idempotent") is True
                    and sentbox.get("count") == 1 and folders.get("folders"),
                    f"inbox={data.get('count')} draft={draft_id} sent={sent.get('uid')} idem={sent2.get('idempotent')} "
                    f"list_raw={json.dumps(data, ensure_ascii=False)[:90]}")

                # ---------- S11 兜底分支：普通 UA → qrConnect ----------
                r = await HTTP.get(f"{BASE}/api/v1/wecom/oauth/authorize-url",
                                   headers={**HEADERS, "User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
                body = r.json() or {}
                rec("S11 普通 UA 走 qrConnect 兜底",
                    body.get("kind") == "qr_connect"
                    and "open.work.weixin.qq.com/wwopen/sso/qrConnect" in (body.get("authorizeUrl") or ""),
                    body.get("kind", ""))

                # ---------- S12 伪造 state 回调 ----------
                r = await HTTP.get(f"{BASE}/api/v1/wecom/oauth/callback",
                                   params={"code": f"mock-code-{MOCK_USERID}", "state": "forged-by-sentinel"})
                _, data = _call_result_text(await session.call_tool("connection_status", {}))
                rec("S12 伪造 state 被拒且不污染连接态",
                    r.status_code == 302 and "wecom=fail" in (r.headers.get("location") or "")
                    and data.get("mode") == "AB",
                    r.headers.get("location", ""))

                # ---------- S13 disconnect B ----------
                _, data = _call_result_text(await session.call_tool("disconnect", {"mode": "B"}))
                is_err, _ = _call_result_text(await session.call_tool("mail_list_messages", {}))
                _, prof = _call_result_text(await session.call_tool("get_my_profile", {}))
                rec("S13 disconnect(B) 回到 A", data.get("mode") == "A" and is_err and prof.get("userid") == MOCK_USERID,
                    json.dumps(data, ensure_ascii=False)[:80])

                # ---------- S14 全断 ----------
                _, data = _call_result_text(await session.call_tool("disconnect", {}))
                is_err, _ = _call_result_text(await session.call_tool("get_my_profile", {}))
                rec("S14 全断后 profile 被拒", data.get("connected") is False and is_err,
                    json.dumps(data, ensure_ascii=False)[:80])

                # ---------- S15 probe ----------
                r = await HTTP.post(f"{BASE}/internal/mcp/probe",
                                    json={"transport": "builtin", "code": "wechat_work"})
                tools = (r.json() or {}).get("tools") or []
                rec("S15 probe 报原生 13 工具", len(tools) == 13,
                    f"count={len(tools)}")

                # ---------- S16 health ----------
                r = await HTTP.get(f"{BASE}/health")
                servers = (r.json() or {}).get("servers") or {}
                rec("S16 /health wechat_work=13", servers.get("wechat_work") == 13, str(servers))

                # ---------- S17 库内无明文 ----------
                # WAL 模式下近期写入可能还在 -wal/-shm 边车里，三个文件都要扫
                raw = b""
                for suffix in ("", "-wal", "-shm"):
                    p = os.environ["WECOM_DB_PATH"] + suffix
                    if os.path.exists(p):
                        raw += open(p, "rb").read()
                leaks = [s for s in (CORP_SECRET.encode(), MOCK_PWD.encode(),
                                     f"mock-code-{MOCK_USERID}".encode()) if s in raw]
                rec("S17 DB 无明文凭据", not leaks, f"leaks={leaks}")

    finally:
        server.should_exit = True
        thread.join(timeout=10)
        await HTTP.aclose()
        try:
            from mcp_hub.wecom import graph as wecom_graph
            await wecom_graph.shutdown()
        except Exception:
            pass
        shutil.rmtree(_TMPDIR, ignore_errors=True)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n" + ("全部断言通过 ✅" if not failed else f"存在失败断言 ❌：{failed}"))
    print(f"（共 {len(RESULTS)} 项，失败 {len(failed)} 项）")
    sys.stdout.flush()
    # aiosqlite 后台线程是非守护的，哨兵显式强退，避免挂住
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
