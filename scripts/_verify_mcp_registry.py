#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：MCP 服务器注册表 + 信任闸门 + 内置工具桥接（docs/59 §10.3 / §10.4）

只做「可逆」的调用：探测(probe) 不落 trusted；trust 之后一定 un-trust 复原。
所以本脚本跑完，库里 mcp_server 的 trusted 回到全 0（与 V97 种子一致），可反复跑。

  M1  GET  /api/v1/mcp/servers                 恰好 qq_mail / wechat_work 两行；trusted=false、
                                               source=BUILTIN、toolCount=6/2、connected=false
  M2  GET  /api/v1/mcp/manifest                **空**（都没信任）
  M3  POST /servers/qq_mail/probe              ok=true、tools=6，但 trusted **仍为 false**
                                               ⇒ 证明「探测 ≠ 信任」（探活只证明能用，不等于授权）
  M4  POST /servers/qq_mail/trust              ok=true、toolCount=6
  M5  GET  /api/v1/mcp/manifest                **仍空**：qq_mail 已信任但当前用户**未连接**邮箱
                                               ⇒ 连接闸门（判据 2），防「信任了就能读别人邮箱」
  M6  GET  /servers/qq_mail/tools              6 个工具，required 与契约逐字一致
  M7  POST /builtin/qq_mail/call                ok=false 且文案含「未连接」⇒ 执行侧同样拦
  M8  POST /builtin/wechat_work/call            ok=false 且文案含「尚未信任」⇒ 闸门**顺序**正确
  M9  POST /servers/qq_mail/untrust             trusted=false；manifest 仍空（幂等复原）
  M10 GET  /api/v1/mcp/servers（无 token）        HTTP 401
  M11 审计落库                                  M7 之后 mcp_tool_audit 行数 +1（直接查库比对）
  M12 凭据不外泄                                列表响应不含 authCode/corpSecret/credential 等键名与明文

用法：
    python scripts/_verify_mcp_registry.py [--base http://127.0.0.1:8080]
前置：后端在线 + V97 已执行（首次启动自动建表与种子）+ mcp-hub 在 :8099 在线（M3/M4 需要）。
     前置缺失时脚本会明确报 FATAL/FAIL 原因，不静默 SKIP。
退出码 = 失败项数。
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

RESULTS = []
EXPECT_REQUIRED = {
    "list_folders": [],
    "list_messages": [],
    "read_message": ["uid"],
    "search_messages": ["query"],
    "create_draft": ["to", "subject", "body"],
    "send_draft": ["draftId", "requestId"],
}
FORBIDDEN_KEY_SUBSTR = ("credential", "authcode", "corpsecret", "secret", "password", "enc")
MYSQL = "D:/dev/mysql/mysql-8.4.10-winx64/bin/mysql.exe"  # 注意用盘符式路径：
# Git Bash 的 /d/... 在 Python os.path.exists 下不成立（2026-10-20 踩过，导致 M11 假失败）。


def rec(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + " —— " + detail)


def call(base, path, method="GET", token=None, body=None, timeout=30):
    url = base.rstrip("/") + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # 连接失败也要给出可读原因，不能让脚本崩
        return 0, "TRANSPORT_ERROR: %s: %s" % (type(e).__name__, e)


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def login(base, username, password):
    st, raw = call(base, "/api/v1/auth/login", "POST",
                   body={"username": username, "password": password})
    d = jload(raw) or {}
    return (d.get("data") or {}).get("accessToken"), st, d


def audit_rows():
    """直接查库数 mcp_tool_audit 行数；查不到返回 None（不算失败项，但要说明）。"""
    if not os.path.exists(MYSQL):
        return None
    try:
        out = subprocess.run([MYSQL, "-uroot", "-N", "-B", "aios", "-e",
                              "select count(*) from mcp_tool_audit"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return None
        return int((out.stdout or "0").strip().splitlines()[0])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AIOS_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("== MCP 注册表 / 信任闸门接口验收 @ %s ==" % base)
    token, st, d = login(base, args.user, args.password)
    if not token:
        print("  [FATAL] 登录失败（HTTP %s，%s）—— 后端未就绪或 V97 未执行" % (st, (d or {}).get("message")))
        return 1

    # ---------- M1 清单 ----------
    st, raw = call(base, "/api/v1/mcp/servers", token=token)
    d = jload(raw) or {}
    items = d.get("data") or []
    by_code = {i.get("code"): i for i in items}
    qq, ww = by_code.get("qq_mail") or {}, by_code.get("wechat_work") or {}
    ok = (st == 200 and d.get("code") == 0
          and qq.get("source") == "BUILTIN" and ww.get("source") == "BUILTIN"
          and qq.get("trusted") is False and ww.get("trusted") is False
          and qq.get("toolCount") == 6 and ww.get("toolCount") == 2
          and qq.get("connected") is False)
    rec("M1 清单：2 个内置服务器、默认不可信、目录 6/2", ok,
        "HTTP=%s qq=%s ww=%s" % (st, {k: qq.get(k) for k in ("source", "trusted", "toolCount", "connected")},
                                 {k: ww.get(k) for k in ("source", "trusted", "toolCount", "connected")}))

    # ---------- M12 凭据不外泄（先做，避免后面状态变化影响） ----------
    leaked_keys = [k for i in items for k in i.keys()
                   if any(s in k.lower() for s in FORBIDDEN_KEY_SUBSTR)]
    raw_lower = raw.lower()
    leaked_vals = [s for s in ("authcode", "cropsecret=", "enc:") if s in raw_lower]
    rec("M12 列表不含凭据键/密文", not leaked_keys and not leaked_vals,
        "可疑键=%s 可疑值=%s" % (leaked_keys, leaked_vals))

    # ---------- M2 manifest 空 ----------
    st, raw = call(base, "/api/v1/mcp/manifest", token=token)
    d = jload(raw) or {}
    rec("M2 manifest 为空（全未信任）", st == 200 and (d.get("data") or []) == [],
        "HTTP=%s data=%s" % (st, d.get("data")))

    # ---------- M3 probe 不授权 ----------
    st, raw = call(base, "/api/v1/mcp/servers/qq_mail/probe", "POST", token=token)
    d = jload(raw) or {}
    pd = d.get("data") or {}
    tools_n = len(pd.get("tools") or [])
    st2, raw2 = call(base, "/api/v1/mcp/servers", token=token)
    qq_after_probe = {i.get("code"): i for i in (jload(raw2) or {}).get("data") or []}.get("qq_mail") or {}
    rec("M3 probe ok=true 但不改 trusted（探测≠信任）",
        st == 200 and pd.get("ok") is True and tools_n == 6 and qq_after_probe.get("trusted") is False,
        "HTTP=%s ok=%s tools=%s trusted_after=%s error=%r"
        % (st, pd.get("ok"), tools_n, qq_after_probe.get("trusted"), pd.get("error")))

    # ---------- M4 trust ----------
    st, raw = call(base, "/api/v1/mcp/servers/qq_mail/trust", "POST", token=token)
    d = jload(raw) or {}
    td = d.get("data") or {}
    rec("M4 trust ok=true toolCount=6",
        st == 200 and td.get("ok") is True and td.get("toolCount") == 6,
        "HTTP=%s data=%s" % (st, td))

    # ---------- M5 连接闸门 ----------
    st, raw = call(base, "/api/v1/mcp/manifest", token=token)
    d = jload(raw) or {}
    codes = [i.get("code") for i in (d.get("data") or [])]
    rec("M5 已信任但未连接 ⇒ manifest 仍不含 qq_mail（连接闸门）",
        st == 200 and "qq_mail" not in codes, "HTTP=%s codes=%s" % (st, codes))

    # ---------- M6 工具目录 ----------
    st, raw = call(base, "/api/v1/mcp/servers/qq_mail/tools", token=token)
    d = jload(raw) or {}
    tools = d.get("data") or []
    got = {}
    for t in tools:
        try:
            got[t.get("name")] = json.loads(t.get("inputSchema") or "{}").get("required") or []
        except Exception:
            got[t.get("name")] = "<schema 解析失败>"
    rec("M6 工具目录 = 契约 6 项且 required 一致", got == EXPECT_REQUIRED, "actual=%s" % got)

    # ---------- M7 / M11 执行侧闸门 + 审计 ----------
    before = audit_rows()
    st, raw = call(base, "/api/v1/mcp/builtin/qq_mail/call", "POST", token=token,
                   body={"tool": "list_messages", "arguments": {"limit": 5}})
    d = jload(raw) or {}
    cd = d.get("data") or {}
    err = str(cd.get("error") or "")
    rec("M7 未连接 ⇒ 执行被拦（文案含『未连接』）",
        st == 200 and cd.get("ok") is False and "未连接" in err, "data=%s" % cd)

    after = audit_rows()
    if before is None or after is None:
        rec("M11 审计落库", False, "无法查库（mysql 客户端不可用或表不存在）before=%s after=%s" % (before, after))
    else:
        rec("M11 审计落库（mcp_tool_audit +1）", after == before + 1, "before=%s after=%s" % (before, after))

    # ---------- M8 闸门顺序：未信任优先于未连接 ----------
    st, raw = call(base, "/api/v1/mcp/builtin/wechat_work/call", "POST", token=token,
                   body={"tool": "check_connection", "arguments": {}})
    d = jload(raw) or {}
    cd = d.get("data") or {}
    err = str(cd.get("error") or "")
    rec("M8 未信任 ⇒ 先报『尚未信任』（闸门顺序）",
        st == 200 and cd.get("ok") is False and "尚未信任" in err, "data=%s" % cd)

    # ---------- M9 复原 ----------
    st, raw = call(base, "/api/v1/mcp/servers/qq_mail/untrust", "POST", token=token)
    d = jload(raw) or {}
    st2, raw2 = call(base, "/api/v1/mcp/manifest", token=token)
    codes2 = [i.get("code") for i in ((jload(raw2) or {}).get("data") or [])]
    rec("M9 untrust 复原（trusted=false，manifest 空）",
        st == 200 and (d.get("data") or {}).get("ok") is True and codes2 == [],
        "HTTP=%s data=%s manifest=%s" % (st, d.get("data"), codes2))

    # ---------- M10 未登录 ----------
    st, raw = call(base, "/api/v1/mcp/servers")
    rec("M10 未登录 → 401", st == 401, "HTTP=%s body=%s" % (st, raw[:120]))

    failed = [r for r in RESULTS if not r[1]]
    print("\n%s（%d/%d）" % ("全部通过 ✅" if not failed else "存在失败 ❌", len(RESULTS) - len(failed), len(RESULTS)))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
