# -*- coding: utf-8 -*-
"""用户端「进入项目」后的两件事：**布局**（数字人不再吃半屏）与**会话记忆不丢**。

来源：用户 2026-10-11 指令 ——「检查用户端进入项目时，数字人图像占用屏幕一半的问题，
与 ai 回答只能在下半部分，修正一下，且上一次会话记忆不能丢失」。

为什么用「本地静态服务 + page.route 打桩」而不是 file:// ：
  进入项目要真的走 enterProject（它会拉项目详情、拉项目数字人、建/取项目会话、载入历史消息），
  只有把 /api/v1/** 打桩成可控响应，才能在**离线、可重复**的前提下驱动真实代码路径。
  这也让「历史消息仍在坞里」变成可断言的事实，而不是靠肉眼。

判据（每条都可复算）：
  L1 ★居中：机器人的水平中心必须与 stage 中心对齐（≤2px）。
     这条专门钉住一个真实缺陷：`.robot-wrap` 是 <button>（inline-block），
     `margin:0 auto` 对它**不生效** ⇒ 机器人贴左、与居中的标题错位（修复前实测 left=11px，容器中心 195px）。
  L2 紧凑：会话态机器人的高度占视口比 ≤ 18%（修复前 844 下 17.9%、640 下 23.3%）。
  L3 ★回答区不再只在下半部分：对话坞**自身顶部** ≤ 260px。
     阈值依据（均为实测，不是拍的）：修复前 271px（不含项目 chip）/ ≈299px（含 chip），
     修复后 249px ⇒ 取 260 留出 11px 余量，同时对旧行为仍有 ≥11px 的区分度。
     为什么不量「首条气泡的 top」：矮屏下对话坞会滚动（oaScrollDock），
     首条气泡可能已被滚出可视区、其 rect.top 反映的是滚动位置而不是布局位置（本轮初版即错在这里）。
  M1 记忆：进入项目后，坞里仍渲染出该项目会话的历史消息（3 条）。
  M2 ★记忆：进入同一项目**复用**同一条会话（新建次数不增加）；且清掉复用记忆后才新建
     —— 后者是**负向对照**，证明 M2 的断言不是恒真。
  M3 记忆：强制重渲染（oaBoot）不清空对话坞。

用法：python scripts/_check_oa_project_layout.py
"""
import functools
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
CLIENT = REPO / "user-client"

PASS, FAIL = [], []
POSTED_CONVS = []          # 记录 POST /v1/conversations 的次数（会话是否被新建）
HISTORY = [
    {"role": "user", "content": "上次我们说到哪了？"},
    {"role": "ai", "content": "上次停在经费表第二稿，我按你的意见改了两处。"},
    {"role": "ai", "content": "需要我把它导成一份纪要吗？"},
]


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print(("  [PASS] " if cond else "  [FAIL] ") + cid + ("" if cond else "  <- " + str(detail)[:300]))


HISTORY_CONTENTS = [h["content"] for h in HISTORY]


def _history_kept(m):
    """判据：三条历史消息**都必须**仍出现在坞里。

    注意**不能**断言「气泡数恰好等于 3」—— 进入项目时还会追加一条项目说明卡（合法），
    那样的断言会把正确行为判成失败（本轮初版就犯了这个错）。
    """
    texts = m.get("stateTexts") or []
    return all(any(c in t for t in texts) for c in HISTORY_CONTENTS)


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(CLIENT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def chromium_exe():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    for pat in ("chromium-*/chrome-win64/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
        hits = sorted(root.glob(pat)) if root.exists() else []
        if hits:
            return str(hits[-1])
    return None


def main():
    httpd, port = serve()
    base = "http://127.0.0.1:%d" % port
    exe = chromium_exe()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))

            def probe(vh):
                page = browser.new_page(viewport={"width": 390, "height": vh})
                page.route("**/api/v1/**", lambda route: _route(route))
                page.goto(base + "/index.html", wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                page.evaluate("()=>{document.body.classList.add('auth');window.oaState.mode='oa';window.oaBoot();}")
                page.wait_for_timeout(300)

                POSTED_CONVS.clear()
                # 真的驱动 enterProject（含项目详情 / 项目数字人 / 建会话 / 载入历史）
                page.evaluate("()=>window.oaEnterProject({id:7,name:'某某区发展和改革局数据治理项目',projectType:'BIZ'})")
                page.wait_for_timeout(700)

                m = page.evaluate("""()=>{
                  const q=s=>document.querySelector(s);
                  const B=e=>{if(!e)return null;const r=e.getBoundingClientRect();
                    return {top:r.top,left:r.left,h:r.height,w:r.width,cx:r.left+r.width/2};};
                  const st=B(q('#oaStage')), rb=B(q('#oaRobot'));
                  const bubs=[...document.querySelectorAll('#oaDockList .bub')];
                  const first=bubs.length?bubs[0].getBoundingClientRect():null;
                  const dock=B(q('#oaDock'));
                  return {vh:innerHeight, chatting:q('#v-home').classList.contains('chatting'),
                          stage:st, robot:rb, bubCount:bubs.length,
                          firstTop:first?first.top:null,
                          dockTop:dock?dock.top:null, dockH:dock?dock.h:null,
                          stateTexts:bubs.map(b=>b.innerText.trim())};
                }""")
                print("      量测：robotH=%.0f(%.1f%%) 对话区top=%.0f(%.1f%%) 对话区h=%.1f%%"
                      % (m["robot"]["h"], m["robot"]["h"] / m["vh"] * 100,
                         m["dockTop"] or -1, (m["dockTop"] or 0) / m["vh"] * 100,
                         (m["dockH"] or 0) / m["vh"] * 100))
                after_first = dict(m)
                after_first["posted"] = len(POSTED_CONVS)
                after_first["convId"] = page.evaluate("()=>window.oaState.projectConvId[7] || null")

                # M2 负向对照：清掉复用记忆后，再进入同一项目**应当**新建一条会话
                page.evaluate("()=>{delete window.oaState.projectConvId[7];}")
                page.evaluate("()=>window.oaEnterProject({id:7,name:'某某区域',projectType:'BIZ'})")
                page.wait_for_timeout(600)
                after_clear = {"posted": len(POSTED_CONVS)}

                # M3：强制重渲染不得清空对话坞
                page.evaluate("()=>{window.oaBoot();}")
                page.wait_for_timeout(300)
                m3 = page.evaluate("()=>[...document.querySelectorAll('#oaDockList .bub')].map(b=>b.innerText.trim())")

                page.screenshot(path=str(REPO / ("logs/proof" if (REPO / "logs/proof").exists() else "logs") / ("oa_project_layout_%d.png" % vh)))
                page.close()
                return after_first, after_clear, m3

            for vh in (844, 640):
                print("\n[视口 390x%d]" % vh)
                a, b, m3 = probe(vh)
                chk("L1 ★机器人水平居中（|机器人中心-容器中心|≤2px，%s）" % vh,
                    a["robot"] and abs(a["robot"]["cx"] - a["stage"]["cx"]) <= 2,
                    "robot.cx=%.1f stage.cx=%.1f" % (a["robot"]["cx"], a["stage"]["cx"]))
                ratio = a["robot"]["h"] / a["vh"]
                chk("L2 机器人紧凑（高度占视口 ≤18%%，%s）" % vh, ratio <= 0.18,
                    "%.1f%% (h=%.0f vh=%d)" % (ratio * 100, a["robot"]["h"], a["vh"]))
                chk("L3 ★回答区不再被压在下方（对话坞顶部 ≤260px，%s）" % vh,
                    a["dockTop"] is not None and a["dockTop"] <= 260,
                    "dockTop=%.0f" % (a["dockTop"] if a["dockTop"] is not None else -1))
                chk("M1 记忆：进入项目后坞里仍在渲染历史消息（3 条都在，%s）" % vh,
                    _history_kept(a), "bubCount=%d" % a["bubCount"])
                chk("M2 ★记忆：进入同一项目复用会话（新建次数不增，%s）" % vh,
                    a["posted"] == 1 and a["convId"] == 555,
                    "posted=%d convId=%s" % (a["posted"], a["convId"]))
                chk("M2b ★负向对照：清掉复用记忆后再进入**确实**会新建（证明 M2 非恒真，%s）" % vh,
                    b["posted"] == 2, "posted=%d" % b["posted"])
                chk("M3 记忆：强制重渲染不清空对话坞（3 条历史仍在，%s）" % vh,
                    _history_kept({"stateTexts": m3}) and len(m3) >= 3, "bubCount=%d" % len(m3))

            browser.close()
    finally:
        httpd.shutdown()

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


def _route(route):
    url = route.request.url
    body = {"code": 0, "message": "ok", "data": []}
    if "/v1/conversations" in url and route.request.method == "POST":
        POSTED_CONVS.append(url)
        body["data"] = {"id": 555, "title": "项目 · 某某区发展和改革局数据治理项目"}
    elif url.rstrip("/").endswith("/messages"):
        body["data"] = list(HISTORY)
    elif "/v1/pm/projects/7/workers" in url:
        body["data"] = {"items": []}
    elif "/v1/pm/projects/7" in url:
        body["data"] = {"id": 7, "name": "某某区发展和改革局数据治理项目",
                        "projectType": "BIZ", "status": "ACTIVE"}
    elif "/v1/workers" in url:
        body["data"] = []
    route.fulfill(status=200, content_type="application/json", body=_json(body))


def _json(o):
    import json
    return json.dumps(o, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
