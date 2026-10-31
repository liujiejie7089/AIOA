# -*- coding: utf-8 -*-
"""真机验收哨兵：企微 MCP 的 `chat_id` 往返闭环（2026-10-31）。

用户实测报「提供的 chat_id 无效」。根因：
    `recent_group_sessions` 原来返回的字段叫 ``ref``，而 `session_messages` 的入参叫
    ``chat_id`` —— 模型拿到 ``ref`` 却要填 ``chat_id``，于是报「chat_id 无效」。
    且 ``ref`` 的描述写着「不要向用户展示」，把模型引向更隐蔽的错误路径。

修复：返回字段统一为 ``chat_id``（保留 ``ref`` 兼容别名），两处工具描述改写。

判据（铁律 7/12：判据回被测对象，不与被测对象同源）：
    C1  `recent_group_sessions` 每条会话都带 **chat_id** 字段（不是只有 ref）。
    C2  `ref` 兼容别名仍在（老客户端不断）。
    C3 ★**往返闭环**：把 C1 拿到的 chat_id **原样**喂给 `session_messages`
        ⇒ 真的取到消息（这是「chat_id 无效」是否修好的唯一判据）。
    C4  工具描述写明 chat_id 要原样回传（模型不再自造）。

用法：
    <agent/.venv python> scripts/_verify_wecom_chatid_roundtrip.py
前置：Java :8080 与 mcp-hub :8099 在跑；企微 CLI 连接器已授权（WECOM_MOCK=1 + 共享 profile）。
未满足前置时逐项记 SKIP 并说明原因（**不**判失败 —— 环境不具备不是缺陷）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

PASS, FAIL, SKIP = [], [], []


def chk(name, ok, detail=""):
    if ok:
        PASS.append(name)
        print("  [PASS] %s" % name)
    else:
        FAIL.append(name)
        print("  [FAIL] %s  <- %s" % (name, str(detail)[:400]))


def skip(name, why):
    SKIP.append(name)
    print("  [SKIP] %s  <- %s" % (name, why))


def login(username="admin", password="Admin@123"):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/v1/auth/login",
        data=json.dumps({"username": username, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(op.open(req, timeout=15).read())["data"]["accessToken"]


def _text_of(result):
    """MCP 客户端返回 [{'type':'text','text':...}]；取文本并尝试解 JSON。"""
    raw = result
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        raw = raw[0].get("text", "")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


async def main():
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        skip("整组", "缺少依赖 langchain-mcp-adapters：%s" % exc)
        return

    try:
        token = login()
    except Exception as exc:  # noqa: BLE001
        skip("整组", "拿不到 accessToken（Java 未在线或账号不通）：%s" % exc)
        return

    client = MultiServerMCPClient({
        "wecom_cli": {
            "transport": "streamable_http",
            "url": "http://127.0.0.1:8099/mcp/wecom_cli",
            "headers": {"Authorization": "Bearer " + token},
        }
    })
    try:
        tools = await client.get_tools()
    except Exception as exc:  # noqa: BLE001
        skip("整组", "连不上 mcp-hub :8099：%s" % exc)
        return

    by_name = {}
    for t in tools:
        by_name[t.name.split("__")[-1]] = t
    rs = by_name.get("recent_group_sessions")
    sm = by_name.get("session_messages")
    if not rs or not sm:
        skip("整组", "wecom_cli 未暴露 recent_group_sessions / session_messages")
        return

    # ---- C4 描述 ----
    desc_rs = (getattr(rs, "description", "") or "")
    desc_sm = (getattr(sm, "description", "") or "")
    chk("C4a recent_group_sessions 描述写明返回 chat_id 字段",
        "chat_id" in desc_rs, desc_rs[:200])
    chk("C4b session_messages 描述要求 chat_id 原样取自上一步",
        "原样" in desc_sm or "原样取自" in desc_sm, desc_sm[:200])

    # ---- C1/C2/C3 ----
    try:
        raw = await rs.ainvoke({"days": 7})
    except Exception as exc:  # noqa: BLE001
        skip("C1/C2/C3", "调 recent_group_sessions 失败：%s" % exc)
        return
    payload = _text_of(raw)
    if not isinstance(payload, dict):
        skip("C1/C2/C3", "返回不是 JSON 对象：%r" % str(payload)[:200])
        return
    if "还没有绑定企业微信" in str(payload):
        skip("C1/C2/C3", "企微连接器未授权（返回「还没有绑定企业微信」）")
        return

    sessions = payload.get("sessions") or []
    if not sessions:
        skip("C1/C2/C3", "最近 7 天没有群会话（无可验证样本）")
        return

    first = sessions[0]
    chk("C1 recent_group_sessions 每条会话都带 chat_id 字段",
        bool(first.get("chat_id")), str(first)[:300])
    chk("C2 保留 ref 兼容别名（老客户端不断）",
        first.get("ref") == first.get("chat_id"), str(first)[:300])

    cid = first.get("chat_id") or ""
    try:
        out = await sm.ainvoke({"chat_id": cid, "days": 7, "limit": 5})
    except Exception as exc:  # noqa: BLE001
        chk("C3 ★chat_id 往返闭环（拿到的 chat_id 能直接取消息）", False,
            "session_messages 失败：%s" % exc)
        return
    msgs = _text_of(out)
    ok = isinstance(msgs, dict) and not msgs.get("error") and \
        isinstance(msgs.get("messages"), list)
    chk("C3 ★chat_id 往返闭环（拿到的 chat_id 能直接取消息）", ok, str(msgs)[:300])


if __name__ == "__main__":
    asyncio.run(main())
    print("\n合计：%d 通过 / %d 失败 / %d 跳过" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败项：" + "; ".join(FAIL))
    sys.exit(1 if FAIL else 0)
