#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""企业微信群机器人连接器验收（**真机**，会真的往群里发一条消息）。

链路（每一步都真打协议，且关键结论取第二源）：
  G1  hub /api/v1/connectors 清单里有 wecom_group（工具数 2）
  G2  管理员 PUT webhookKey → hub 侧 configured=true（直接回查 hub，不信 Java 回话）
  G3  掩码视图不回明文 key
  G4  MCP 客户端连 /mcp/wecom_group，tools/list = 2 个工具、required 正确
  G5  call_tool send_group_text → 真实发送成功（企微 errcode=0）
  G6  call_tool 空 content → isError=True（不允许"空消息也算成功"）
  G7  hub 日志里查不到明文 webhook key（G5 发完之后再查，防"代码守纪律、依赖漏凭据"）

为什么需要 G7（2026-10-30 实测）：凭据不进代码只是第一层。发完之后翻 logs/mcp-hub.log，
看到 httpx 自己在 INFO 级别把 `POST .../webhook/send?key=8fc8e8c4-0370-4…` 整条 URL 打了出来 ——
key 就是凭证，等于把凭据写进了日志文件。已在 group.py 装 `_RedactKeyFilter` 抹成 `key=***`，
这条断言就是防止将来有人「顺手换个 HTTP 库/加一行日志」把它带回来。
判据取日志文件本体（第二源），不看代码里有没有过滤器。

用法：
    python scripts/_verify_wecom_group.py --key <webhook key> [--base http://127.0.0.1:8080] [--hub http://127.0.0.1:8099]
前置：Java :8080 与 mcp-hub :8099 在线；hub 需 WECOM_MOCK=0（真实身份，vault 按租户隔离）。
退出码 = 失败项数。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

RESULTS: list[tuple[str, bool, str]] = []
CODE = "wecom_group"


def call(base, path, method="GET", token=None, body=None, timeout=25):
    req = urllib.request.Request(base.rstrip("/") + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, "URLError: %s" % e.reason


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


def rec(name, ok, det=""):
    RESULTS.append((name, ok, det))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" —— " + det) if det else ""))


async def mcp_roundtrip(hub, token, key_present: bool):
    """连 /mcp/wecom_group：列工具 + 真发一条 + 空消息必须失败。"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = hub.rstrip("/") + "/mcp/" + CODE
    headers = {"Authorization": "Bearer " + token}
    out = {}
    async with streamablehttp_client(url=url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            listed = await s.list_tools()
            out["tools"] = [(t.name, (t.inputSchema or {}).get("required") or []) for t in listed.tools]
            sent = await s.call_tool("send_group_text",
                                     {"content": "AIOS 群机器人接入验收 ✅（连接器体系 v1）"})
            out["sent_text"] = "".join(getattr(c, "text", "") for c in (sent.content or []))
            out["sent_error"] = bool(getattr(sent, "isError", False))
            empty = await s.call_tool("send_group_text", {"content": ""})
            out["empty_error"] = bool(getattr(empty, "isError", False))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--hub", default="http://127.0.0.1:8099")
    ap.add_argument("--key", default=os.environ.get("WECOM_WEBHOOK_KEY", "").strip())
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()

    print("== 企业微信群机器人连接器验收 @ %s / hub %s ==" % (args.base, args.hub))
    if not args.key:
        print("  [FATAL] 缺少 --key（或环境变量 WECOM_WEBHOOK_KEY）")
        return 1

    st, raw = call(args.base, "/api/v1/auth/login", "POST",
                   body={"username": args.user, "password": args.password})
    token = ((jload(raw).get("data") or {}).get("accessToken")) if st == 200 else None
    if not token:
        print("  [FATAL] 登录失败 HTTP=%s %s" % (st, raw[:120]))
        return 1

    # G1 清单
    st, raw = call(args.hub, "/api/v1/connectors", token=token)
    items = (jload(raw).get("connectors") or [])
    me = next((i for i in items if i.get("code") == CODE), None)
    rec("G1 hub 清单含 wecom_group 且工具数 2",
        st == 200 and me is not None and me.get("toolCount") == 2,
        "HTTP=%s toolCount=%s" % (st, me and me.get("toolCount")))

    # G2 保存 → 回查 hub
    st, raw = call(args.hub, "/api/v1/connectors/%s/credentials" % CODE, "PUT", token=token,
                   body={"values": {"webhookKey": args.key}, "enabled": True})
    d = jload(raw)
    st2, raw2 = call(args.hub, "/api/v1/connectors/%s/credentials" % CODE, token=token)
    d2 = jload(raw2)
    rec("G2 保存后 hub 侧 configured=true（第二源）",
        st == 200 and d.get("ok") is True and st2 == 200 and d2.get("configured") is True,
        "putHTTP=%s getConfigured=%s" % (st, d2.get("configured")))

    # G3 掩码
    rec("G3 掩码视图不回明文 key",
        args.key not in raw2 and d2.get("values", {}).get("webhookKeySet") is True,
        "leak=%s webhookKeySet=%s" % (args.key in raw2, d2.get("values", {}).get("webhookKeySet")))

    # G4~G6 MCP
    try:
        out = asyncio.run(mcp_roundtrip(args.hub, token, True))
    except Exception as e:  # noqa: BLE001
        rec("G4 MCP 连接 /mcp/wecom_group", False, "%s: %s" % (type(e).__name__, e))
        return len([r for r in RESULTS if not r[1]])

    names = sorted(n for n, _ in out["tools"])
    reqs = dict(out["tools"])
    rec("G4 工具目录 = 2 个且 required 只有 content",
        names == ["send_group_markdown", "send_group_text"]
        and reqs.get("send_group_text") == ["content"],
        "tools=%s required=%s" % (names, reqs))

    rec("G5 真实发送成功（企微 errcode=0）",
        out["sent_error"] is False and '"sent": true' in out["sent_text"].replace('"sent":true', '"sent": true'),
        out["sent_text"][:120])

    rec("G6 空内容被拒（isError=true，不静默成功）", out["empty_error"] is True, str(out["empty_error"]))

    # G7 日志不得含明文 key：G5 已经真的发过一条，此时日志里必然有那次请求
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "logs", "mcp-hub.log")
    if not os.path.exists(log_path):
        rec("G7 hub 日志无明文 webhook key", False,
            "找不到 %s —— 无法验证脱敏（请用 start-all.sh 启动，日志才落在 logs/）" % log_path)
    else:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        hits = text.count(args.key)
        redacted = "key=***" in text
        rec("G7 hub 日志无明文 webhook key", hits == 0 and redacted,
            "明文出现=%d 次 已脱敏标记=%s 文件=%s" % (hits, redacted, os.path.basename(log_path)))

    fails = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for n, _, det in fails:
        print("  - %s：%s" % (n, det))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
