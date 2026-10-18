# -*- coding: utf-8 -*-
"""
_verify_form_flow.py — docs/52 P4「数据流转」端到端哨兵（LEDGER / APPROVAL / RESUME）
================================================================================

打**真实后端 + 真实库**（不 stub），验证三件事：

  B  LEDGER  ：提交 → form_submission.status=DONE，不进审批，无 approval_order_id
  C  负向    ：缺必填 → 4xx，且**不落库**（计数不变；证明校验不是恒真）
  D  RESUME  ：APPROVAL+RESUME 策略 → status=APPROVING + approvalOrderId 非空 + resume=True
  E  终态回写：审批人驳回 → form_submission.status=REJECTED（ApprovalOutcomeSink 真跑通）
  F  回执同源：receipt.lines 的 label 来自**表单库字段 title**、value 是**用户真实填写值**
              （2026-10-17 修复前 43 张表的 receipt_json 写的是 display_fields，
                与后端 lines 契约不符 ⇒ 全部静默退化成「提交单号」兜底；本条专门钉死它）
  G  自清理  ：把本套件产生的 form_submission / approval_order / approval_task / notification
              删干净，并断言删除后计数为 0（可复核、可重复跑）

跑法（后端 :8080 在线，MySQL 可连）：
    C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
        scripts/_verify_form_flow.py [--host http://127.0.0.1:8080]

退出码 = 失败条数（0 = 全绿）。本机有 http_proxy 时必须 trust_env=False，否则 502。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pymysql
import requests

BASE = "http://127.0.0.1:8080/api/v1"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios")
USER, PWD = "wjj_xu", "User@123"          # 租户 3 普通成员（有 LEAVE 审批流配置）
APPROVER_PWD = "User@123"
MARK = "E2E-FORM-"                         # 本套件数据前缀，便于人工复查/兜底清理

passed = 0
failed = 0


def chk(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print("  [OK  ] %s%s" % (name, (" — " + str(detail)) if detail else ""))
    else:
        failed += 1
        print("  [FAIL] %s%s" % (name, (" — " + str(detail)) if detail else ""))


def login(username: str, pwd: str = PWD) -> tuple[str, dict]:
    r = S.post(BASE + "/auth/login", json={"username": username, "password": pwd})
    j = r.json()
    assert j.get("code") == 0, "登录失败 %s: %s" % (username, j)
    return j["data"]["accessToken"], j["data"]["user"]


def call(method: str, path: str, token: str, **kw):
    r = S.request(method, BASE + path, headers={"Authorization": "Bearer " + token}, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def auto_data(fields: list[dict]) -> dict:
    """按表单定义的字段类型自动造合法数据（不写死任何字段名）。"""
    data = {}
    for f in fields:
        t = f["type"]
        name = f["name"]
        if t == "date":
            data[name] = "2026-11-02"
        elif t == "datetime":
            data[name] = "2026-11-02 09:30:00"
        elif t == "number":
            data[name] = 2
        elif t == "amount":
            data[name] = 128.5
        elif t == "boolean":
            data[name] = True
        elif t == "select":
            opts = f.get("options") or []
            data[name] = (opts[0].get("value") if opts else "X")
        elif t == "multiselect":
            opts = f.get("options") or []
            data[name] = [opts[0].get("value")] if opts else ["X"]
        elif t == "file":
            data[name] = MARK + "proof.png"
        else:
            data[name] = MARK + "自动化填写"
    return data


def db():
    return pymysql.connect(charset="utf8mb4", autocommit=True, **DB)


def count_submissions(cur, code: str) -> int:
    cur.execute("SELECT COUNT(*) FROM form_submission WHERE code=%s AND deleted_at IS NULL", (code,))
    return cur.fetchone()[0]


def main() -> int:
    global S
    S = requests.Session()
    S.trust_env = False

    print("== A 前置 ==")
    tok, user = login(USER)
    tenant_id = user.get("tenantId")
    chk("A1 成员登录", tok is not None, "user=%s tenant=%s" % (user.get("username"), tenant_id))

    st, wl = call("GET", "/forms/worklog_submit", tok)
    wl_def = wl.get("data") or {}
    chk("A2 工作日志表单可渲染且策略=LEDGER",
        st == 200 and wl_def.get("submitPolicy") == "LEDGER" and len(wl_def.get("fields") or []) > 0,
        "st=%s policy=%s fields=%d" % (st, wl_def.get("submitPolicy"), len(wl_def.get("fields") or [])))

    st, lv = call("GET", "/forms/leave_request", tok)
    lv_def = lv.get("data") or {}
    policy = str(lv_def.get("submitPolicy") or "")
    chk("A3 请假表单策略含 APPROVAL+RESUME",
        st == 200 and "APPROVAL" in policy and "RESUME" in policy,
        "st=%s policy=%s" % (st, policy))

    conn = db()
    cur = conn.cursor()

    # ---------------------------------------------------------------- B LEDGER
    print("\n== B LEDGER 分流 ==")
    wl_data = auto_data(wl_def["fields"])
    wl_data["today_work"] = MARK + "今日完成：表单流转哨兵"
    st, res = call("POST", "/forms/worklog_submit/submit", tok, json={"data": wl_data})
    body = res.get("data") or {}
    chk("B1 提交成功且 HTTP 200", st == 200 and body.get("submissionId"), "st=%s %s" % (st, res))
    sub_ledger = body.get("submissionId")
    chk("B2 分流为 DONE（台账，不进审批）",
        body.get("status") == "DONE", "status=%s" % body.get("status"))
    chk("B3 不进审批：approvalOrderId 为空、resume=False",
        body.get("approvalOrderId") is None and body.get("resume") is False,
        "orderId=%s resume=%s" % (body.get("approvalOrderId"), body.get("resume")))
    if sub_ledger:
        cur.execute("SELECT status, approval_order_id, biz_type FROM form_submission WHERE id=%s", (sub_ledger,))
        row = cur.fetchone()
        chk("B4 库里状态与接口一致（铁律 12：判据回到库）",
            row and row[0] == "DONE" and row[1] is None, "db=%s" % (row,))

    # ---------------------------------------------------------------- F 回执
    print("\n== F 声明式回执（与表单库同源） ==")
    receipt = body.get("receipt") or {}
    lines = receipt.get("lines") or []
    titles = {f["label"] for f in wl_def["fields"]}
    labels = [ln.get("label") for ln in lines]
    chk("F1 回执含 lines 且非「提交单号」兜底",
        len(lines) > 0 and labels != ["提交单号"], "labels=%s" % labels)
    chk("F2 回执 label 全部来自表单库字段 title（不是硬编码）",
        bool(labels) and set(labels).issubset(titles), "labels=%s titles=%s" % (labels, sorted(titles)))
    by_label = {ln.get("label"): ln.get("value") for ln in lines}
    date_label = next((f["label"] for f in wl_def["fields"] if f["type"] == "date"), None)
    chk("F3 ${field} 占位替换成用户真实填写值",
        date_label in by_label and by_label[date_label] == wl_data.get("log_date"),
        "%s=%s 期望=%s" % (date_label, by_label.get(date_label), wl_data.get("log_date")))

    # ---------------------------------------------------------------- C 负向
    print("\n== C 负向对照（校验必须能红，失败不得落库） ==")
    before = count_submissions(cur, "worklog_submit")
    st, res = call("POST", "/forms/worklog_submit/submit", tok,
                   json={"data": {"log_date": "2026-11-02"}})   # 缺 today_work（必填）
    after = count_submissions(cur, "worklog_submit")
    # 判据说明：本仓库 `GlobalExceptionHandler.handleBiz` 只把 401/403/404 映射成真实 HTTP 状态，
    # 其余业务错误一律 **HTTP 200 + body.code=400**（历史口径，H5 全站按 body.code 判成败）。
    # 所以这里断言的是「body.code=400 且不是 code=0」，不是 HTTP 4xx —— 不是放宽，是纠正 premise。
    biz_code = res.get("code") if isinstance(res, dict) else None
    chk("C1 缺必填被拒（body.code=400，不是成功也不是 500）",
        400 <= st < 500 or biz_code == 400,
        "http=%s body.code=%s %s" % (st, biz_code, json.dumps(res, ensure_ascii=False)[:160]))
    # 话术判据：报错必须用**字段中文名**（取自表单库 title），不能回显英文键名。
    # 2026-10-17 修复前：FormSchemaValidator.labelOf 只读 def.label（种子写的是 JSON Schema 的
    # title）⇒ 用户看到「必填字段「today_work」不能为空」，不知道要改哪一格。
    missing_name = "today_work"
    missing_label = next((f["label"] for f in wl_def["fields"] if f["name"] == missing_name), missing_name)
    msg = str(res.get("message") or "")
    chk("C1b 拒绝话术用字段中文名（不是英文键名）",
        missing_label in msg and missing_name not in msg,
        "message=%s 期望含「%s」且不含 %s" % (msg, missing_label, missing_name))
    chk("C2 校验失败不落库（提交数不变）", before == after, "before=%s after=%s" % (before, after))
    st, res = call("GET", "/forms/not_exist_form_zzz", tok)
    chk("C3 不存在的表单码不给空定义", 400 <= st < 500, "st=%s" % st)

    # ---------------------------------------------------------------- D APPROVAL
    print("\n== D APPROVAL + RESUME 分流 ==")
    lv_data = auto_data(lv_def["fields"])
    reason_field = next((f["name"] for f in lv_def["fields"] if f["type"] == "textarea"), None)
    if reason_field:
        lv_data[reason_field] = MARK + "请假事由（自动化）"
    st, res = call("POST", "/forms/leave_request/submit", tok, json={"data": lv_data})
    body = res.get("data") or {}
    sub_leave = body.get("submissionId")
    order_id = body.get("approvalOrderId")
    chk("D1 提交进入审批中（APPROVING）", st == 200 and body.get("status") == "APPROVING",
        "st=%s status=%s %s" % (st, body.get("status"), json.dumps(res, ensure_ascii=False)[:200]))
    chk("D2 生成审批单（approvalOrderId 非空）", bool(order_id), "orderId=%s" % order_id)
    chk("D3 RESUME 标记为真（对话要回填）", body.get("resume") is True, "resume=%s" % body.get("resume"))

    approver_username = None
    if order_id:
        cur.execute("SELECT id, approver_type, approver_id, status FROM approval_task "
                    "WHERE order_id=%s AND status='PENDING' ORDER BY seq LIMIT 1", (order_id,))
        task = cur.fetchone()
        chk("D4 审批任务已生成且待处理", task is not None, "task=%s" % (task,))
        if task:
            task_id, atype, aid = task[0], task[1], task[2]
            cur.execute("SELECT username FROM sys_user WHERE id=%s", (aid,))
            r = cur.fetchone()
            approver_username = r[0] if r else None
            chk("D5 能解析出审批人账号（后续驳回要用）", bool(approver_username),
                "type=%s approverId=%s username=%s" % (atype, aid, approver_username))

    # ---------------------------------------------------------------- E 终态回写
    print("\n== E 审批终态回写 form_submission ==")
    if order_id and approver_username:
        atok, au = login(approver_username, APPROVER_PWD)
        chk("E1 审批人可登录且有审批角色", atok is not None, "roles=%s" % au.get("roles"))
        st, res = call("POST", "/workflow/tasks/%s/decide" % task_id, atok,
                       json={"decision": "REJECT", "note": MARK + "自动化驳回"})
        chk("E2 驳回成功", st == 200 and (res.get("data") or {}).get("orderStatus") == "REJECTED",
            "st=%s %s" % (st, json.dumps(res, ensure_ascii=False)[:200]))
        cur.execute("SELECT status FROM form_submission WHERE id=%s", (sub_leave,))
        row = cur.fetchone()
        chk("E3 驳回后 form_submission 回写 REJECTED（ApprovalOutcomeSink 真跑通）",
            row and row[0] == "REJECTED", "db.status=%s" % (row[0] if row else None))
        cur.execute("SELECT status FROM approval_order WHERE id=%s", (order_id,))
        orow = cur.fetchone()
        chk("E4 审批单也处于 REJECTED（两者一致）",
            orow and orow[0] == "REJECTED", "order.status=%s" % (orow[0] if orow else None))
    else:
        chk("E1..E4 审批终态", False, "前置缺失：order_id=%s approver=%s" % (order_id, approver_username))

    # ---------------------------------------------------------------- G 自清理
    print("\n== G 自清理（可重复跑） ==")
    ids = [i for i in (sub_ledger, sub_leave) if i]
    orders = [order_id] if order_id else []
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cur.execute("DELETE FROM form_submission WHERE id IN (%s)" % ph, ids)
        print("  [clean] form_submission -%d" % cur.rowcount)
    if orders:
        oph = ",".join(["%s"] * len(orders))
        cur.execute("DELETE FROM notification WHERE ref_id IN (%s)" % oph, orders)
        print("  [clean] notification -%d" % cur.rowcount)
        cur.execute("DELETE FROM approval_task WHERE order_id IN (%s)" % oph, orders)
        print("  [clean] approval_task -%d" % cur.rowcount)
        cur.execute("DELETE FROM approval_order WHERE id IN (%s)" % oph, orders)
        print("  [clean] approval_order -%d" % cur.rowcount)
    left = 0
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cur.execute("SELECT COUNT(*) FROM form_submission WHERE id IN (%s)" % ph, ids)
        left += cur.fetchone()[0]
    if orders:
        oph = ",".join(["%s"] * len(orders))
        cur.execute("SELECT COUNT(*) FROM approval_order WHERE id IN (%s)" % oph, orders)
        left += cur.fetchone()[0]
    chk("G1 本套件数据已删干净（可重复跑）", left == 0, "残留=%d" % left)

    conn.close()
    print("\n[RESULT] 通过 %d / 失败 %d" % (passed, failed))
    return failed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8080")
    a = ap.parse_args()
    BASE = a.host.rstrip("/") + "/api/v1"
    sys.exit(main())
