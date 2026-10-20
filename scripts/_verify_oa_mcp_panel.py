# -*- coding: utf-8 -*-
"""用户端 H5 · 连接器面板「MCP 服务器」区 长期哨兵。

驱动方式（照 scripts/_check_oa_project_layout.py）：
  本地静态服务 user-client/ + page.route 打桩 /api/v1/** + chromium 兜底（glob 找 ms-playwright）。
断言（每条都可复算，离线可重复）：
  P1  进「插件-技能-连接器 → 连接器」后出现标题「MCP 服务器」，且 2 张卡（QQ邮箱/企业微信）
  P2  两卡状态 chip 都为「未启用」（种子 trusted=false）
  P3  点第一张卡「信任并启用」→ 抓真实请求 POST /v1/mcp/servers/qq_mail/trust；
      桩 {ok:true,toolCount:6} → toast 含 6，卡片 chip 变「已启用」
  P4 （负向·分辨力核心）桩 {ok:false,toolCount:0} → toast 含「启用失败」，
      卡片 chip 仍为「未启用」（实现若乐观置位则本条必红）
  P5  点「查看工具」→ 抓 GET /v1/mcp/servers/qq_mail/tools，页面出现 6 个工具名
  P6  （负向）桩 trusted:true,source:BUILTIN,connected:false → chip 必为「连接器未连接」，按钮区「取消信任」
  P7  （负向）GET /v1/mcp/servers 返回 500 → 连接器面板仍显示原有 2 张连接器卡，
      MCP 区块显示加载失败文案（MCP 挂了不许把整面板打成错误页）

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
        return route.fulfill(status=200, content_type="application/json",
                             body=_json({"code": 0, "message": "ok", "data": SEED_CONNECTORS}))
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
    page.wait_for_selector("#oaConnectorsList .oa-mcp-section", timeout=8000)
    page.wait_for_timeout(150)


def mcp_cards(page):
    return page.query_selector_all("#oaConnectorsList .oa-mcp-section .conn-card")


def main():
    global base
    httpd, port = serve()
    base = "http://127.0.0.1:%d" % port
    exe = chromium_exe()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            # ---- P1 + P2：标题、2 张卡、状态皆「未启用」 ----
            SCEN.clear(); TRUSTED.clear()
            pg = new_page(browser); open_panel(pg)
            sec = pg.query_selector("#oaConnectorsList .oa-mcp-section")
            title = sec.query_selector(".sec-title").inner_text().strip()
            cards = mcp_cards(pg)
            names = [c.query_selector(".conn-name").inner_text().strip() for c in cards]
            chk("P1 标题=MCP 服务器 且 2 张卡(QQ邮箱/企业微信)",
                title == "MCP 服务器" and len(cards) == 2
                and any("QQ邮箱" in n for n in names) and any("企业微信" in n for n in names),
                "title=%r cards=%d names=%s" % (title, len(cards), names))
            chips = [c.query_selector(".chip").inner_text().strip() for c in cards]
            chk("P2 两张卡状态 chip 都是 未启用", chips == ["未启用", "未启用"], chips)

            # ---- P3：信任并启用（ok:true,toolCount:6）→ 抓请求 / toast 含 6 / chip 已启用 ----
            REQS.clear()
            first = cards[0]
            first.query_selector('[data-mcp-act="trust"]').click()
            pg.wait_for_function(
                "()=>{var c=document.querySelector('#oaConnectorsList .oa-mcp-section .conn-card .chip');"
                "return c && c.textContent.indexOf('已启用')>=0;}", timeout=5000)
            toasts = pg.evaluate("()=>window.__toasts")
            hit = any(m == "POST" and "/v1/mcp/servers/qq_mail/trust" in u for m, u in REQS)
            chk("P3 抓到 POST /v1/mcp/servers/qq_mail/trust", hit, REQS)
            chk("P3 toast 含 6", any("6" in t for t in toasts), toasts)

            # ---- P5：查看工具 → 抓 GET tools / 出现 6 个工具名 ----
            REQS.clear()
            pg.query_selector("#oaConnectorsList .oa-mcp-section .conn-card [data-mcp-act='tools']").click()
            pg.wait_for_function(
                "()=>{var c=document.querySelector('#oaConnectorsList .oa-mcp-section .conn-card');"
                "return c && c.innerText.indexOf('list_folders')>=0;}", timeout=5000)
            hit_tools = any(m == "GET" and "/v1/mcp/servers/qq_mail/tools" in u for m, u in REQS)
            chk("P5 抓到 GET /v1/mcp/servers/qq_mail/tools", hit_tools, REQS)
            codes = pg.evaluate(
                "()=>[...document.querySelectorAll('#oaConnectorsList .oa-mcp-section .conn-card code')].map(e=>e.textContent)")
            shown = [n for n in codes if n in TOOL_NAMES]
            chk("P5 出现 6 个工具名", len(shown) == 6, shown)
            pg.close()

            # ---- P4（负向）：ok:false → toast 含 启用失败 / chip 仍为 未启用 ----
            SCEN.clear(); TRUSTED.clear()
            SCEN["trust_resp"] = {"ok": False, "error": "MCP 网关不可用：ConnectException", "toolCount": 0}
            pg = new_page(browser); open_panel(pg)
            pg.query_selector("#oaConnectorsList .oa-mcp-section .conn-card [data-mcp-act='trust']").click()
            pg.wait_for_timeout(400)
            toasts = pg.evaluate("()=>window.__toasts")
            chip = pg.query_selector("#oaConnectorsList .oa-mcp-section .conn-card .chip").inner_text().strip()
            chk("P4 toast 含 启用失败", any("启用失败" in t for t in toasts), toasts)
            chk("P4 chip 仍为 未启用（未乐观置位）", chip == "未启用", chip)
            pg.close()

            # ---- P6（负向）：trusted:true,BUILTIN,connected:false → 连接器未连接 + 取消信任 ----
            SCEN.clear(); TRUSTED.clear()
            SCEN["mcp"] = [{"code": "qq_mail", "name": "QQ邮箱", "source": "BUILTIN", "transport": "stdio",
                            "trusted": True, "status": "OK", "lastError": None, "lastProbeAt": None,
                            "connectorCode": "qq_mail", "toolCount": 4, "connected": False}]
            pg = new_page(browser); open_panel(pg)
            chip = pg.query_selector("#oaConnectorsList .oa-mcp-section .conn-card .chip").inner_text().strip()
            untrust = pg.query_selector("#oaConnectorsList .oa-mcp-section .conn-card [data-mcp-act='untrust']")
            trust = pg.query_selector("#oaConnectorsList .oa-mcp-section .conn-card [data-mcp-act='trust']")
            chk("P6 chip=连接器未连接", chip == "连接器未连接", chip)
            chk("P6 显示 取消信任 且无 信任并启用", untrust is not None and trust is None,
                "untrust=%s trust=%s" % (untrust is not None, trust is not None))
            pg.close()

            # ---- P7（负向）：/v1/mcp/servers 500 → 连接器照常 + MCP 区加载失败 ----
            SCEN.clear(); TRUSTED.clear(); SCEN["mcp500"] = True
            pg = new_page(browser); open_panel(pg)
            conn_n = pg.evaluate(
                "()=>{var list=document.querySelector('#oaConnectorsList');"
                "var sec=document.querySelector('#oaConnectorsList .oa-mcp-section');"
                "return [...list.querySelectorAll('.conn-card')].filter(c=>!sec.contains(c)).length;}")
            mcp_txt = pg.query_selector("#oaConnectorsList .oa-mcp-section").inner_text()
            chk("P7 连接器面板仍有 2 张连接器卡", conn_n == 2, conn_n)
            chk("P7 MCP 区块显示加载失败文案", "MCP 加载失败" in mcp_txt, mcp_txt[:80])
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
