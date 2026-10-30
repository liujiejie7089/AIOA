#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""企业微信「扫码」连接器（wecom_cli）端到端哨兵 —— 一人一账号 + 数字人可读本人企微数据。

要防的是什么
------------
这条链路有四个「看起来通了其实没通」的位置，任何一处错都表现为用户视角的同一句话
「绑定成功了，但数字人还是读不到我的企微」：

  ① **目录判据写错**：CLI 的 `credentials.enc` 是直接落在 `WECOM_CLI_CONFIG_DIR` 下的，
     不会自己套一层 `personal/`（实测见 profiles.cli_dir）。判据多写一层 ⇒ 永远判定未绑定。
  ② **契约写错**：hub 的 `/api/v1/wecom_cli/*` 回 `{code,message,data}`，与
     `/api/v1/connectors/*` 的 `{ok,error}` 不是一套。Java 若复用了凭据网关，
     每一次成功都会被判成失败并抛 400。
  ③ **连接态没落库**：manifest 闸门读的是 `connector_connection`，不是 hub 的目录。
     扫码成功但库里没 CONNECTED ⇒ 工具从模型手里消失（连上了反而不能用）。
  ④ **隔离失效**：用户 A 扫码后，B 也能拿到工具 —— 这是最严重的一条（越权读他人数据）。

判据纪律（铁律 7/12）
--------------------
- 「已绑定」必须回 **磁盘** 再取一次（credentials.enc 是否真的在），不信接口自述；
- 「manifest 放行」必须看 Java 的 `/mcp/manifest`，不看 hub 的 /health；
- 「数字人能读到数据」必须真的走一趟 MCP 协议调工具，不看工具目录里有没有这个工具名。

前置
----
Java :8080 在线（V102 已建 connector_def/mcp_server 行）、hub :8099 在线、
wecom_cli 已 trust（否则 manifest 不出现，S8 会红）。
开发态通常设 `AIOS_WECOM_CLI_SHARED_PROFILE`（start-all.sh 在 WECOM_MOCK=1 时自动给），
否则本机没有第二个已扫码账号，S2/S6 会红 —— 那是环境问题，不是代码问题，脚本会明确提示。

用法
----
    D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_wecom_cli.py
    可选：--base http://127.0.0.1:8080 --hub http://127.0.0.1:8099
          --user zhangsan --password User@123 --other admin --other-password Admin@123
退出码 = 失败项数（0 = 全绿）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

REPO = Path(__file__).resolve().parent.parent
HUB_SRC = REPO / "mcp-hub"
if str(HUB_SRC) not in sys.path:
    sys.path.insert(0, str(HUB_SRC))

CODE = "wecom_cli"
RESULTS: list[tuple[str, bool, str]] = []


def rec(name, ok, det=""):
    RESULTS.append((name, ok, det))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" —— " + det) if det else ""))


def call(base, path, method="GET", token=None, body=None, timeout=40):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, "TRANSPORT_ERROR: %s: %s" % (type(e).__name__, e)


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


def data_of(raw):
    d = jload(raw)
    v = d.get("data")
    return v if isinstance(v, (dict, list)) else {}


def login(base, user, password):
    st, raw = call(base, "/api/v1/auth/login", "POST",
                   body={"username": user, "password": password})
    return jload(raw).get("data", {}).get("accessToken") or ""


# ---------------- 直接驱动 CLI（不经过 hub）：目录隔离的第一手证据 ----------------

def cli_bin() -> str:
    from mcp_hub.wecom_cli import runner
    return runner.bin_path()


def cli_status(config_dir: Path) -> str:
    """把 WECOM_CLI_CONFIG_DIR 指向给定目录，读 CLI 自报的授权状态。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("WECOM_CLI_ADDITIONAL_HEADERS_")}
    env["WECOM_CLI_CONFIG_DIR"] = str(config_dir)
    env.setdefault("NO_COLOR", "1")
    p = subprocess.run([cli_bin(), "auth", "show", "--status"], capture_output=True,
                       env=env, cwd=str(config_dir), timeout=60)
    out = (p.stdout or b"").decode("utf-8", "replace").strip()
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    return (out or err or "exit=%s" % p.returncode).splitlines()[0].strip()


# ---------------- MCP：真的走协议调工具 ----------------

async def mcp_call(hub: str, token: str, tool: str, args: dict) -> tuple[bool, str]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = hub.rstrip("/") + "/mcp/" + CODE
    async with streamablehttp_client(url, headers={"Authorization": "Bearer " + token}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
            text = ""
            for c in (res.content or []):
                text += getattr(c, "text", "") or ""
            return (not res.isError), text


async def mcp_list(hub: str, token: str) -> list[str]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = hub.rstrip("/") + "/mcp/" + CODE
    async with streamablehttp_client(url, headers={"Authorization": "Bearer " + token}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.list_tools()
            return [t.name for t in (res.tools or [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AIOS_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--hub", default=os.environ.get("AIOS_HUB", "http://127.0.0.1:8099"))
    ap.add_argument("--user", default="zhangsan")
    ap.add_argument("--password", default="User@123")
    ap.add_argument("--other", default="admin")
    ap.add_argument("--other-password", default="Admin@123")
    args = ap.parse_args()
    base, hub = args.base.rstrip("/"), args.hub.rstrip("/")

    print("== 企业微信扫码连接器验收 @ %s（hub %s）==" % (base, hub))

    # ---- S1 hub 侧真的挂上了这台服务器 ----
    st, raw = call(hub, "/health", timeout=10)
    servers = jload(raw).get("servers") or {}
    rec("S1 hub /health 含 wecom_cli 且工具数为 5",
        st == 200 and servers.get(CODE) == 5,
        "servers=%s" % json.dumps(servers, ensure_ascii=False))

    # ---- S2 目录即身份：①空目录必须 unauthorized（第一手） ②布局判据不许「多套一层」 ----
    # ②是回归重点：CLI 的 credentials.enc 直接落在 WECOM_CLI_CONFIG_DIR 下，
    #   判据若写成 <base>/personal/credentials.enc 而 CLI 目录又是 <base>，
    #   就会「扫码成功但永远判定未绑定」。这里用临时目录把三种情形都钉住。
    from mcp_hub.wecom_cli import profiles

    tmp = Path(tempfile.mkdtemp(prefix="wcli-s2-"))
    try:
        empty_status = cli_status(tmp)
        base_dir = tmp / "t" / "u"
        (base_dir / "personal").mkdir(parents=True, exist_ok=True)
        (base_dir / "personal" / "credentials.enc").write_bytes(b"x")
        laid_out = (profiles.cli_dir(base_dir) == base_dir / "personal"
                    and profiles.is_authorized(base_dir))
        # 兼容「调用方直接给 CLI 目录」：credentials.enc 已在根上时不许再套一层
        (base_dir / "credentials.enc").write_bytes(b"x")
        direct = (profiles.cli_dir(base_dir) == base_dir and profiles.is_authorized(base_dir))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rec("S2 目录即身份：空目录 unauthorized，且 cli_dir 不会多套/少套一层 personal",
        "unauthorized" in empty_status.lower() and laid_out and direct,
        "empty=%r 布局=%s 直给CLI目录=%s" % (empty_status, laid_out, direct))

    tok = login(base, args.user, args.password)
    if not tok:
        rec("S0 登录 %s" % args.user, False, "拿不到 accessToken，后续全部不可验")
        print("\n== 汇总：%d 项，通过 0，失败 %d ==" % (len(RESULTS), len(RESULTS)))
        return len(RESULTS)

    # ---- S3 连接器目录里它是 QR 形态 ----
    st, raw = call(base, "/api/v1/connectors", token=tok)
    items = data_of(raw) or []
    mine = next((c for c in items if c.get("code") == CODE), None) if isinstance(items, list) else None
    rec("S3 连接器目录有 wecom_cli 且 authMode=QR、应用配置就绪",
        st == 200 and mine is not None and mine.get("authMode") == "QR"
        and mine.get("configReady") is True,
        json.dumps(mine, ensure_ascii=False)[:220] if mine else "目录里没有 %s：%s" % (CODE, raw[:160]))

    # ---- S4 详情/start 都认 QR ----
    st_d, raw_d = call(base, "/api/v1/connectors/" + CODE, token=tok)
    st_s, raw_s = call(base, "/api/v1/connectors/%s/connect/start" % CODE, "POST",
                       token=tok, body={})
    d, s = data_of(raw_d), data_of(raw_s)
    rec("S4 详情 mode=QR 且 connect/start 回 mode=QR（不给 authUrl，避免误跳转）",
        st_d == 200 and st_s == 200 and d.get("mode") == "QR" and s.get("mode") == "QR"
        and not s.get("authUrl"),
        "detail.mode=%r start=%s" % (d.get("mode"), json.dumps(s, ensure_ascii=False)[:160]))

    # ---- S5 负向：非 QR 连接器不许走扫码端点（否则等于开放「拿别人身份起扫码」） ----
    # 判据看 body 的业务码，不看 HTTP 状态：本项目业务异常统一是 HTTP 200 + code!=0
    #（GlobalExceptionHandler），拿 4xx 当判据会把「拒绝了」误报成「通过了」。
    st_n, raw_n = call(base, "/api/v1/connectors/qq_mail/qr", "POST", token=tok, body={})
    nb = jload(raw_n)
    rec("S5 非 QR 连接器调 /qr 被业务拒绝（code!=0 且提示不支持扫码、不返回二维码）",
        nb.get("code") != 0 and "扫码" in str(nb.get("message") or "")
        and "qr" not in data_of(raw_n),
        "http=%s body=%s" % (st_n, raw_n[:160]))

    # ---- S6 扫码状态：以 CLI 目录为准 ----
    st, raw = call(base, "/api/v1/connectors/%s/qr-status" % CODE, token=tok)
    qs = data_of(raw)
    rec("S6 qr-status 报已授权且带显示名",
        st == 200 and qs.get("authorized") is True and (qs.get("accountLabel") or "").strip() != "",
        json.dumps(qs, ensure_ascii=False)[:200])

    # ---- S7 绑定：返回 CONNECTED，且第二源（库投影）也 CONNECTED ----
    st_b, raw_b = call(base, "/api/v1/connectors/%s/qr-bind" % CODE, "POST", token=tok)
    b = data_of(raw_b)
    st, raw = call(base, "/api/v1/connectors", token=tok)
    items = data_of(raw) or []
    mine2 = next((c for c in items if c.get("code") == CODE), None) if isinstance(items, list) else None
    rec("S7 qr-bind 后连接态落库为 CONNECTED（第二源：目录接口）",
        st_b == 200 and b.get("status") == "CONNECTED"
        and mine2 is not None and mine2.get("status") == "CONNECTED"
        and (mine2.get("accountLabel") or "").strip() != "",
        "bind=%s 目录=%s" % (json.dumps(b, ensure_ascii=False)[:140],
                             json.dumps({k: mine2.get(k) for k in ("status", "accountLabel")},
                                        ensure_ascii=False) if mine2 else "缺"))

    # ---- S8 manifest 放行（agent 的唯一入口） ----
    st, raw = call(base, "/api/v1/mcp/manifest", token=tok)
    man = data_of(raw) or []
    hit = next((m for m in man if m.get("code") == CODE), None) if isinstance(man, list) else None
    rec("S8 manifest 含 wecom_cli，url 指向 hub 的 /mcp/wecom_cli，工具数 5",
        st == 200 and hit is not None and str(hit.get("url", "")).endswith("/mcp/" + CODE)
        and hit.get("toolCount") == 5,
        json.dumps(hit, ensure_ascii=False) if hit else "manifest 里没有 %s（是否漏了 trust？）" % CODE)

    # ---- S9 隔离性：没绑定的另一个用户，manifest 不给这台服务器 ----
    otok = login(base, args.other, args.other_password)
    if not otok:
        rec("S9 未绑定用户的 manifest 不含 wecom_cli", False, "另一用户登录失败，无法验证隔离")
    else:
        st, raw = call(base, "/api/v1/mcp/manifest", token=otok)
        oman = data_of(raw) or []
        ocodes = [m.get("code") for m in oman] if isinstance(oman, list) else []
        rec("S9 未绑定用户的 manifest 不含 wecom_cli（越权防线）",
            st == 200 and CODE not in ocodes, "另一用户拿到：%s" % ocodes)

    # ---- S10/S11/S12 真的走 MCP 调工具 ----
    try:
        names = asyncio.run(mcp_list(hub, tok))
    except Exception as e:  # noqa: BLE001
        names = []
        rec("S10 MCP 握手并列出 5 个工具", False, "%s: %s" % (type(e).__name__, e))
    else:
        want = {"whoami", "contact_search", "recent_group_sessions", "session_messages", "mail_search"}
        rec("S10 MCP 握手并列出 5 个只读工具", want.issubset(set(names)),
            "拿到 %s" % sorted(names))

    def _try(tool, targs):
        try:
            return asyncio.run(mcp_call(hub, tok, tool, targs))
        except Exception as e:  # noqa: BLE001
            return False, "%s: %s" % (type(e).__name__, e)

    ok, text = _try("whoami", {})
    who = jload(text) if text.strip().startswith("{") else {}
    my_name = (who.get("userName") or "").strip()
    rec("S11 MCP whoami 返回真人身份名（数字人知道自己代谁查）",
        ok and len(my_name) >= 2, text[:200])

    # 用**本人姓名**当关键词去搜，并断言搜得到自己 —— 这样「接口返回成功但永远是空壳」
    # 也会被判红（早先版本用了一个企业里根本不存在的关键词，count=0 照样 PASS，等于没测）。
    kw = my_name[:1] or "刘"
    ok, text = _try("contact_search", {"keywords": kw})
    hit = jload(text) if text.strip().startswith("{") else {}
    members = hit.get("members") or []
    rec("S12 MCP contact_search 用本人姓名真查回通讯录（count>=1 且命中本人）",
        ok and int(hit.get("count") or 0) >= 1
        and any((m.get("name") or "") == my_name for m in members),
        "kw=%r -> %s" % (kw, text[:240]))

    # 群消息/邮件：允许业务上没数据，但不允许「接口层失败」
    ok_g, text_g = _try("recent_group_sessions", {"days": 7})
    ok_m, text_m = _try("mail_search", {"days": 7, "limit": 3})
    rec("S13 recent_group_sessions / mail_search 至少一个返回成功（允许业务无数据）",
        ok_g or ok_m, "groups=%s mail=%s" % (str(ok_g) + ":" + text_g[:80],
                                            str(ok_m) + ":" + text_m[:80]))

    # ---- S14 解绑要删干净，再绑回来（保证哨兵可重复跑） ----
    st_x, raw_x = call(base, "/api/v1/connectors/%s/disconnect" % CODE, "POST", token=tok)
    st, raw = call(base, "/api/v1/connectors", token=tok)
    items = data_of(raw) or []
    after = next((c for c in items if c.get("code") == CODE), None) if isinstance(items, list) else None
    st, raw = call(base, "/api/v1/mcp/manifest", token=tok)
    man = data_of(raw) or []
    gone = CODE not in ([m.get("code") for m in man] if isinstance(man, list) else [])
    rec("S14 disconnect 后 status=NEED_AUTH 且 manifest 收回工具（连上了才有、断开了就没了）",
        st_x == 200 and after is not None and after.get("status") == "NEED_AUTH" and gone,
        "status=%s manifest_has=%s" % (after.get("status") if after else "缺", not gone))

    st_r, raw_r = call(base, "/api/v1/connectors/%s/qr-bind" % CODE, "POST", token=tok)
    rec("S15 收尾：重新绑定回 CONNECTED（保证下次跑哨兵前置成立）",
        st_r == 200 and data_of(raw_r).get("status") == "CONNECTED",
        raw_r[:160])

    failed = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" %
          (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n, _, det in failed:
        print("  - %s：%s" % (n, det))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
