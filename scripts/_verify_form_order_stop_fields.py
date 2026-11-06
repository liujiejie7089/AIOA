# -*- coding: utf-8 -*-
"""表单先于换人 / 填表无法停止 / 内部字段外露 —— 端到端验收（2026-11-06，docs/83）

用户诉求（原话）：
  「还没转到专业数字人，表单就已经出来了，应该要先进行专业数字人，
    还有填写表单时，无法停止，同时，内部字段不能展示给用户」

三条分别验：
  S 顺序：当前不是对口数字人时，need_form **不挂卡**；先换人、再用同一句话自动重发；
          重发后（此时已在对口数字人上）才挂卡。改绑结果**回库核**。
  T 停止：表单挂起中点「停止生成」→ 卡片收起、S.busy 释放（输入栏可用）、并向服务端发 cancel
          （表单卡是 await 住的，旧实现会让 while 出不来 ⇒ S.busy 永久为 true）。
  F 字段：核对面板只说人话，不出现「假种 / 请假天数 / 证明材料 —」这类内部字段；
          纯函数 formSummaryHtml 同口径（不经 UI 也能验）。

前置：后端 :8080（H5 在 /aios/h5/）；agent 不必在线（SSE 用桩，字段定义取真实 /v1/forms 接口）。
用法：python scripts/_verify_form_order_stop_fields.py
"""

try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pathlib
import re
import subprocess
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

WRONG_ID, WRONG_NAME = 1314, "文档管理数字人"   # 起手：一个**不办请假**的数字人
RIGHT_ID, RIGHT_NAME = 523, "请假助手"          # 对口：worker_type=LEAVE_APPROVER
FORM_CODE = "leave_request"
QUESTION = "我要请假"

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def sql(q):
    return subprocess.run([MYSQL, "-uroot", "aios", "-e", q],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def worker_id_of(conv_id):
    r = sql(f"SELECT worker_id FROM chat_conversation WHERE id={int(conv_id)};")
    lines = [l for l in (r.stdout or "").strip().splitlines() if l.strip()]
    try:
        return int(lines[1].split("\t")[0])
    except Exception:
        return None


def login():
    d = httpx.post(f"{API}/auth/login", json={"username": USER, "password": PWD},
                   timeout=30, trust_env=False).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"]


def main():
    token, user = login()
    h = {"Authorization": "Bearer " + token}

    # 表单字段取**真实接口**（与生产渲染同源），不在脚本里手搓 schema
    fd = httpx.get(f"{API}/forms/{FORM_CODE}", headers=h, timeout=30, trust_env=False).json()
    form = fd.get("data") or {}
    if not form.get("fields"):
        raise SystemExit("取不到 leave_request 的字段定义")
    print(f"      · 表单 {FORM_CODE} 字段：{[f.get('name') for f in form['fields']]}")

    need_form = {"form_code": FORM_CODE, "version": form.get("version"),
                 "title": form.get("name") or "请假申请", "submit_label": "提交审批申请",
                 "reason": "先填业务表单", "fields": form.get("fields") or [],
                 "origin": {"kind": "worker", "worker_id": RIGHT_ID, "worker_name": RIGHT_NAME}}

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="zh-CN")
        ctx.add_init_script(
            "localStorage.setItem('aios_session', %s);localStorage.setItem('aios_mode','oa');"
            % json.dumps(json.dumps({"token": token, "user": user}, ensure_ascii=False)))
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))

        runs = {"n": 0}
        run_bodies = []
        cancels = []

        def on_create_run(route, request):
            runs["n"] += 1
            rid = "e2e-form-%d" % runs["n"]
            try:
                body = json.loads(request.post_data or "{}")
            except Exception:
                body = {}
            body["__url"] = request.url
            body["__rid"] = rid
            run_bodies.append(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"code": 0, "message": "ok", "data": {"id": rid}}))

        def on_events(route, request):
            sse = ("event: message.delta\ndata: %s\n\n"
                   "event: need_form\ndata: %s\n\n"
                   % ("我这边先把请假单发给你。", json.dumps(need_form, ensure_ascii=False)))
            route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body=sse)

        pg.route("**/v1/conversations/*/runs", on_create_run)
        pg.route("**/v1/runs/*/events", on_events)

        def on_req(req):
            if req.method == "POST" and re.search(r"/v1/runs/[^/]+/cancel$", req.url):
                cancels.append(req.url)
        pg.on("request", on_req)

        def wait_until(fn, timeout=10.0, step=0.15):
            # 必须用 pg.wait_for_timeout：time.sleep 会堵住 Playwright 的事件分发（pitfalls 97）
            t0 = time.time()
            while time.time() - t0 < timeout:
                if fn():
                    return True
                pg.wait_for_timeout(int(step * 1000))
            return False

        pg.goto(H5, wait_until="domcontentloaded")
        pg.wait_for_selector("#oaRoot", timeout=30000)
        pg.wait_for_timeout(2000)

        # ---- 起手：切到一个**不办请假**的数字人 -----------------------------
        pg.evaluate("() => oaGo('workers')")
        pg.wait_for_selector('#v-workers.on #oaWorkersList .lrow[data-worker="%d"]' % WRONG_ID, timeout=15000)
        pg.click('#oaWorkersList .lrow[data-worker="%d"]' % WRONG_ID)
        pg.wait_for_timeout(800)
        who0 = pg.evaluate("() => { const e=document.querySelector('.oa-who'); return e?e.textContent:null; }")
        rec("S0 起手在「不办请假」的数字人上（这是问题现场的前提）",
            bool(who0) and WRONG_NAME in who0, f"含「{WRONG_NAME}」", who0)

        pg.fill("#oaInput", QUESTION)
        pg.wait_for_timeout(200)
        # 记录「表单出现的那一刻，当前对话对象是谁」——这才是「先转人还是先出表」的直接证据。
        # 只按时间点采样会被自动重发的速度左右（第一轮与第二轮相隔可能不到 1 秒）。
        pg.evaluate("""() => {
            window.__formLog = [];
            const host = document.getElementById('oaDockList') || document.body;
            const grab = () => {
              document.querySelectorAll('.leave-form').forEach(el => {
                if(el.__seen) return;
                el.__seen = true;
                const w = document.querySelector('.oa-who');
                window.__formLog.push((w && w.textContent) || '');
              });
            };
            grab();
            new MutationObserver(grab).observe(host, {childList:true, subtree:true});
        }""")
        pg.click("#oaSendBtn", force=True)

        # ---- S 段：顺序 ------------------------------------------------------
        # ① 表单出现时，当前必须已经是对口数字人（空串=当时还没有 .oa-who，同样算错）
        ok_form = wait_until(lambda: pg.evaluate("() => (window.__formLog||[]).length > 0"), 18)
        form_log = pg.evaluate("() => window.__formLog || []")
        rec("S1 表单出现的那一刻，当前对话对象已是对口数字人（不是先出表后换人）",
            ok_form and all(RIGHT_NAME in w for w in form_log),
            f"每次出现时 .oa-who 都含「{RIGHT_NAME}」", form_log)

        # ② 发生了换人
        ok_switch = wait_until(lambda: (lambda t: bool(t) and RIGHT_NAME in t)(
            pg.evaluate("() => { const e=document.querySelector('.oa-who'); return e?e.textContent:null; }")), 12)
        who1 = pg.evaluate("() => { const e=document.querySelector('.oa-who'); return e?e.textContent:null; }")
        rec("S2 先转到对口数字人（顶部「与「X」对话中」已变）",
            ok_switch and bool(who1) and RIGHT_NAME in who1, f"含「{RIGHT_NAME}」", who1)

        # ③ 同一句话被自动重发（不要求用户重打）
        ok_resend = wait_until(lambda: len(run_bodies) >= 2, 15)
        last = run_bodies[-1] if run_bodies else {}
        new_conv = None
        m = re.search(r"/v1/conversations/(\d+)/runs", last.get("__url") or "")
        if m:
            new_conv = int(m.group(1))
        rec("S3 换人后用同一句话自动重发（用户不用重打）",
            ok_resend and last.get("text") == QUESTION, f"第二次 createRun text={QUESTION!r}",
            {"n": len(run_bodies), "text": last.get("text"), "conv": new_conv})

        # ④ 回库核：重发所用会话确实绑在对口数字人上（不是只改了界面）
        db_w = worker_id_of(new_conv) if new_conv else None
        rec("S4 重发所用会话在库里绑的是对口数字人（不是只换了称呼）",
            db_w == RIGHT_ID, f"worker_id={RIGHT_ID}", db_w)

        # ⑤ 重发后（已在对口人上）表单才挂出来
        try:
            pg.wait_for_selector(".leave-form", timeout=15000)
            mounted = True
        except Exception:
            mounted = False
        rec("S5 转对人之后表单才出现（顺序正确）", mounted, ".leave-form 存在", mounted)
        pg.screenshot(path=str(OUT / "50-form-after-handoff.png"))

        # ⑥ 表单标签是人话（不是 schema 里的内部叫法）
        labels = pg.evaluate("""() => Array.from(document.querySelectorAll('.leave-form .lf-row > label'))
            .map(e => (e.textContent||'').replace('*','').trim())""")
        rec("S6 表单字段名是人话（「假种」显示为「请假类型」）",
            bool(labels) and "请假类型" in labels and "假种" not in labels,
            "含「请假类型」且无「假种」", labels)

        # ⑦ 同一时刻只能有一张请假卡：经典 leaveFormHtml(#leaveForm) 与后端 need_form 卡
        #    (.leave-form[data-code]) 并存时，用户会看到两张互相矛盾的请假单（2026-11-06 现场）。
        cards = pg.evaluate("""() => Array.from(document.querySelectorAll('.leave-form')).map(c => ({
            id: c.id || '', code: c.getAttribute('data-code') || '',
            btn: (c.querySelector('[data-form-submit]')||{}).textContent || ''}))""")
        rec("S7 同一时刻只有一张请假卡（经典卡与后端卡不并存）",
            len(cards) == 1 and cards[0].get("code") == FORM_CODE,
            f"仅 1 张且 data-code={FORM_CODE}", cards)

        # ---- F 段：内部字段不外露 ------------------------------------------
        # 纯函数级（不经 UI 也能验，防「界面碰巧没显示」）
        pure = pg.evaluate("""() => formSummaryHtml(
            {form_code:'leave_request', fields:[
              {name:'leave_type',label:'假种',type:'select',options:[{value:'ANNUAL',label:'年休假'}]},
              {name:'start_date',label:'开始日期',type:'date'},
              {name:'end_date',label:'结束日期',type:'date'},
              {name:'days',label:'请假天数',type:'number'},
              {name:'reason',label:'请假事由',type:'textarea'},
              {name:'proof',label:'证明材料',type:'file'}],
             required:['leave_type','start_date','end_date','days','reason']},
            {leave_type:'ANNUAL', start_date:'2026-11-29', end_date:'2026-11-29',
             days:'4', reason:'522', proof:[]})""")
        rec("F1 核对面板不含内部字段（假种 / 请假天数 / 证明材料 / 内部键名）",
            not any(k in pure for k in ["假种", "请假天数", "证明材料", "leave_type", "start_date", "days"]),
            "四个内部词一个都不出现",
            [k for k in ["假种", "请假天数", "证明材料", "leave_type", "start_date", "days"] if k in pure])
        rec("F2 保留用户填过的内容（请假类型/开始日期/请假事由/事由值）",
            all(k in pure for k in ["请假类型", "年休假", "开始日期", "请假事由", "522"]),
            "人话标签与值都在", [k for k in ["请假类型", "年休假", "开始日期", "请假事由", "522"] if k not in pure])

        # 真实 UI：填必填 → 点提交 → 看核对面板（**不**点确认，避免产生业务数据）
        pg.evaluate("""() => {
            const card = document.querySelector('.leave-form');
            card.querySelectorAll('[data-field]').forEach(c => {
              const type = c.getAttribute('data-type');
              if(c.getAttribute('data-required') !== '1') return;
              if(type === 'select'){ if(c.options.length > 1) c.selectedIndex = 1; }
              else if(type === 'number'){ c.value = '1'; }
              else if(type === 'date'){ c.value = '2026-11-30'; }
              else { c.value = '家里有事'; }
              c.dispatchEvent(new Event('input', {bubbles:true}));
              c.dispatchEvent(new Event('change', {bubbles:true}));
            });
        }""")
        pg.click(".leave-form [data-form-submit]")
        pg.wait_for_timeout(600)
        panel = pg.evaluate("() => { const e=document.querySelector('.leave-form .lf-confirm');"
                            " return e?e.textContent.replace(/\\s+/g,' ').trim():null; }")
        rec("F3 真实核对面板：不出现「假种 / 请假天数 / 证明材料」",
            bool(panel) and not any(k in panel for k in ["假种", "请假天数", "证明材料"]),
            "无内部字段", panel)
        rec("F4 标题改为用户语言「确认提交以下内容」",
            bool(panel) and "确认提交以下内容" in panel, "含「确认提交以下内容」", panel[:60])
        pg.screenshot(path=str(OUT / "51-form-confirm-human.png"))

        # ---- T 段：填表时能停止 --------------------------------------------
        rec("T0 表单挂起时 S.busy 为 true（确有「正在进行的一轮」可停止）",
            pg.evaluate("() => oaState.busy === true"), "busy == true",
            pg.evaluate("() => oaState.busy"))
        n_before = len(cancels)
        try:
            pg.click(".bub-stop", force=True, timeout=5000)   # 与用户点「停止生成」同一条路径
            clicked = True
        except Exception:
            clicked = False
        ok_clear = wait_until(lambda: pg.evaluate("() => document.querySelectorAll('.leave-form').length") == 0, 8)
        busy_after = pg.evaluate("() => oaState.busy")
        # 输入栏「可用」的判据不看发送键显隐：发送键本来就随输入框有无文字显隐（空值时是话筒），
        # 那是设计而非故障。真正的判据是：停止按钮已摘掉、输入框未被禁用。
        stop_gone = pg.evaluate("() => document.querySelectorAll('.bub-stop').length === 0")
        input_ok = pg.evaluate("() => { const i=document.getElementById('oaInput');"
                               " return !!i && !i.disabled && !i.readOnly; }")
        rec("T1 点「停止生成」→ 表单卡收起、S.busy 释放、输入框恢复可用",
            clicked and ok_clear and busy_after is False and stop_gone and input_ok,
            "卡片消失 + busy=false + 停止键已摘 + 输入框可用",
            {"clicked": clicked, "cleared": ok_clear, "busy": busy_after,
             "stopGone": stop_gone, "inputUsable": input_ok})
        rec("T2 停止同时向服务端取消这一轮（不再把 run 挂在 WAITING_INPUT）",
            len(cancels) > n_before, "发出 POST /v1/runs/{id}/cancel",
            {"before": n_before, "after": len(cancels), "last": cancels[-1] if cancels else None})
        pg.screenshot(path=str(OUT / "52-form-stopped.png"))

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
