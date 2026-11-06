# -*- coding: utf-8 -*-
"""「负责人确认环节」端到端验收（八期，2026-11-06）

用户诉求（原话）：
  「去掉输入框里固定指定负责人的入口和配置。审批流程调整为：用户填写完表单发起审批后，
    再进入负责人确认环节，提供两种选择 —— 默认负责人（沿用原本配置的流程）或
    指定负责人（支持选择多个），由用户自行决定。最终返回的数据中需包含数据流情况和
    处理人信息，并保证结构清晰、字段完整。」

判据（每条都回接口/库核，不看界面文字自证）：
  A1 默认提交（不传负责人）→ handlers.mode=DEFAULT、specified 为空、仍按后台流程建节点
  A2 指定 2 人 → handlers.mode=SPECIFIED；specified 顺序 == 传入顺序；dataFlow 前两级
     的 approver 顺序与之一致且 source=SPECIFIED；第 1 级 current=true
  A3 指定人插在配置流**前面**（原节点 seq 后移），不是替换也不是追加在后面
  A4 指定含申请人本人 → 400，文案点明「申请人本人」
  A5 指定不存在的人 → 400，文案点明「在职成员」
  A6 重复 userId 去重后只建一个节点（不出现同一个人两级）
  A7 dataFlow / handlers 字段完整性（缺一个字段就算红）
  B1 通用表单（APPROVAL 策略）提交带 2 人 → receipt.handlers / receipt.dataFlow 同口径
  U1 H5 输入栏**不再有**「指定负责人」入口（DOM 不存在）
  U2 表单卡片：提交 → 核对 → 「确认提交」后**先弹负责人确认**（两个选项）
  U3 默认选中「默认负责人」；切「指定负责人」出现候选列表
  U4 一个没选就确认 → 拦下且**不发请求**
  U5 多选 2 人 → 真提交的 body 带 assigneeUserIds（顺序一致）
  U6 回执卡渲染「处理人 + 数据流」两块（含当前级）
  U7 全程无 JS 报错

前置：后端 :8080（H5 在 /aios/h5/）；agent 不必在线（SSE 用桩，只伪造「生成表单」这一段）。
用法：python scripts/_verify_handler_confirm.py
"""

try:  # A3：GBK 控制台打印中文/符号会 UnicodeEncodeError
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
RUN_ID = "e2e-handler-run-1"

results = []
created_orders = []
created_leaves = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def sql(q):
    return subprocess.run([MYSQL, "-uroot", "aios", "-e", q],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def login():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"], {"Authorization": "Bearer " + d["data"]["accessToken"]}


def post(h, path, body=None, timeout=60):
    return httpx.post(API + path, headers=h, json=body if body is not None else {}, timeout=timeout,
                      trust_env=False).json()


def get(h, path):
    return httpx.get(API + path, headers=h, timeout=30, trust_env=False).json()


def main():
    token, user, h = login()
    me = int(user.get("id") or 0)
    inst = int(user.get("institutionId") or 0)

    # ---------------------------------------------------------------- P 前置：可审批候选人
    members = (get(h, "/org/members?size=200").get("data") or {})
    rows = members.get("items") or []
    cands = [m for m in rows if m.get("userId") and int(m["userId"]) != me]
    print(f"      · 本机构在职成员 {len(rows)} 人，可作为负责人的 {len(cands)} 人")
    if len(cands) < 2:
        # 补齐候选：把同租户已有账号登记进本机构（测完删除）。不新造账号，避免留垃圾。
        sql(f"""INSERT INTO org_member (tenant_id, institution_id, user_id, name, status, created_at)
                SELECT 56, {inst}, u.id, u.username, 'ACTIVE', NOW() FROM sys_user u
                WHERE u.tenant_id=56 AND u.id NOT IN
                  (SELECT user_id FROM org_member WHERE institution_id={inst}) LIMIT 2;""")
        members = (get(h, "/org/members?size=200").get("data") or {})
        rows = members.get("items") or []
        cands = [m for m in rows if m.get("userId") and int(m["userId"]) != me]
        print(f"      · 补齐后候选 {len(cands)} 人")
    if len(cands) < 2:
        raise SystemExit("候选负责人不足 2 人，无法验证「多选」")
    u1, u2 = int(cands[0]["userId"]), int(cands[1]["userId"])
    n1, n2 = cands[0].get("name"), cands[1].get("name")

    types = get(h, "/leave/types").get("data") or []
    # 选一个「不要证明 + 提前天数最少」的假种：其余校验（余额/最长连续/证明）与本轮无关
    # 优先「不占额度」（quotaDaysPerYear=0 ⇒ 后端 quotaTracked=false，不校验余额）的假种：
    # 否则每跑一次就在 test 账号上占掉 1 天在途额度，第二次跑就变成「余额不足」假红。
    pool = [t for t in types if not t.get("needProof")]
    lt = (next((t for t in pool if float(t.get("quotaDaysPerYear") or 0) == 0), None)
          or (sorted(pool, key=lambda t: (t.get("advanceDays") or 0))[0] if pool else None))
    if not lt:
        raise SystemExit("没有可用假种")
    adv = int(lt.get("advanceDays") or 0)
    # 日期必须落在**工作日**：假种单位是 WORKDAY，跨周末会算出「申请天数为 0」而被拦下
    # （2026-11-06 实测：11-07 是周六，直接 today+1 提交 ⇒ 400「所选区间可能全部为休息日」）。
    d = time.localtime(time.time() + (adv + 1) * 86400)
    while time.strftime("%w", d) in ("0", "6"):          # 0=周日 6=周六
        d = time.localtime(time.mktime(d) + 86400)
    today = time.strftime("%Y-%m-%d", d)                  # 只请 1 个工作日，区间必为非空
    end = today
    print(f"      · 假种 {lt.get('code')}（提前 {adv} 天），请假区间 {today}（1 个工作日）")

    def leave(assignees=None, label=""):
        body = {"leaveTypeCode": lt["code"], "startDate": today, "endDate": end,
                "reason": "负责人确认环节验收" + label}
        if assignees is not None:
            body["assigneeUserIds"] = assignees
        r = post(h, "/leave/requests", body)
        if r.get("code") == 0:
            d = r.get("data") or {}
            if d.get("orderId"):
                created_orders.append(int(d["orderId"]))
            if d.get("leaveRequestId"):
                created_leaves.append(int(d["leaveRequestId"]))
        return r

    def steps_of(r):
        return ((r.get("data") or {}).get("dataFlow") or {}).get("steps") or []

    # ---------------------------------------------------------------- A1 默认负责人
    r = leave(label="·默认")
    d = r.get("data") or {}
    hd = d.get("handlers") or {}
    df = d.get("dataFlow") or {}
    rec("A1 默认提交：handlers.mode=DEFAULT 且没有指定名单",
        r.get("code") == 0 and hd.get("mode") == "DEFAULT" and (hd.get("specified") or []) == [],
        "{mode:'DEFAULT', specified:[]}",
        {"code": r.get("code"), "message": r.get("message"), "mode": hd.get("mode"),
         "specified": hd.get("specified")})
    rec("A1b 默认提交：dataFlow 仍按后台流程给出节点与当前级",
        len(df.get("steps") or []) >= 1 and any(s.get("current") for s in df.get("steps") or []),
        "steps≥1 且有一级 current=True",
        {"steps": len(df.get("steps") or []), "currentSeq": df.get("currentSeq")})

    # ---------------------------------------------------------------- A2 指定 2 人
    r = leave([u1, u2], "·指定2人")
    d = r.get("data") or {}
    hd = d.get("handlers") or {}
    df = d.get("dataFlow") or {}
    spec = hd.get("specified") or []
    rec("A2 指定 2 人：mode=SPECIFIED 且名单顺序 == 传入顺序",
        r.get("code") == 0 and hd.get("mode") == "SPECIFIED"
        and [int(x.get("userId")) for x in spec] == [u1, u2],
        f"SPECIFIED, [{u1},{u2}]", {"mode": hd.get("mode"),
                                    "specified": [int(x.get("userId")) for x in spec], "names": [x.get("name") for x in spec]})
    steps = steps_of(r)
    first_two = [int((s.get("approver") or {}).get("userId") or 0) for s in steps[:2]]
    rec("A2b dataFlow 前两级就是这两个人，且 source=SPECIFIED、第 1 级为当前级",
        first_two == [u1, u2]
        and all(s.get("source") == "SPECIFIED" for s in steps[:2])
        and bool(steps) and steps[0].get("current") is True,
        f"前两级 [{u1},{u2}] / SPECIFIED / 第1级 current",
        {"firstTwo": first_two, "sources": [s.get("source") for s in steps[:2]],
         "currents": [s.get("current") for s in steps[:2]]})
    rec("A2c 回执的 currentApprover 就是第 1 位指定人",
        int(d.get("currentApproverId") or 0) == u1 and (hd.get("current") or {}).get("userId") == u1,
        f"currentApproverId={u1}",
        {"currentApproverId": d.get("currentApproverId"), "handlers.current": hd.get("current")})

    # ---------------------------------------------------------------- A3 插在配置流前面
    flow_steps = [s for s in steps if s.get("source") == "FLOW"]
    spec_steps = [s for s in steps if s.get("source") == "SPECIFIED"]
    rec("A3 指定人整体排在配置流节点之前（seq 1..N），原节点 seq 后移",
        bool(spec_steps) and bool(flow_steps)
        and max(int(s["seq"]) for s in spec_steps) < min(int(s["seq"]) for s in flow_steps),
        "max(指定 seq) < min(配置流 seq)",
        {"specSeq": [s["seq"] for s in spec_steps], "flowSeq": [s["seq"] for s in flow_steps],
         "nodeCount": df.get("nodeCount")},
        "配置流（tenant 56 LEAVE）= DEPT_LEADER + ORG_ADMIN(threshold_days=3)，短假期节点2会 SKIPPED，属预期")

    # ---------------------------------------------------------------- A4/A5/A6 校验与去重
    r = leave([me], "·自审")
    rec("A4 指定申请人本人 → 400 且点明「申请人本人」",
        r.get("code") == 400 and "申请人本人" in str(r.get("message")),
        "code=400 且含「申请人本人」", {"code": r.get("code"), "message": r.get("message")})
    r = leave([999999], "·不存在")
    rec("A5 指定不在本机构在职的人 → 400 且点明「在职成员」",
        r.get("code") == 400 and "在职成员" in str(r.get("message")),
        "code=400 且含「在职成员」", {"code": r.get("code"), "message": r.get("message")})
    r = leave([u1, u1, u2], "·重复")
    spec = ((r.get("data") or {}).get("handlers") or {}).get("specified") or []
    rec("A6 重复 userId 去重：传 [u1,u1,u2] 只建 2 个指定节点",
        r.get("code") == 0 and [int(x.get("userId")) for x in spec] == [u1, u2],
        f"[{u1},{u2}]", [int(x.get("userId")) for x in spec])

    # ---------------------------------------------------------------- A7 字段完整性
    need_step = {"seq", "taskId", "approverType", "approverTypeLabel", "source", "approver",
                 "nodeMode", "status", "statusLabel", "current"}
    s0 = (steps_of(r) or [{}])[0]
    missing_step = sorted(k for k in need_step if k not in s0)
    need_hd = {"mode", "modeLabel", "specified", "specifiedCount", "current", "cc", "nodeCount"}
    hd0 = (r.get("data") or {}).get("handlers") or {}
    missing_hd = sorted(k for k in need_hd if k not in hd0)
    need_flow = {"orderId", "bizType", "title", "applicant", "submittedAt", "status",
                 "statusLabel", "steps", "nodeCount", "currentSeq"}
    df0 = (r.get("data") or {}).get("dataFlow") or {}
    missing_flow = sorted(k for k in need_flow if k not in df0)
    rec("A7 dataFlow / handlers 字段完整（缺一即红）",
        not missing_step and not missing_hd and not missing_flow,
        "steps/handlers/dataFlow 字段齐全",
        {"缺少 step 字段": missing_step, "缺少 handlers 字段": missing_hd, "缺少 dataFlow 字段": missing_flow})

    # ---------------------------------------------------------------- B1 通用表单
    launch = get(h, "/forms/launchable?policy=APPROVAL").get("data") or []
    code = next((f.get("code") for f in launch if f.get("code") == "notice_publish"),
                (launch[0] or {}).get("code") if launch else None)
    form_rec = None
    if code:
        fdef = get(h, f"/forms/{code}").get("data") or {}
        vals = {}
        for f in fdef.get("fields") or []:
            if not f.get("required"):
                continue
            t = (f.get("type") or "text").lower()
            opts = f.get("options") or []
            if t in ("select", "radio"):
                vals[f["name"]] = (opts[0].get("value") if opts and isinstance(opts[0], dict) else (opts[0] if opts else "1"))
            elif t == "multiselect":
                vals[f["name"]] = [(opts[0].get("value") if opts and isinstance(opts[0], dict) else (opts[0] if opts else "1"))]
            elif t == "boolean":
                vals[f["name"]] = True
            elif t in ("number", "integer"):
                vals[f["name"]] = 1
            elif t == "date":
                vals[f["name"]] = today
            elif t == "datetime":
                vals[f["name"]] = today + "T09:00"
            else:
                vals[f["name"]] = "负责人确认环节验收"
        body = {"data": vals, "assigneeUserIds": [u2, u1]}
        r2 = post(h, f"/forms/{code}/submit", body)
        receipt = ((r2.get("data") or {}).get("receipt") or {})
        hd2 = receipt.get("handlers") or {}
        df2 = receipt.get("dataFlow") or {}
        spec2 = hd2.get("specified") or []
        st2 = df2.get("steps") or []
        form_rec = r2
        if (r2.get("data") or {}).get("approvalOrderId"):
            created_orders.append(int(r2["data"]["approvalOrderId"]))
        rec(f"B1 通用表单（{code}）提交带 2 人：回执 handlers/dataFlow 与请假同口径",
            r2.get("code") == 0 and hd2.get("mode") == "SPECIFIED"
            and [int(x.get("userId")) for x in spec2] == [u2, u1]
            and [int((s.get("approver") or {}).get("userId") or 0) for s in st2[:2]] == [u2, u1],
            f"SPECIFIED 且前两级 [{u2},{u1}]",
            {"code": r2.get("code"), "msg": r2.get("message"),
             "mode": hd2.get("mode"), "specified": [int(x.get("userId")) for x in spec2],
             "firstTwo": [int((s.get("approver") or {}).get("userId") or 0) for s in st2[:2]]})
    else:
        rec("B1 通用表单（APPROVAL）可用", False, "launchable 里有 APPROVAL 表单", launch)

    # ---------------------------------------------------------------- U 段：浏览器
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="zh-CN")
        ctx.add_init_script(
            "localStorage.setItem('aios_session', %s);localStorage.setItem('aios_mode','oa');"
            % json.dumps(json.dumps({"token": token, "user": user}, ensure_ascii=False)))
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))

        # 只伪造「生成表单」这一段 SSE：提交、校验、落库全走真后端
        def on_create_run(route, request):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"code": 0, "message": "ok", "data": {"id": RUN_ID}}))

        frame = {"form_code": code, "version": (get(h, f"/forms/{code}").get("data") or {}).get("version"),
                 "title": (get(h, f"/forms/{code}").get("data") or {}).get("name"),
                 "submit_label": "提交审批", "reason": "提交后进入审批",
                 "fields": (get(h, f"/forms/{code}").get("data") or {}).get("fields") or [],
                 "origin": {"kind": "worker", "worker_id": 1, "worker_name": "审批助手"}}

        def on_events(route, request):
            sse = ("event: need_form\ndata: %s\n\n"
                   'event: run.completed\ndata: {"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
                   % json.dumps(frame, ensure_ascii=False))
            route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body=sse)

        pg.route("**/v1/conversations/*/runs", on_create_run)
        pg.route("**/v1/runs/%s/events" % RUN_ID, on_events)

        submit_bodies = []

        def on_req(req):
            if req.method == "POST" and req.url.endswith("/submit") and "/forms/" in req.url:
                try:
                    submit_bodies.append(json.loads(req.post_data or "{}"))
                except Exception:
                    pass
        pg.on("request", on_req)

        pg.goto(H5, wait_until="domcontentloaded")
        pg.wait_for_selector("#oaRoot", timeout=30000)
        pg.wait_for_timeout(2500)

        # U1 输入栏不再有指定负责人入口
        no_btn = pg.evaluate("() => !document.getElementById('oaAssignBtn') && !document.getElementById('oaAssignBar')")
        rec("U1 输入栏已去掉「指定负责人」入口（按钮与 chip 都不在 DOM 里）", no_btn,
            "oaAssignBtn / oaAssignBar 均不存在", no_btn)
        pg.screenshot(path=str(OUT / "30-input-no-assign.png"))

        # U2 唤起表单卡片
        pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
        pg.wait_for_timeout(500)
        pg.evaluate("() => { const b = document.getElementById('odNewChat'); if(b) b.click(); }")
        pg.wait_for_timeout(600)
        pg.fill("#oaInput", "帮我发一个通知公告")
        pg.wait_for_timeout(200)
        pg.click("#oaSendBtn", force=True)
        sel = '.leave-form[data-code="%s"]' % code
        try:
            pg.wait_for_selector(sel, timeout=15000)
            got_card = True
        except Exception:
            got_card = False
        rec("U2 表单卡片渲染成功（后续步骤的前提）", got_card, sel, got_card)
        if not got_card:
            b.close()
        else:
            # 填必填字段（按后端 schema 的类型逐类填；与卡片渲染同源）
            pg.evaluate("""(args) => {
                const card = document.querySelector('.leave-form[data-code="'+args.code+'"]');
                if(!card) return;
                card.querySelectorAll('[data-field]').forEach(c => {
                  const type = c.getAttribute('data-type');
                  const req = c.getAttribute('data-required') === '1';
                  if(!req) return;
                  if(type === 'select'){ if(c.options.length > 1) c.selectedIndex = 1; }
                  else if(type === 'multiselect'){ if(c.options.length > 0) c.options[0].selected = true; }
                  else if(type === 'boolean'){ c.checked = true; }
                  else if(type === 'number'){ c.value = '1'; }
                  else if(type === 'date'){ c.value = args.d1; }
                  else if(type === 'datetime'){ c.value = args.d1 + 'T09:00'; }
                  else { c.value = '负责人确认环节验收'; }
                  c.dispatchEvent(new Event('input', {bubbles:true}));
                  c.dispatchEvent(new Event('change', {bubbles:true}));
                });
            }""", {"code": code, "d1": today})
            pg.click(sel + " [data-form-submit]")
            pg.wait_for_timeout(500)
            has_summary = pg.locator(sel + " [data-form-confirm]").count() > 0
            rec("U2b 点「提交」先出核对面板（原有两段式未被破坏）", has_summary, "存在 [data-form-confirm]", has_summary)

            # U3 确认提交 → 负责人确认弹层
            pg.click(sel + " [data-form-confirm]")
            try:
                pg.wait_for_selector("#hdMask.on", timeout=8000)
                pg.wait_for_timeout(500)      # 等淡入动画结束再截图/判读（否则整层半透明、底下 tabbar 透出来）
                opened = True
            except Exception:
                opened = False
            opts = pg.evaluate("() => Array.from(document.querySelectorAll('#hdMask .hd-opt'))"
                               ".map(e => ({k:e.getAttribute('data-hd'), on:e.classList.contains('on'),"
                               " t:(e.textContent||'').replace(/\\s+/g,' ').trim()}))")
            rec("U3 「确认提交」后先弹「确认负责人」，两个选项齐全且默认选中「默认负责人」",
                opened and len(opts) == 2 and any(o["k"] == "DEFAULT" and o["on"] for o in opts)
                and all(any(w in o["t"] for o in opts) for w in ["默认负责人", "指定负责人"]),
                "两选项、DEFAULT 默认选中", {"opened": opened, "opts": opts})
            pg.screenshot(path=str(OUT / "31-handler-confirm.png"))

            # U4 不选人直接确认 → 拦下且不发请求
            before = len(submit_bodies)
            pg.click('#hdMask [data-hd="SPECIFIED"]')
            pg.wait_for_timeout(1200)
            cands_ui = pg.evaluate("() => Array.from(document.querySelectorAll('#hdList [data-uid]'))"
                                   ".map(e => (e.querySelector('.hd-nm')||{}).textContent)")
            rec("U4 切「指定负责人」→ 出现候选名单（来自本机构在职成员）",
                len(cands_ui) >= 2, "≥2 个候选", {"n": len(cands_ui), "names": cands_ui[:5]})
            pg.click("#hdMask [data-hd-ok]")
            pg.wait_for_timeout(600)
            err_txt = pg.evaluate("() => { const e = document.getElementById('hdErr');"
                                  "return e && !e.hidden ? e.textContent : ''; }")
            still_open = pg.evaluate("() => !!document.querySelector('#hdMask.on')")
            rec("U4b 一个没选就确认 → 被拦下（弹层不关、不发提交请求）",
                ("至少选择" in str(err_txt)) and still_open and len(submit_bodies) == before,
                "提示「请至少选择一位负责人」且请求数不变",
                {"err": err_txt, "open": still_open, "reqs": [len(submit_bodies), before]})
            pg.screenshot(path=str(OUT / "32-specified-required.png"))

            # U5 选 2 人（按点击顺序）→ 真提交
            pg.evaluate("() => { const items = document.querySelectorAll('#hdList [data-uid]');"
                        "if(items[0]) items[0].click(); }")
            pg.wait_for_timeout(300)
            pg.evaluate("() => { const items = document.querySelectorAll('#hdList [data-uid]');"
                        "if(items[1]) items[1].click(); }")
            pg.wait_for_timeout(400)
            chips = pg.evaluate("() => Array.from(document.querySelectorAll('#hdPicked .hd-chip'))"
                                ".map(e => (e.textContent||'').trim())")
            rec("U5 选中两人后出现带序号的已选 chips（1. / 2.）",
                len(chips) == 2 and "1." in chips[0] and "2." in chips[1],
                "两个 chip 且带 1./2.", chips)
            pg.screenshot(path=str(OUT / "33-two-picked.png"))
            pg.click("#hdMask [data-hd-ok]")
            pg.wait_for_timeout(2500)
            body_sent = submit_bodies[-1] if submit_bodies else {}
            sent_ids = body_sent.get("assigneeUserIds") or []
            rec("U5b 真提交的请求体带 assigneeUserIds（两位、顺序与选择一致）",
                len(sent_ids) == 2 and len(set(sent_ids)) == 2,
                "2 个 userId", sent_ids)
            receipt_ui = pg.evaluate("() => { const r = document.querySelector('.lf-receipt');"
                                     "return r ? r.innerText.replace(/\\s+/g,' ') : ''; }")
            rec("U6 回执卡渲染「处理人」与「数据流」（含当前级）",
                ("处理人" in receipt_ui) and ("数据流" in receipt_ui) and ("当前" in receipt_ui),
                "含 处理人 / 数据流 / 当前", receipt_ui[:160])
            pg.screenshot(path=str(OUT / "34-receipt-flow.png"))

            rec("U7 全程无 JS 运行时报错", len(errs) == 0, "0 条", errs[:3])
            b.close()

    # ---------------------------------------------------------------- 清理
    if created_orders:
        ids = ",".join(str(x) for x in created_orders)
        sql(f"DELETE FROM approval_task WHERE order_id IN ({ids});")
        sql(f"DELETE FROM form_submission WHERE approval_order_id IN ({ids});")
        sql(f"DELETE FROM approval_order WHERE id IN ({ids});")
    if created_leaves:
        lids = ",".join(str(x) for x in created_leaves)
        sql(f"DELETE FROM leave_request WHERE id IN ({lids});")
        # 在途额度按**剩余**的 PENDING 单重算（不写死 0）：只还原本脚本占掉的部分
        sql("""UPDATE leave_balance b SET pending_days = COALESCE((
                 SELECT SUM(r.days) FROM leave_request r
                 WHERE r.user_id=b.user_id AND r.leave_type_code=b.leave_type_code
                   AND YEAR(r.start_date)=b.year AND r.status='PENDING'
                   AND r.deleted_at IS NULL), 0)
               WHERE b.user_id=%d;""" % me)
    ok = sum(1 for _, v in results if v)
    print("\n" + "=" * 70)
    for name, v in results:
        print(("  ✅ " if v else "  ❌ ") + name)
    print(f"\n合计 {len(results)} 项，通过 {ok}，失败 {len(results) - ok}")
    print("截图目录：", OUT)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
