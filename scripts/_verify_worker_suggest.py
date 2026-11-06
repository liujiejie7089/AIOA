# -*- coding: utf-8 -*-
"""「越界建议 ⇒ 一句话变成可点的跳转」端到端验收（九期，2026-11-06）

用户诉求（原话）：
  「如果当前数字人无法处理，那就提示跳到合适的数字人处理」

截图现场：请假助手读了《策划书.docx》，回「这属于策划书内容解读，超出我的请假办理职责范围；
请改问文档解读数字员工或项目负责人」——用户看到的只有一句话，**没有任何可点入口**。

本条链路分两段，分别用不同手段验（都不自证）：
  · 后端判定（读回答正文 → 该不该给卡、给谁）：RunServiceSuggestWorkerTest（11 例纯函数）
  · 前端契约（收到帧 → 渲染卡 → 点击真发请求 → 会话真改绑）：本脚本
SSE 用桩只伪造「这一轮回答 + 建议帧」，**handoff 请求、会话改绑、原问题重发全走真后端与真库**。

判据：
  A1 越界回答落定后出现 guide 卡，且文案点名目标数字人（文档管理数字人）
  A2 只推这一张，不再叠第二张关键词推荐卡
  A3 点「换他重答」→ 真发 POST /v1/conversations/{id}/handoff，body.workerId 正确
  A4 改绑落到库：chat_conversation.worker_id 从 523 变 1314（**回库核，不看界面**）
  A5 原问题被原样重发，且仍在**同一条会话**里（不新建会话，历史不丢）
  A6 顶栏/状态已切到新数字人
  B1 越界但点名的名字库里不存在（截图里的「文档解读数字员工」是模型编的）⇒ 给「去挑一位」卡
  B2 点「去看看」→ 进数字员工列表，且原问句暂存、选中数字人后自动填回输入框
  C1 全程无 JS 异常

前置：后端 :8080（H5 在 /aios/h5/）；agent 不必在线（SSE 用桩）。
用法：python scripts/_verify_worker_suggest.py
"""

try:  # GBK 控制台打印中文/符号会 UnicodeEncodeError
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pathlib
import subprocess
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
API = BASE + "/api/v1"
H5 = BASE + "/aios/h5/"
USER, PWD = "test", "test"
MYSQL = r"D:\dev\mysql\mysql-8.4.10-winx64\bin\mysql.exe"
OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "regression-2026-11-06"
OUT.mkdir(parents=True, exist_ok=True)

CUR_ID, CUR_NAME = 523, "请假助手"           # 当前数字人（worker_type=LEAVE_APPROVER，无能力行）
TGT_ID, TGT_NAME = 1314, "文档管理数字人"     # 目标：有 worker_capability(doc_upload) ⇒ 在候选里

QUESTION = "策划书里面说了什么"

# A 场景回答：越界 + 点名**库里真实存在**的数字人
ANSWER_HIT = ("知识库里找到了《策划书.docx》，我继续取它的正文。这属于策划书内容解读，"
              "超出我的请假办理职责范围；请改问" + TGT_NAME + "。")
# B 场景回答：截图原文（点名的「文档解读数字员工」全租户都不存在，是模型编的）
ANSWER_MISS = ("知识库里确实有《策划书.docx》（自贡彩灯数字文旅方向）。这属于策划书内容解读，"
               "超出我的请假办理职责范围；请改问文档解读数字员工或项目负责人。")

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def sql(q):
    return subprocess.run([MYSQL, "-uroot", "aios", "-e", q],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def worker_id_of(conv_id):
    """回库取会话绑定的数字人 —— 唯一事实源，不用界面文字自证。"""
    r = sql(f"SELECT worker_id FROM chat_conversation WHERE id={int(conv_id)};")
    lines = [l for l in (r.stdout or "").strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    try:
        return int(lines[1].split("\t")[0])
    except Exception:
        return None


def login():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"]


def main():
    token, user = login()

    # ---------------------------------------------------------------- P 前置：两位数字人必须在位
    ws = httpx.get(f"{API}/workers", headers={"Authorization": "Bearer " + token},
                   timeout=30, trust_env=False).json().get("data") or []
    by_id = {int(w["id"]): w for w in ws if w.get("id")}
    rec("P1 前置：库里同时有「请假助手」与「文档管理数字人」",
        CUR_ID in by_id and TGT_ID in by_id,
        f"存在 {CUR_ID} 与 {TGT_ID}",
        {"cur": by_id.get(CUR_ID, {}).get("name"), "tgt": by_id.get(TGT_ID, {}).get("name")})
    if CUR_ID not in by_id or TGT_ID not in by_id:
        raise SystemExit("前置不满足：所需数字人不在本租户")

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="zh-CN")
        ctx.add_init_script(
            "localStorage.setItem('aios_session', %s);localStorage.setItem('aios_mode','oa');"
            % json.dumps(json.dumps({"token": token, "user": user}, ensure_ascii=False)))
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))

        # ---- 桩：只伪造「这一轮回答 + 建议帧」，其余全真 -------------------
        stub = {"answer": ANSWER_HIT, "suggest": {"out_of_scope": True, "to_worker_id": TGT_ID,
                                                  "to_worker_name": TGT_NAME, "task_name": "文档上传"}}
        runs = {"n": 0, "created": []}
        run_bodies = []      # 每次 createRun 的 body（含 text），用于判「原问题重发」

        def on_create_run(route, request):
            runs["n"] += 1
            rid = "e2e-suggest-%d" % runs["n"]
            try:
                body = json.loads(request.post_data or "{}")
            except Exception:
                body = {}
            body["__url"] = request.url
            runs["created"].append(rid)
            run_bodies.append(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"code": 0, "message": "ok", "data": {"id": rid}}))

        def on_events(route, request):
            sse = ("event: message.delta\ndata: %s\n\n"
                   "event: suggest.worker\ndata: %s\n\n"
                   'event: run.completed\ndata: {"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
                   % (stub["answer"], json.dumps(stub["suggest"], ensure_ascii=False)))
            route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body=sse)

        pg.route("**/v1/conversations/*/runs", on_create_run)
        pg.route("**/v1/runs/*/events", on_events)

        handoffs = []
        all_posts = []

        def on_req(req):
            if "/api/v1/" in req.url:
                all_posts.append(req.method + " " + req.url.split("/api/v1")[-1])
            if req.method == "POST" and req.url.endswith("/handoff"):
                handoffs.append({"url": req.url, "body": req.post_data})

        pg.on("request", on_req)

        def wait_until(fn, timeout=8.0, step=0.15):
            """轮询等待。

            ★必须用 pg.wait_for_timeout 而不是 time.sleep：Py 侧 time.sleep 会卡住
            Playwright 的事件分发线程，`pg.route` 的桩回调与 request 监听都排在队列里
            执行不到 —— 表现为「浏览器明明发了请求，run_bodies 却一直是 1」，
            靠后一个 pg.evaluate 才把队列冲开（2026-11-06 实测，差点误判成重发没触发）。
            """
            t0 = time.time()
            while time.time() - t0 < timeout:
                if fn():
                    return True
                pg.wait_for_timeout(int(step * 1000))
            return False

        pg.goto(H5, wait_until="domcontentloaded")
        pg.wait_for_selector("#oaRoot", timeout=30000)
        pg.wait_for_timeout(2000)

        # ---- 选中「请假助手」（与用户点卡片同一条路径：oaPickWorker） -------
        pg.evaluate("() => oaGo('workers')")
        pg.wait_for_selector('#v-workers.on #oaWorkersList .lrow[data-worker="%d"]' % CUR_ID, timeout=15000)
        pg.click('#oaWorkersList .lrow[data-worker="%d"]' % CUR_ID)
        pg.wait_for_timeout(800)
        cur_ui = pg.evaluate("() => { const e = document.querySelector('.oa-who');"
                             " return e ? e.textContent : null; }")
        rec("P2 选中当前数字人（顶部「与「X」对话中」随之一致）",
            bool(cur_ui) and CUR_NAME in cur_ui, f"含「{CUR_NAME}」", cur_ui)

        # ---- A 段：越界 + 点名真人 ⇒ 可点跳转 ------------------------------
        pg.fill("#oaInput", QUESTION)
        pg.wait_for_timeout(200)
        pg.click("#oaSendBtn", force=True)
        try:
            pg.wait_for_selector(".guide", timeout=15000)
            got = True
        except Exception:
            got = False
        txt = pg.evaluate("() => { const g = document.querySelector('.guide'); return g ? g.textContent : null; }")
        rec("A1 越界回答落定后出现 guide 卡，且点名目标数字人",
            got and bool(txt) and TGT_NAME in txt,
            f"卡片含「{TGT_NAME}」", (txt or "")[:120])
        pg.screenshot(path=str(OUT / "40-suggest-handoff.png"))

        n_guide = pg.evaluate("() => document.querySelectorAll('.guide').length")
        rec("A2 只推这一张（不再叠第二张关键词推荐卡）", n_guide == 1, "guide 数 == 1", n_guide)

        # 会话 id 从**真实请求 URL** 取（前端状态对象在模块作用域里，不对外暴露，
        # 也不该为了测试去改生产代码；URL 是这条链路上最硬的事实来源）
        import re
        conv_id = None
        if run_bodies:
            m = re.search(r"/v1/conversations/(\d+)/runs", run_bodies[0].get("__url") or "")
            conv_id = int(m.group(1)) if m else None
        rec("A2b 会话已建立（后续改绑要有会话可改）", bool(conv_id), "convId 非空", conv_id)
        before_worker = worker_id_of(conv_id) if conv_id else None
        rec("A2c 改绑前库里就是当前数字人（改动能归因）",
            before_worker == CUR_ID, f"worker_id={CUR_ID}", before_worker)

        # 点「换他重答」：真发 handoff，且原问题重发
        pg.click(".guide [data-re]")
        ok = wait_until(lambda: len(handoffs) > 0, timeout=10)
        h = handoffs[-1] if handoffs else {}
        try:
            hb = json.loads(h.get("body") or "{}")
        except Exception:
            hb = {}
        rec("A3 点「换他重答」→ 真发 POST /v1/conversations/{id}/handoff，body.workerId 正确",
            ok and ("/v1/conversations/%s/handoff" % conv_id) in (h.get("url") or "")
            and int(hb.get("workerId") or 0) == TGT_ID,
            f"POST …/{conv_id}/handoff body.workerId={TGT_ID}",
            {"url": h.get("url"), "body": hb})

        # 回库核：会话真的改绑了（不新建会话）
        wait_until(lambda: worker_id_of(conv_id) == TGT_ID, timeout=6)
        after_worker = worker_id_of(conv_id)
        rec("A4 改绑落到库：chat_conversation.worker_id 变成目标数字人",
            after_worker == TGT_ID, f"worker_id={TGT_ID}", after_worker)
        n_same = sql(f"SELECT COUNT(*) AS n FROM chat_conversation WHERE id={int(conv_id)};")
        cnt = (n_same.stdout or "").strip().splitlines()[-1] if (n_same.stdout or "").strip() else ""
        rec("A4b 没有新建会话（历史不丢）", cnt.strip() == "1", "该 id 仍只有 1 条", cnt)

        # 原问题重发，且仍落在同一条会话
        ok2 = wait_until(lambda: len(run_bodies) >= 2, timeout=10)
        last_run = run_bodies[-1] if run_bodies else {}
        st = pg.evaluate("() => ({busy: oaState.busy, q: oaState.lastQuery, conv: oaState.convId,"
                         " w: oaState.worker && oaState.worker.name,"
                         " val: (document.getElementById('oaInput')||{}).value})")
        rec("A5 原问题被原样重发，且仍在同一条会话（不换会话、不重打）",
            ok2 and last_run.get("text") == QUESTION
            and ("/v1/conversations/%s/runs" % conv_id) in (last_run.get("__url") or ""),
            f"POST …/{conv_id}/runs text={QUESTION!r}",
            {"n": len(run_bodies), "text": last_run.get("text"), "url": last_run.get("__url"),
             "state": st, "flow": all_posts[-6:]})

        ui2 = pg.evaluate("() => { const e = document.querySelector('.oa-who');"
                          " return e ? e.textContent : null; }")
        rec("A6 顶栏「与「X」对话中」已切到新数字人",
            bool(ui2) and TGT_NAME in ui2, f"含「{TGT_NAME}」", ui2)
        pg.screenshot(path=str(OUT / "41-suggest-switched.png"))

        # ---- B 段：截图原文（点名的人库里不存在）⇒ 挑人卡 ------------------
        # 先开一个新对话：否则 .guide 会命中 A 段那张老卡，「点击」也会点到它。
        pg.evaluate("() => { const b = document.getElementById('odNewChat'); if(b) b.click(); }")
        pg.wait_for_timeout(800)
        n_guide0 = pg.evaluate("() => document.querySelectorAll('.guide').length")
        rec("B0 新对话后旧卡已清空（B 段判据针对的是本轮新卡）", n_guide0 == 0, "guide 数 == 0", n_guide0)

        pg.evaluate("() => oaGo('workers')")
        pg.wait_for_selector('#v-workers.on #oaWorkersList .lrow[data-worker="%d"]' % CUR_ID, timeout=15000)
        pg.click('#oaWorkersList .lrow[data-worker="%d"]' % CUR_ID)   # 换回请假助手（会重置会话）
        pg.wait_for_timeout(800)
        stub["answer"] = ANSWER_MISS
        stub["suggest"] = {"out_of_scope": True}     # 越界，但没有可用目标

        pg.fill("#oaInput", QUESTION)
        pg.wait_for_timeout(200)
        pg.click("#oaSendBtn", force=True)
        try:
            pg.wait_for_selector(".guide", timeout=15000)
            got_b = True
        except Exception:
            got_b = False
        txt_b = pg.evaluate("() => { const g = document.querySelector('.guide'); return g ? g.textContent : null; }")
        rec("B1 越界但点名的数字人在库里不存在 ⇒ 给「去挑一位」卡（不再只剩一句话）",
            got_b and bool(txt_b) and "去挑一位能办的数字人" in txt_b,
            "卡片含「去挑一位能办的数字人」", (txt_b or "")[:120])
        pg.screenshot(path=str(OUT / "42-suggest-pick.png"))

        # 点「去看看」→ 进数字员工列表
        pg.click(".guide [data-re]")
        pg.wait_for_timeout(800)
        on_workers = pg.evaluate("() => { const v = document.getElementById('v-workers');"
                                " return !!v && v.classList.contains('on'); }")
        rec("B2 点「去看看」→ 进入数字员工列表（有地方可点，不是死路）", on_workers,
            "#v-workers.on", on_workers)

        # 选一位 → 原问句自动填回输入框
        pg.click('#oaWorkersList .lrow[data-worker="%d"]' % TGT_ID)
        pg.wait_for_timeout(900)
        filled = pg.evaluate("() => { const i = document.getElementById('oaInput'); return i ? i.value : null; }")
        rec("B3 选完数字人后原问句自动填回输入框（不用重打）",
            (filled or "").strip() == QUESTION, repr(QUESTION), repr(filled))

        pg.screenshot(path=str(OUT / "43-suggest-picked.png"))

        # ---- C 段：全程无 JS 异常 ----------------------------------------
        rec("C1 全程无 JS 异常", len(errs) == 0, "0 个 pageerror", errs[:3])

        b.close()

    ok_n = sum(1 for _, o in results if o)
    print(f"\n===== {ok_n}/{len(results)} 通过 =====")
    if ok_n != len(results):
        for n, o in results:
            if not o:
                print("  FAILED:", n)
        sys.exit(1)


if __name__ == "__main__":
    main()
