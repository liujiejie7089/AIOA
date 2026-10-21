# -*- coding: utf-8 -*-
"""用户端 H5 · 连接器面板「MCP」长期哨兵（2026-10-21 改版）。

UI 已改：内置 MCP 服务器**并入**对应连接器卡（卡内 .oa-mcp-inline 内嵌块），
不再单独出「MCP 服务器」卡 —— 否则同一能力出现两对同名卡（连接器一对 + MCP 一对）。
外部 MCP 服务器才单列「MCP 服务器（外部）」区（无外部时整区不渲染）。
两道闸不变：连接器授权（卡主按钮「连接」）→ MCP 信任（内嵌块「启用 MCP」）。

驱动方式（照 scripts/_check_oa_project_layout.py）：
  本地静态服务 user-client/ + page.route 打桩 /api/v1/** + chromium 兜底（glob 找 ms-playwright）。
断言（每条都可复算，离线可重复）：
  P1  面板只有 2 张连接器卡；「QQ邮箱」名字只出现 1 次（去重核心判据）；
      无外部服务器时无「MCP 服务器（外部）」区；QQ邮箱/企业微信卡内均有内嵌 MCP 块
  P2  两块内嵌 chip 都是「未启用」（种子 trusted=false）
  P3  点「启用 MCP」→ 抓真实请求 POST /v1/mcp/servers/qq_mail/trust；
      桩 {ok:true,toolCount:6} → toast 含 6，内嵌 chip 变「已启用」
  P4 （负向·分辨力核心）桩 {ok:false,toolCount:0} → toast 含「启用失败」，
      内嵌 chip 仍为「未启用」（实现若乐观置位则本条必红）
  P5  点「查看工具」→ 抓 GET /v1/mcp/servers/qq_mail/tools，出现 6 个工具名，
      且目录为精简形式（不含工具长描述）
  P6 （负向）桩 trusted:true,source:BUILTIN,connected:false → 内嵌 chip=「连接器未连接」，
      按钮「停用」（无「启用 MCP」）
  P7 （负向）GET /v1/mcp/servers 返回 500 → 连接器照常 2 张卡（主功能不被拖垮），
      两张卡内嵌块显示「MCP 加载失败」
  P8 （回归）授权成功 → 前端必须重新拉取 /mcp/servers 且内嵌 chip 变「已启用」

用法（由托管 python 3.13 跑，本机 Playwright 装在那套解释器里）：
  python scripts/_verify_oa_mcp_panel.py
"""
import functools
import glob
import http.server
import json
import os
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
CLIENT = REPO / "user-client"

PASS, FAIL = [], []
REQS = []                 # 抓到的 (method, url)
TRUSTED = set()           # 信任状态（信任成功后写入，列表桩据此返回 trusted）
SCEN = {}                 # 当前场景覆盖：trust_resp / mcp(覆盖列表) / mcp500

SEED_MCP = [
    {"code": "qq_mail", "name": "QQ邮箱", "source": "BUILTIN", "transport": "stdio",
     "trusted": False, "status": "OK", "lastError": None, "lastProbeAt": None,
     "connectorCode": "qq_mail", "toolCount": 0, "connected": True},
    {"code": "wecom", "name": "企业微信", "source": "BUILTIN", "transport": "stdio",
     "trusted": False, "status": "OK", "lastError": None, "lastProbeAt": None,
     "connectorCode": "wecom", "toolCount": 0, "connected": True},
]
SEED_CONNECTORS = [
    {"code": "qq_mail", "name": "QQ邮箱", "group": "邮箱", "icon": "mail", "status": "CONNECTED",
     "configReady": True, "summary": "已连接 · 收件箱", "connectedAt": "2026-10-20 09:00"},
    {"code": "wecom", "name": "企业微信", "group": "办公", "icon": "people", "status": "UNVERIFIED",
     "configReady": True, "summary": "未通过校验"},
]
SEED_TOOLS = [
    {"name": "list_folders", "description": "列出邮箱文件夹", "inputSchema": {}, "readOnly": True, "sort": 1},
    {"name": "read_mail", "description": "读取指定邮件", "inputSchema": {}, "readOnly": True, "sort": 2},
    {"name": "send_mail", "description": "发送邮件", "inputSchema": {}, "readOnly": False, "sort": 3},
    {"name": "move_mail", "description": "移动邮件", "inputSchema": {}, "readOnly": False, "sort": 4},
    {"name": "search_mail", "description": "搜索邮件", "inputSchema": {}, "readOnly": True, "sort": 5},
    {"name": "delete_mail", "description": "删除邮件", "inputSchema": {}, "readOnly": False, "sort": 6},
]
TOOL_NAMES = {t["name"] for t in SEED_TOOLS}


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print(("  [PASS] " if cond else "  [FAIL] ") + cid + ("" if cond else "  <- " + str(detail)[:300]))


def _json(o):
    return json.dumps(o, ensure_ascii=False)


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(CLIENT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def chromium_exe():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    for pat in ("chromium-*/chrome-win/chrome.exe",
                "chromium-*/chrome-win64/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
        hits = sorted(root.glob(pat)) if root.exists() else []
        if hits:
            return str(hits[-1])
    return None


def mcp_list():
    override = SCEN.get("mcp")
    if override is not None:
        if SCEN.get("authed"):
            # 授权成功后后端会返回 connected=true —— 用来验证前端有没有重新拉取
            return [dict(s, connected=True) if s.get("connectorCode") else dict(s) for s in override]
        return override
    out = []
    for s in SEED_MCP:
        s2 = dict(s)
        if s2["code"] in TRUSTED:
            s2["trusted"] = True
            s2["toolCount"] = 6
        out.append(s2)
    return out


def _route(route):
    url = route.request.url
    method = route.request.method
    REQS.append((method, url))
    p = url.split("?")[0].rstrip("/")
    if "/v1/mcp/servers" in p:
        if SCEN.get("mcp500") and p.endswith("/mcp/servers"):
            return route.fulfill(status=500, content_type="application/json",
                                 body=_json({"code": 1, "message": "internal error"}))
        if p.endswith("/trust"):
            code = p.split("/v1/mcp/servers/")[1].split("/trust")[0]
            d = SCEN.get("trust_resp", {"ok": True, "error": None, "toolCount": 6})
            if d.get("ok"):
                TRUSTED.add(code)
            return route.fulfill(status=200, content_type="application/json",
                                 body=_json({"code": 0, "message": "ok", "data": d}))
        if p.endswith("/untrust"):
            code = p.split("/v1/mcp/servers/")[1].split("/untrust")[0]
            TRUSTED.discard(code)
            return route.fulfill(status=200, content_type="application/json",
                                 body=_json({"code": 0, "message": "ok",
                                             "data": {"ok": True, "toolCount": 0}}))
        if p.endswith("/probe"):
            d = SCEN.get("probe_resp", {"ok": True, "tools": SEED_TOOLS, "error": None})
            return route.fulfill(status=200, content_type="application/json",
                                 body=_json({"code": 0, "message": "ok", "data": d}))
        if p.endswith("/tools"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=_json({"code": 0, "message": "ok", "data": SEED_TOOLS}))
        # 列表
        return route.fulfill(status=200, content_type="application/json",
                             body=_json({"code": 0, "message": "ok", "data": mcp_list()}))
    if "/v1/connectors" in p:
        # 凭据连接：成功后置 authed，让后续 /mcp/servers 返回 connected=true
        if p.endswith("/connect/credential"):
            SCEN["authed"] = True
            return route.fulfill(status=200, content_type="application/json",
                                 body=_json({"code": 0, "message": "ok",
                                             "data": {"status": "CONNECTED",
                                                      "accountLabel": "tester@qq.com"}}))
        # 详情（弹层要的 fields）
        rest = p.split("/v1/connectors/")[-1] if "/v1/connectors/" in p else ""
        if rest and "/" not in rest:
            return route.fulfill(status=200, content_type="application/json",
                                 body=_json({"code": 0, "message": "ok", "data": {
                                     "code": rest, "name": "QQ邮箱", "mode": "CREDENTIAL",
                                     "fields": [
                                         {"key": "email", "label": "QQ 邮箱地址", "required": True},
                                         {"key": "authCode", "label": "授权码", "type": "password",
                                          "required": True}]}}))
        data = SCEN.get("conn") or SEED_CONNECTORS
        if SCEN.get("authed"):
            data = [dict(c, status="CONNECTED", accountLabel="tester@qq.com")
                    if c.get("code") == "qq_mail" else dict(c) for c in data]
        return route.fulfill(status=200, content_type="application/json",
                             body=_json({"code": 0, "message": "ok", "data": data}))
    return route.fulfill(status=200, content_type="application/json",
                         body=_json({"code": 0, "message": "ok", "data": []}))


BOOT_JS = (
    "document.body.classList.add('auth');"
    "window.oaState.mode='oa';"
    "window.oaBoot();"
    "window.__toasts=[];"
    "(function(){var f=window.toast;window.toast=function(m){try{window.__toasts.push(String(m));}catch(e){}return f.apply(this,arguments);};})();"
    "window.oaGo('skills');"
    "var _seg=document.querySelector(\"#oaSkillsSeg button[data-seg='connectors']\"); if(_seg){_seg.click();}"
)


def new_page(browser):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.route("**/api/v1/**", _route)
    return page


def open_panel(page):
    page.goto(base + "/index.html", wait_until="domcontentloaded")
    page.evaluate(BOOT_JS)
    # 内置 MCP 已并入连接器卡（.oa-mcp-inline），不再有独立「MCP 服务器」卡
    page.wait_for_selector("#oaConnectorsList .conn-card .oa-mcp-inline", timeout=8000)
    page.wait_for_timeout(150)


def conn_card(page, name):
    """按连接器名找卡（新 UI：内置 MCP 内嵌在连接器卡里，不存在独立 MCP 卡）。"""
    for c in page.query_selector_all("#oaConnectorsList .conn-card"):
        n = c.query_selector(".conn-name")
        if n and name in n.inner_text():
            return c
    return None


def inline(page, name):
    c = conn_card(page, name)
    return c.query_selector(".oa-mcp-inline") if c else None


def inline_chip(page, name):
    el = inline(page, name)
    if el is None:
        return None
    chip = el.query_selector(".chip")
    return chip.inner_text().strip() if chip else None


def main():
    global base
    httpd, port = serve()
    base = "http://127.0.0.1:%d" % port
    exe = chromium_exe()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            # ---- P1 + P2：去重（两对→一对）+ 内嵌 MCP 块状态皆「未启用」 ----
            SCEN.clear(); TRUSTED.clear()
            pg = new_page(browser); open_panel(pg)
            cards = pg.query_selector_all("#oaConnectorsList .conn-card")
            panel_txt = pg.query_selector("#oaConnectorsList").inner_text()
            qq, wecom = inline(pg, "QQ邮箱"), inline(pg, "企业微信")
            chk("P1 面板只有 2 张卡（内置 MCP 不再单列，两对→一对）",
                len(cards) == 2, len(cards))
            chk("P1 「QQ邮箱」名字只出现 1 次（去重核心判据）",
                panel_txt.count("QQ邮箱") == 1, panel_txt.count("QQ邮箱"))
            chk("P1 无独立 MCP 服务器区（无外部服务器时整区不渲染）",
                "MCP 服务器（外部）" not in panel_txt, "外部区标题出现在面板中")
            chk("P1 QQ邮箱/企业微信卡内均有内嵌 MCP 块",
                qq is not None and wecom is not None,
                "qq=%s wecom=%s" % (qq is not None, wecom is not None))
            chips = [inline_chip(pg, "QQ邮箱"), inline_chip(pg, "企业微信")]
            chk("P2 两块内嵌 chip 都是 未启用", chips == ["未启用", "未启用"], chips)

            # ---- P3：启用 MCP（ok:true,toolCount:6）→ 抓请求 / toast 含 6 / chip 已启用 ----
            REQS.clear()
            conn_card(pg, "QQ邮箱").query_selector('[data-mcp-act="trust"]').click()
            pg.wait_for_function(
                "()=>{var c=document.querySelector('#oaConnectorsList .conn-card .oa-mcp-inline .chip');"
                "return c && c.textContent.indexOf('已启用')>=0;}", timeout=5000)
            toasts = pg.evaluate("()=>window.__toasts")
            hit = any(m == "POST" and "/v1/mcp/servers/qq_mail/trust" in u for m, u in REQS)
            chk("P3 抓到 POST /v1/mcp/servers/qq_mail/trust", hit, REQS)
            chk("P3 toast 含 6", any("6" in t for t in toasts), toasts)

            # ---- P5：查看工具 → 抓 GET tools / 出现 6 个工具名（精简为 code 行） ----
            REQS.clear()
            conn_card(pg, "QQ邮箱").query_selector('[data-mcp-act="tools"]').click()
            pg.wait_for_function(
                "()=>{var c=document.querySelector('#oaConnectorsList .conn-card .oa-mcp-inline');"
                "return c && c.innerText.indexOf('list_folders')>=0;}", timeout=5000)
            hit_tools = any(m == "GET" and "/v1/mcp/servers/qq_mail/tools" in u for m, u in REQS)
            chk("P5 抓到 GET /v1/mcp/servers/qq_mail/tools", hit_tools, REQS)
            codes = pg.evaluate(
                "()=>{var c=document.querySelector('#oaConnectorsList .conn-card .oa-mcp-inline');"
                "return [...c.querySelectorAll('code')].map(e=>e.textContent);}")
            shown = [n for n in codes if n in TOOL_NAMES]
            chk("P5 出现 6 个工具名", len(shown) == 6, shown)
            chk("P5 工具目录已精简（不含长描述）",
                pg.evaluate(
                    "()=>{var c=document.querySelector('#oaConnectorsList .conn-card .oa-mcp-inline');"
                    "return c.innerText.indexOf('列出邮箱文件夹')<0;}"),
                "工具描述仍出现在目录中")
            pg.close()

            # ---- P4（负向）：ok:false → toast 含 启用失败 / chip 仍为 未启用 ----
            SCEN.clear(); TRUSTED.clear()
            SCEN["trust_resp"] = {"ok": False, "error": "MCP 网关不可用：ConnectException", "toolCount": 0}
            pg = new_page(browser); open_panel(pg)
            conn_card(pg, "QQ邮箱").query_selector('[data-mcp-act="trust"]').click()
            pg.wait_for_timeout(400)
            toasts = pg.evaluate("()=>window.__toasts")
            chip = inline_chip(pg, "QQ邮箱")
            chk("P4 toast 含 启用失败", any("启用失败" in t for t in toasts), toasts)
            chk("P4 chip 仍为 未启用（未乐观置位）", chip == "未启用", chip)
            pg.close()

            # ---- P6（负向）：trusted:true,BUILTIN,connected:false → 连接器未连接 + 停用按钮 ----
            SCEN.clear(); TRUSTED.clear()
            SCEN["mcp"] = [{"code": "qq_mail", "name": "QQ邮箱", "source": "BUILTIN", "transport": "stdio",
                            "trusted": True, "status": "OK", "lastError": None, "lastProbeAt": None,
                            "connectorCode": "qq_mail", "toolCount": 4, "connected": False}]
            pg = new_page(browser); open_panel(pg)
            chip = inline_chip(pg, "QQ邮箱")
            box = inline(pg, "QQ邮箱")
            untrust = box.query_selector('[data-mcp-act="untrust"]') if box else None
            trust = box.query_selector('[data-mcp-act="trust"]') if box else None
            chk("P6 chip=连接器未连接", chip == "连接器未连接", chip)
            chk("P6 显示 停用 且无 启用 MCP", untrust is not None and trust is None,
                "untrust=%s trust=%s" % (untrust is not None, trust is not None))
            pg.close()

            # ---- P7（负向）：/v1/mcp/servers 500 → 连接器卡照常，内嵌块显示加载失败 ----
            SCEN.clear(); TRUSTED.clear(); SCEN["mcp500"] = True
            pg = new_page(browser); open_panel(pg)
            cards = pg.query_selector_all("#oaConnectorsList .conn-card")
            bad = pg.evaluate(
                "()=>[...document.querySelectorAll('#oaConnectorsList .conn-card')]"
                ".filter(c=>c.querySelector('.oa-mcp-inline')"
                "&& c.querySelector('.oa-mcp-inline').innerText.indexOf('MCP 加载失败')>=0).length;")
            chk("P7 连接器面板仍有 2 张连接器卡（主功能未被 MCP 拖垮）", len(cards) == 2, len(cards))
            chk("P7 两张卡的内嵌块均显示 MCP 加载失败", bad == 2, bad)
            pg.close()

            # ---- P8（回归）：授权成功 → 内嵌块必须重新拉取并变已启用 ----
            # 线上真实症状：填完授权码、库里已 CONNECTED，MCP 状态却一直停在「连接器未连接」——
            # 因为 loadMcp() 有 mcpLoaded 幂等闸。判据：真的再发一次 GET /v1/mcp/servers 且 chip 变了。
            SCEN.clear(); TRUSTED.clear()
            SCEN["mcp"] = [{"code": "qq_mail", "name": "QQ邮箱", "source": "BUILTIN", "transport": "stdio",
                            "trusted": True, "status": "OK", "lastError": None, "lastProbeAt": None,
                            "connectorCode": "qq_mail", "toolCount": 6, "connected": False}]
            # 连接器从「未连接」起步，卡上才有「连接」按钮（= 授权入口）
            SCEN["conn"] = [{"code": "qq_mail", "name": "QQ邮箱", "group": "邮箱", "icon": "mail",
                             "status": "", "configReady": True, "summary": "", "connectedAt": None}]
            pg = new_page(browser); open_panel(pg)
            chip0 = inline_chip(pg, "QQ邮箱")
            REQS.clear()
            # 新 UI：授权入口 = 连接器卡主按钮「连接」（不再有独立的「去授权」按钮）
            conn_card(pg, "QQ邮箱").query_selector('[data-act="connect"]').click()
            pg.wait_for_selector(".oa-conn-dlg input[data-fkey]", timeout=5000)
            pg.fill(".oa-conn-dlg input[data-fkey='email']", "tester@qq.com")
            pg.fill(".oa-conn-dlg input[data-fkey='authCode']", "dummy-auth-code")
            pg.query_selector("#oaConnSubmit").click()
            # 不用裸 wait_for_function：没修好时它会抛 TimeoutError，整个脚本中断、
            # 连「合计」都不打印 —— 看起来像环境抖动，而不是一条明确的失败断言。
            chip1 = chip0
            try:
                pg.wait_for_function(
                    "()=>{var c=document.querySelector('#oaConnectorsList .conn-card .oa-mcp-inline .chip');"
                    "return c && c.textContent.indexOf('已启用')>=0;}", timeout=6000)
            except Exception:
                pass
            chip1 = inline_chip(pg, "QQ邮箱") or chip1

            post_i = next((i for i, (m, u) in enumerate(REQS)
                           if m == "POST" and u.endswith("/connect/credential")), -1)
            get_after = [u for i, (m, u) in enumerate(REQS)
                         if i > post_i >= 0 and m == "GET" and u.split("?")[0].rstrip("/").endswith("/mcp/servers")]
            chk("P8 授权前 chip=连接器未连接", chip0 == "连接器未连接", chip0)
            chk("P8 授权成功后重新拉了 GET /v1/mcp/servers", bool(get_after), REQS)
            chk("P8 授权成功后 chip 变为已启用（不再停在连接器未连接）", chip1 == "已启用",
                "chip0=%s chip1=%s" % (chip0, chip1))
            pg.close()

            browser.close()
    finally:
        httpd.shutdown()

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
