#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：MCP 服务器注册表 + 信任闸门 + 内置工具桥接（docs/59 §10.3 / §10.4）

只做「可逆」的调用：探测(probe) 不落 trusted；trust 之后一定 un-trust 复原。

**为什么开头要先做快照 + 复位**（2026-10-30 修）：
M1「默认不可信」、M3「probe 不改 trusted」、M2/M9「manifest 为空」、M8「先报尚未信任」
这五项都以「库里 trusted 全 0」为前提，而脚本自己并不保证这个前提 —— 上一轮谁 trust 过、
或者真实环境里管理员为了用起来而 trust 过，都会让它们**假失败**（本轮实测就是：
三个内置服务器 trusted 全为 1，五项一起红）。
直接在开头无脑 un-trust 也不行：真实在用的连接器一取消信任 AI 那边的工具就没了。
故改成「先快照每个内置服务器的 trusted，再复位，跑完按快照恢复」——
既不依赖外部状态，也不破坏真实配置。

  M0  GET  /api/v1/mcp/servers                 快照 trusted（前置，不计入断言）
  M1  GET  /api/v1/mcp/servers                 4 行（qq_mail / wecom_cli / wechat_work / wecom_group，
                                               后两个是已下线留痕行）；trusted=false、source=BUILTIN、
                                               toolCount=6/5/0/0（已下线的工具快照由 V104 清空）
  M1b 已下线服务器的行**必须保留**且 trusted=false（回滚靠行，别删；但绝不能再进 manifest）
  M2  GET  /api/v1/mcp/manifest                **空**（都没信任）
  M3  POST /servers/qq_mail/probe              ok=true、tools=6，但 trusted **仍为 false**
                                               ⇒ 证明「探测 ≠ 信任」（探活只证明能用，不等于授权）
  M4  POST /servers/qq_mail/trust              ok=true、toolCount=6
  M5  GET  /api/v1/mcp/manifest                **仍空**：qq_mail 已信任但当前用户**未连接**邮箱
                                               ⇒ 连接闸门（判据 2），防「信任了就能读别人邮箱」
  M6  GET  /servers/qq_mail/tools              6 个工具，required 与契约逐字一致
  M7  POST /builtin/qq_mail/call                ok=false 且文案含「未连接」⇒ 执行侧同样拦
  M8  POST /builtin/wechat_work/call            ok=false 且文案含「尚未信任」⇒ 闸门**顺序**正确
                                               （信任判定在 handler 查找之前，故实现删了也不影响）
  M9  POST /servers/qq_mail/untrust             trusted=false；manifest 仍空（幂等复原）
  M10 GET  /api/v1/mcp/servers（无 token）        HTTP 401
  M11 审计落库                                  M7 之后 mcp_tool_audit 行数 +1（直接查库比对）
  M12 凭据不外泄                                列表响应不含 authCode/corpSecret/credential 等键名与明文
  M13 工具目录无漂移                            存活服务器的 DB 目录（信任时从 hub 覆盖写）与 hub **实装**数
                                               逐个相等；且 hub 里**不得再出现**已下线的两个 code。
                                               hub 是工具的唯一真源（wecom_cli/catalog.py），DB 只是快照；
                                               判据回到真源再取一次，不与被测对象同源。

用法：
    python scripts/_verify_mcp_registry.py [--base http://127.0.0.1:8080]
前置：后端在线 + V97 已执行（首次启动自动建表与种子）+ mcp-hub 在 :8099 在线（M3/M4/M13 需要）。
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
# 内置服务器 → 期望工具数。**不是**写死的历史值，而是「hub 实装数」的镜像；
# M13 会拿它跟 hub 现报的数字逐个比对，两边不一致就红（防止只改一处）。
EXPECT_TOOL_COUNT = {"qq_mail": 6, "wechat_work": 0, "wecom_group": 0, "wecom_cli": 25}
# 已下线（V103 停用 + V104 清工具快照 + 代码物理删除，2026-10-30；docs/64 §9.7）。
# 企业微信统一改用「企业微信（扫码）」连接器。
# 它们的 mcp_server 行**故意保留**（留痕），但必须 trusted=0 且工具目录为空：
# 否则 manifest 会把已下线连接器的工具重新塞给模型 —— 那是本节最该防的事。
# （V104 之前这里留的是 13/2 个旧快照，导致 /servers/{code}/tools 仍能查出工具，
#   等于"看得见但已经没有人实现它"，比报错更危险。）
RETIRED_SERVERS = {"wechat_work", "wecom_group"}
DEFAULT_HUB = "http://127.0.0.1:8099"
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
    ap.add_argument("--hub", default=os.environ.get("AIOS_HUB", DEFAULT_HUB))
    args = ap.parse_args()
    base = args.base.rstrip("/")
    hub = args.hub.rstrip("/")

    print("== MCP 注册表 / 信任闸门接口验收 @ %s ==" % base)
    token, st, d = login(base, args.user, args.password)
    if not token:
        print("  [FATAL] 登录失败（HTTP %s，%s）—— 后端未就绪或 V97 未执行" % (st, (d or {}).get("message")))
        return 1

    # ---------- M0 前置：快照 trusted，再复位到「全未信任」 ----------
    st, raw = call(base, "/api/v1/mcp/servers", token=token)
    servers = (jload(raw) or {}).get("data") or []
    snapshot = {i.get("code"): bool(i.get("trusted")) for i in servers
                if i.get("source") == "BUILTIN"}
    for code, was_trusted in snapshot.items():
        if was_trusted:
            call(base, "/api/v1/mcp/servers/%s/untrust" % code, "POST", token=token)
    print("  [ 前置 ] 已复位 trusted：%s（跑完按快照恢复）" % (snapshot,))

    try:
        return run_assertions(base, hub, token)
    finally:
        # 按快照恢复：wecom_group 这类「租户已配置、AI 正在用」的服务器不能被留在未信任态
        for code, was_trusted in snapshot.items():
            if was_trusted:
                call(base, "/api/v1/mcp/servers/%s/trust" % code, "POST", token=token)
        if any(snapshot.values()):
            print("  [ 复原 ] 已按快照恢复 trusted：%s"
                  % ([c for c, v in snapshot.items() if v],))


def run_assertions(base, hub, token):
    # ---------- M1 清单 ----------
    st, raw = call(base, "/api/v1/mcp/servers", token=token)
    d = jload(raw) or {}
    items = d.get("data") or []
    by_code = {i.get("code"): i for i in items}
    bad = []
    for code, want in EXPECT_TOOL_COUNT.items():
        it = by_code.get(code) or {}
        if it.get("source") != "BUILTIN":
            bad.append("%s.source=%r" % (code, it.get("source")))
        if it.get("trusted") is not False:
            bad.append("%s.trusted=%r" % (code, it.get("trusted")))
        if it.get("toolCount") != want:
            bad.append("%s.toolCount=%r≠%d" % (code, it.get("toolCount"), want))
    if (by_code.get("qq_mail") or {}).get("connected") is not False:
        bad.append("qq_mail.connected 应为 false")
    extra = [c for c in by_code if by_code[c].get("source") == "BUILTIN"
             and c not in EXPECT_TOOL_COUNT]
    if extra:
        bad.append("多出内置服务器 %s（请同步本脚本 EXPECT_TOOL_COUNT）" % extra)
    rec("M1 清单：4 个内置服务器、默认不可信、目录 6/0/0/5（两个已下线为 0）",
        st == 200 and not bad, "HTTP=%s 偏差=%s" % (st, bad or "无"))

    # ---------- M1b 已下线连接器必须不可信且无工具 ----------
    retired_bad = []
    for c in RETIRED_SERVERS:
        it = by_code.get(c)
        if it is None:
            retired_bad.append("%s 行被物理删了（留痕要用它，不该删）" % c)
            continue
        if it.get("trusted") is not False:
            retired_bad.append("%s.trusted=%r（已下线却仍可信 ⇒ manifest 会把工具塞给模型）"
                               % (c, it.get("trusted")))
        if it.get("toolCount") not in (0, None):
            retired_bad.append("%s.toolCount=%r（工具快照没清 ⇒ 界面会对着一台空服务器报工具数）"
                               % (c, it.get("toolCount")))
    rec("M1b 已下线的 wechat_work / wecom_group 保留行、不可信、无工具", not retired_bad,
        "偏差=%s" % (retired_bad or "无"))

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

    # ---------- M13 工具目录无漂移：DB 快照 == hub 实装 ----------
    # 背景：DB 的 mcp_server_tool 只在 trust 时从 hub 的 list_tools **覆盖写**一次，
    #   之后 hub 侧扩了工具而没人重新信任，DB 就一直是旧数（真发生过：wechat_work 13 却留 3）。
    #   界面/清单里的 toolCount 读的是 DB ⇒ 会对着用户报错数。故此处把判据**回到真源**（hub）再取一次。
    st_h, raw_h = call(hub, "/api/v1/connectors")
    hub_counts = {}
    if st_h == 200:
        for c in (jload(raw_h) or {}).get("connectors") or []:
            hub_counts[c.get("code")] = c.get("toolCount")
    st_s, raw_s = call(base, "/api/v1/mcp/servers", token=token)
    db_counts = {i.get("code"): i.get("toolCount")
                 for i in ((jload(raw_s) or {}).get("data") or [])
                 if i.get("source") == "BUILTIN"}
    # 只比**存活**服务器：已下线的两个 code 在 hub 侧已不存在（代码物理删除），
    # 拿它们的 DB 快照去和 hub 比必然「漂移」，那会把一次正确的删除误判成回归。
    live = [c for c in EXPECT_TOOL_COUNT if c not in RETIRED_SERVERS]
    drift = {c: (db_counts.get(c), hub_counts.get(c))
             for c in live
             if db_counts.get(c) != hub_counts.get(c)}
    # 反向断言：hub 里**不许**再出现已下线的 code（删干净了才算数，否则旧工具会重新流给模型）
    still_in_hub = {c: hub_counts.get(c) for c in RETIRED_SERVERS if c in hub_counts}
    rec("M13 工具目录无漂移（存活服务器 DB == hub；已下线的不在 hub）",
        st_h == 200 and st_s == 200 and not drift and not still_in_hub,
        "hubHTTP=%s dbHTTP=%s hub=%s db=%s 漂移=%s hub残留=%s"
        % (st_h, st_s, hub_counts, db_counts, drift or "无", still_in_hub or "无"))

    # ---------- M10 未登录 ----------
    st, raw = call(base, "/api/v1/mcp/servers")
    rec("M10 未登录 → 401", st == 401, "HTTP=%s body=%s" % (st, raw[:120]))

    failed = [r for r in RESULTS if not r[1]]
    print("\n%s（%d/%d）" % ("全部通过 ✅" if not failed else "存在失败 ❌", len(RESULTS) - len(failed), len(RESULTS)))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
