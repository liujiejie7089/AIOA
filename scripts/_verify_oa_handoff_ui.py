# -*- coding: utf-8 -*-
"""用户端 H5 消费新 SSE 帧 `worker.handoff`（会话内自动切换数字人）的**浏览器级**哨兵。

为什么必须有这一条，而不是只 grep 产物：
  · grep 只能证明产物里**有** `worker.handoff` 分支与 `oaApplyHandoff` 函数；
  · 它证明不了「H5 真的在收到该帧时切了当前数字人、落了提示气泡、且**没换会话**」。
  本脚本用真实 Chromium 载入**重建后的产物** `user-client/index.html`，用 `page.route`
  把 `/api/v1/**` 打桩成可控 SSE 流（无需后端、无需登录态），直接驱动真实 `oaSend()` 路径。

判据（每条都回到事实源头，不读界面自己的副本）：
  P1 ★ handoff 后对话坞里出现「自动转交」提示气泡（`.oa-handoff-note` 存在）。
  P2 ★ 该气泡文案含「报销数字人」与「不用重说」（证明切到了目标数字人 + 提示不用重述）。
  P3 回答气泡存在（坞内出现 message.delta 的回答文本「已按差旅标准为你登记」）。
  P4 ★核心：handoff 前后 `window.oaState.convId` 不变（先置一个哨兵值，handoff 不得改它）。
      这证伪「换人=换会话」——本需求就是要「不换会话、上下文不丢」。
  P5 当前数字人已切到目标：`S.worker.id===456` 且 `S.worker.name==='报销数字人'`
      （且原对象字段被保留，不丢 undefined）。
  P6 顶部 `.oa-who` 已刷新为「报销数字人」（DOM 里唯一渲染 S.worker.name 的点）。
  N1 ★负向对照：同一条流**不发** handoff 帧时，`.oa-handoff-note` 不出现
      （证明 P1/P2 的断言不是恒真）。
  N2 负向对照：不发 handoff 时坞内不含「不用重说」。
  N3 负向对照下回答气泡仍正常出现（排除「只是整条流失败才没气泡」的干扰）。
  N4 负向对照下 convId 仍不变（基线）。

★ 关于 convId 判据的口径：本脚本在每次发送前先把 `S.convId` 设成哨兵串
  `'KEEP-THIS-CONV'`。`oaEnsureConv()` 在 `S.convId` 已有时直接返回它（不会 POST 新建），
  于是「handoff 是否偷偷换会话」被收束成一句可复算的等式：`S.convId` 在流结束后仍等于该哨兵串。
  若 `oaApplyHandoff` 误调了换会话逻辑，等式即破。

前置：无需后端、无需登录态（用本地静态服务 + page.route 打桩）。
用法：python scripts/_verify_oa_handoff_ui.py
"""
import functools
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
INDEX = CLIENT / "index.html"

PASS, FAIL = [], []
CONV_SENTINEL = "KEEP-THIS-CONV"


def chromium_exe():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not root.exists():
        return None
    for pat in ("chromium-*/chrome-win64/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
        hits = sorted(root.glob(pat))
        if hits:
            return str(hits[-1])
    return None


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + str(detail)[:400]))


def sse(*frames):
    return "\n\n".join(frames) + "\n\n"


def frame(ev, data):
    return "event: %s\ndata: %s" % (ev, json.dumps(data, ensure_ascii=False))


# 正向：先 handoff（to_worker_name=报销数字人），再正常回答
POS_BODY = sse(
    frame("worker.handoff", {
        "from_worker_id": 123, "from_worker_name": "请假数字人",
        "to_worker_id": 456, "to_worker_name": "报销数字人",
        "task_name": "费用报销", "question": "我要报销差旅费"}),
    frame("run.started", {"model": "gpt"}),
    frame("message.delta", {"text": "已按差旅标准为你登记"}),
    frame("message.completed", {"content": "已按差旅标准为你登记",
                                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}),
    frame("run.completed", {"status": "SUCCEEDED"}),
)

# 负向：同一形态但不发 handoff 帧
NEG_BODY = sse(
    frame("run.started", {"model": "gpt"}),
    frame("message.delta", {"text": "已按差旅标准为你登记"}),
    frame("message.completed", {"content": "已按差旅标准为你登记",
                                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}),
    frame("run.completed", {"status": "SUCCEEDED"}),
)


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(CLIENT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main():
    if not INDEX.exists():
        print("[FAIL] 产物不存在：%s" % INDEX)
        return 1

    # ---- 静态判据：重建后的产物确实含本轮改动（防止「改的不是构建输入」）----
    html = INDEX.read_text(encoding="utf-8")
    chk("S0 产物含 worker.handoff 事件分支", "ev.event === 'worker.handoff'" in html, "index.html")
    chk("S1 产物含 oaApplyHandoff 函数", "function oaApplyHandoff" in html, "index.html")
    chk("S2 产物含 handoff 气泡标记 oa-handoff-note", "oa-handoff-note" in html, "index.html")

    httpd, port = serve()
    base = "http://127.0.0.1:%d" % port
    exe = chromium_exe()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.on("pageerror", lambda e: print("  [pageerror] " + str(e)))

            # 单一 catch-all 路由：按 URL 分发
            state = {"sse": POS_BODY}

            def _route(route):
                url = route.request.url
                method = route.request.method
                if url.rstrip("/").endswith("/runs") and method == "POST":
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"id": "run-fixed"}))
                    return
                if "/api/v1/runs/" in url and url.rstrip("/").endswith("/events") and method == "GET":
                    route.fulfill(status=200, content_type="text/event-stream", body=state["sse"])
                    return
                if url.rstrip("/").endswith("/conversations") and method == "POST":
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"id": "conv-fixed"}))
                    return
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"code": 0, "message": "ok", "data": []}))

            page.route("**/api/v1/**", _route)

            page.goto(base + "/index.html", wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            page.evaluate("() => { document.body.classList.add('auth'); window.oaState.mode='oa'; window.oaBoot(); }")
            page.wait_for_timeout(400)

            def setup(worker_id, worker_name, conv_id):
                page.evaluate("""(args) => {
                  window.oaState.worker = {id: args.wid, name: args.wname, roleName: 'x', scheduleTime: ''};
                  window.oaState.convId = args.cid;
                  window.oaState.busy = false;
                  window.oaState.pendingFiles = [];
                  var d = document.getElementById('oaDockList');
                  if (d) d.innerHTML = '';
                }""", {"wid": worker_id, "wname": worker_name, "cid": conv_id})

            def send_q(q):
                page.fill("#oaInput", q)
                page.evaluate("async () => { await window.oaSend(); }")
                page.wait_for_timeout(200)

            # ============================== 正向：带 handoff ==============================
            print("\n=== 正向场景：SSE 含 worker.handoff ===")
            state["sse"] = POS_BODY
            setup(123, "请假数字人", CONV_SENTINEL)
            # 发问前先把初始 convId 记下来（即哨兵串），handoff 不得改它
            before = page.evaluate("() => window.oaState.convId")
            send_q("我要报销差旅费")

            note = page.locator(".oa-handoff-note")
            note_n = note.count()
            note_txt = note.first.inner_text() if note_n else ""
            dock = page.eval_on_selector("#oaDockList", "el => el.innerText")
            who = page.eval_on_selector(".oa-who", "el => el.innerText") if page.locator(".oa-who").count() else ""
            after = page.evaluate("() => window.oaState.convId")
            wid = page.evaluate("() => window.oaState.worker ? window.oaState.worker.id : null")
            wname = page.evaluate("() => window.oaState.worker ? window.oaState.worker.name : null")
            # 原对象字段是否保留（roleName 仍在，证明 Object.assign 没丢字段）
            role = page.evaluate("() => window.oaState.worker ? (window.oaState.worker.roleName || null) : null")

            chk("P1 ★handoff 后出现「自动转交」提示气泡（.oa-handoff-note）",
                note_n >= 1, "count=%d" % note_n)
            chk("P2 ★提示气泡含目标数字人「报销数字人」与「不用重说」",
                ("报销数字人" in note_txt) and ("不用重说" in note_txt), note_txt[:200])
            chk("P3 回答气泡存在（坞内出现「已按差旅标准为你登记」）",
                "已按差旅标准为你登记" in dock, dock[:200])
            chk("P4 ★核心：handoff 前后 convId 不变（%s → %s，应为哨兵串）" % (before, after),
                before == CONV_SENTINEL and after == CONV_SENTINEL,
                "before=%s after=%s" % (before, after))
            chk("P5 当前数字人已切到目标（id=456 / name=报销数字人）",
                Number_eq(wid, 456) and wname == "报销数字人", "id=%s name=%s" % (wid, wname))
            chk("P5b 原 worker 对象字段保留（roleName 未丢为 undefined）",
                role == "x", "roleName=%s" % role)
            chk("P6 顶部 .oa-who 已刷新为「报销数字人」",
                "报销数字人" in who, who)

            # ============================== 负向：不带 handoff ==============================
            print("\n=== 负向对照：SSE 不含 worker.handoff ===")
            state["sse"] = NEG_BODY
            setup(123, "请假数字人", CONV_SENTINEL)
            before_n = page.evaluate("() => window.oaState.convId")
            send_q("我要报销差旅费")

            note_n2 = page.locator(".oa-handoff-note").count()
            dock2 = page.eval_on_selector("#oaDockList", "el => el.innerText")
            after_n = page.evaluate("() => window.oaState.convId")

            chk("N1 ★负向对照：不发 handoff 时**不出现**提示气泡（.oa-handoff-note=0）",
                note_n2 == 0, "count=%d" % note_n2)
            chk("N2 负向对照：坞内不含「不用重说」", "不用重说" not in dock2, dock2[:200])
            chk("N3 负向对照下回答气泡仍正常出现", "已按差旅标准为你登记" in dock2, dock2[:200])
            chk("N4 负向对照下 convId 仍不变（基线）",
                before_n == CONV_SENTINEL and after_n == CONV_SENTINEL,
                "before=%s after=%s" % (before_n, after_n))

            browser.close()
    finally:
        httpd.shutdown()

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


def Number_eq(a, b):
    try:
        return float(a) == float(b)
    except Exception:
        return a == b


if __name__ == "__main__":
    sys.exit(main())
