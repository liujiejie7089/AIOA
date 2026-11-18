# -*- coding: utf-8 -*-
"""方案 C 修复后回归：新提交进审批流 + 两端可见 + 历史台账合并 + 审批流转 + 数据一致性。

铁律 7/12：只看接口不算，必须回库核对。
"""
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import time
import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=40, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
MARK = "FIXC-%s" % time.strftime("%m%d%H%M%S")
results = []


def check(tag, cond, detail=""):
    ok = bool(cond)
    results.append((tag, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", tag, ("  " + str(detail)) if detail else ""))
    return ok


def login(u, p):
    r = C.post(f"{BASE}/auth/login", json={"username": u, "password": p})
    return (r.json().get("data") or {}).get("accessToken")


def hd(t):
    return {"Authorization": "Bearer " + t}


def db(q, args=None):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(q, args or ())
            return cur.fetchall()
    finally:
        conn.close()


def arr(r):
    d = (r.json().get("data"))
    return d if isinstance(d, list) else []


def main():
    utok = login("zhangsan", "User@123")
    atok = login("dsj_admin", "Admin@123")
    check("登录用户端+管理端", bool(utok and atok))
    if not (utok and atok):
        return summary()
    H, AH = hd(utok), hd(atok)

    # 1. 配置已生效
    tpl = db("SELECT submit_policy, biz_type FROM form_template WHERE code='expense_form' AND tenant_id=0")
    check("① 平台模板已改 APPROVAL+EXPENSE",
          tpl and tpl[0]["submit_policy"] == "APPROVAL" and tpl[0]["biz_type"] == "EXPENSE", tpl)
    flow = db("SELECT id FROM approval_flow_def WHERE biz_type='EXPENSE' AND tenant_id=0 AND institution_id=0 AND status='ACTIVE'")
    check("② tenant=0 EXPENSE 流已补种", bool(flow), flow)

    # 2. 提交前：确认历史台账行已被 mine() 合并
    before = arr(C.get(f"{BASE}/workflow/mine", headers=H))
    ledger_seen = [x for x in before if x.get("source") == "ledger"]
    check("③ 历史台账行出现在我的申请（方案 B）", len(ledger_seen) > 0,
          [{"id": x.get("id"), "title": x.get("title"), "status": x.get("status")} for x in ledger_seen[:3]])

    # 3. 提交新费用报销
    payload = {"expense_type": "TRAVEL", "amount": 288, "occur_date": "2026-11-17",
               "reason": MARK + " 修复后回归", "invoice": "FIXC-INV"}
    r = C.post(f"{BASE}/forms/expense_form/submit", headers=H,
               json={"data": payload, "conversationId": None, "runId": None, "assigneeUserIds": None})
    body = r.json()
    data = body.get("data") or {}
    sub_id = data.get("submissionId")
    oid = data.get("approvalOrderId")
    print("  提交响应:", json.dumps(body, ensure_ascii=False)[:500])
    check("④ 新提交返回审批单号", body.get("code") == 0 and oid is not None,
          {"submissionId": sub_id, "approvalOrderId": oid, "status": data.get("status")})

    # 4. 回库核对
    sub = db("SELECT id,status,approval_order_id,code FROM form_submission WHERE id=%s", (sub_id,)) if sub_id else []
    check("⑤ form_submission 落行且回写审批单",
          bool(sub) and sub[0]["approval_order_id"] is not None and sub[0]["status"] == "APPROVING", sub)
    order = db("SELECT id,biz_type,title,status FROM approval_order WHERE id=%s", (oid,)) if oid else []
    check("⑥ approval_order 落行 bizType=EXPENSE",
          bool(order) and order[0]["biz_type"] == "EXPENSE" and order[0]["status"] == "PENDING", order)
    tasks = db("SELECT id,seq,approver_type,approver_id,status FROM approval_task WHERE order_id=%s ORDER BY seq", (oid,)) if oid else []
    check("⑦ approval_task 多级节点生成", len(tasks) >= 2, tasks)
    notif = db("SELECT id,title FROM notification WHERE tenant_id=0 AND ref_id=%s ORDER BY id DESC LIMIT 5", (str(oid),)) if oid else []
    print("  通知:", json.dumps(notif, ensure_ascii=False, default=str)[:300])

    # 5. 用户端我的申请可见（新单 + 历史台账）
    after = arr(C.get(f"{BASE}/workflow/mine", headers=H))
    new_seen = [x for x in after if str(x.get("id")) == str(oid) or
                (MARK in str(x.get("title", "")) + str(x.get("content", "")))]
    check("⑧ 用户端我的申请出现新单", len(new_seen) > 0,
          [{"id": x.get("id"), "status": x.get("status"), "title": x.get("title")} for x in new_seen[:2]])
    led_after = [x for x in after if x.get("source") == "ledger"]
    check("⑨ 历史台账仍合并且不与新单冲突", len(led_after) >= len(ledger_seen) and
          all(x.get("id", 0) < 0 for x in led_after), {"n": len(led_after)})

    # 6. 管理端待办可见 —— 第一级审批人是部门负责人 fagai_liu（user#7），不是 dsj_admin
    ltok = login("fagai_liu", "User@123")
    LH = hd(ltok)
    check("⑥b 部门负责人登录", bool(ltok))
    todo = arr(C.get(f"{BASE}/workflow/tasks", params={"scope": "todo"}, headers=LH))
    admin_seen = [x for x in todo if str(x.get("id")) == str(oid) or MARK in str(x.get("title", ""))]
    check("⑩ 管理端待审批出现新单（部门负责人视角）", len(admin_seen) > 0,
          [{"id": x.get("id"), "title": x.get("title"), "status": x.get("status")} for x in admin_seen[:2]])

    # 7. 审批流转：按 task 的 approver_id 选对应账号逐级批
    pend = [t for t in tasks if t["status"] == "PENDING"] if oid else []
    accts = {7: ("fagai_liu", "User@123"), 4: ("fagai_admin", "User@123"),
             1: ("admin", "Admin@123"), 2: ("zhangsan", "User@123")}
    checked_approve = False
    for t in pend:
        who = accts.get(int(t.get("approver_id") or 0)) if t.get("approver_id") else None
        if not who:
            print("  跳过任务", t.get("seq"), "无已知账号 approver_id=", t.get("approver_id"))
            continue
        tok = login(who[0], who[1])
        if not tok:
            print("  账号登录失败，跳过任务", t.get("seq"), who[0])
            continue
        dr = C.post(f"{BASE}/workflow/tasks/{t['id']}/decide", headers=hd(tok),
                    json={"decision": "APPROVE", "note": MARK + " 通过"})
        dbody = dr.json()
        if not checked_approve:
            check("⑪ 审批通过成功（有权限账号）", dr.status_code == 200 and dbody.get("code") == 0,
                  str(dbody)[:180])
            checked_approve = True
        o2 = db("SELECT status FROM approval_order WHERE id=%s", (oid,))
        if o2 and o2[0]["status"] != "PENDING":
            break
    if not checked_approve:
        check("⑪ 有待审批任务可流转", False, tasks)
    o2 = db("SELECT status FROM approval_order WHERE id=%s", (oid,)) if oid else []
    check("⑫ 审批流转到终态 APPROVED", bool(o2) and o2[0]["status"] == "APPROVED", o2)
    sub2 = db("SELECT status FROM form_submission WHERE id=%s", (sub_id,)) if sub_id else []
    check("⑬ 终态回写 form_submission 一致", bool(sub2) and sub2[0]["status"] in ("APPROVED", "DONE"), sub2)
    summary()


def summary():
    p = sum(1 for _, ok in results if ok)
    print("\n==== 汇总：%d/%d PASS ====" % (p, len(results)))
    for tag, ok in results:
        if not ok:
            print("  FAIL:", tag)


main()
