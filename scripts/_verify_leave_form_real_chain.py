"""请假走真链路验收（2026-11-06，docs/85）。

验的是什么
    后端 need_form 卡（通用表单提交）提交请假时，必须真正走进请假业务链路：
    建 leave_request 行、占在途额度、天数由后端按假种单位算、审批单号三处一致。
    历史缺陷：只落 form_submission ⇒ 「我的请假记录」查不到、余额永不扣、
    按天数的条件路由恒不成立（days 传的是 null）。

为什么必须回库核
    铁律 7/12：「界面展示了 X」不算证据。这里接口回执、DB 两行、独立算出的天数
    三方对照 —— 其中工作天数由本脚本自己按日历算，不采信任何一方的输出。

判据（每一条都能单独证伪）
    P1 提交成功（走 /forms/leave_request/submit 这条 need_form 同款入口）
    P2 天数 = 后端按 WORKDAY 算出的工作日数（不是自然日、也不是用户传的值）
       —— 提交时故意传 days=99，若回执/库里出现 99，说明用户自报仍然生效
    P3 leave_request 有这一行，且 order_id 与响应里的审批单号一致
    P4 form_submission 为 APPROVING，approval_order_id 与 leave_request.order_id 相同
    P5 在途额度真的被占（pending +N、可用 -N）
    P6 字典里不存在的假种码（PERSONAL）被拒，且提示是中文
    P7 缺必填字段时按**字段中文名**报错（不抖 reason / start_date 这类键名）
    P8 撤销后额度释放（在同一套链路上反向验证）

用法：python scripts/_verify_leave_form_real_chain.py
"""
import json
import pathlib
import subprocess
import sys
from datetime import date, timedelta

import httpx

BASE = "http://127.0.0.1:8080"
API = BASE + "/api/v1"
USER, PWD = "test", "test"
MYSQL = r"D:\dev\mysql\mysql-8.4.10-winx64\bin\mysql.exe"
FORM_CODE = "leave_request"
RUN_TAG = "e2e-leave-chain"

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n"
          f"      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def sql(q):
    return subprocess.run([MYSQL, "-uroot", "aios", "-e", q],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def sql_one(q):
    """取单值（mysql -N 无表头）。"""
    r = subprocess.run([MYSQL, "-uroot", "aios", "-N", "-e", q],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").strip()


def workdays(start, end):
    """本脚本自己算工作日（周一~周五）—— 不采信接口/DB 的天数。"""
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def next_weekday(target):
    """今天之后（含 7 天内）第一个指定星期几；保证不会选到过去。"""
    today = date.today()
    d = today + timedelta(days=1)
    while d.weekday() != target:
        d += timedelta(days=1)
    return d


def login():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    h = {"Authorization": "Bearer " + d["data"]["accessToken"]}
    return d["data"]["user"], h


def balance_of(h, code):
    d = httpx.get(f"{API}/leave/balance", headers=h, params={"year": date.today().year},
                  timeout=30, trust_env=False).json()
    for b in (d.get("data") or []):
        if b.get("leaveTypeCode") == code:
            return b
    return None


def main():
    user, h = login()
    uid = user.get("userId") or user.get("id")
    tenant = user.get("tenantId")

    # ---- 选假种：优先「占额度」的，才能验出在途占用（不占额度的假种永远不会扣） ----
    comp = balance_of(h, "COMP")
    if not comp or not comp.get("quotaTracked") or float(comp.get("availableDays") or 0) < 3:
        rec("P0 前置：存在可用额度 ≥3 天的假种", False,
            "COMP 可用 ≥3", comp)
        return _summary()
    rec("P0 前置：存在可用额度 ≥3 天的假种", True, "COMP 可用 ≥3",
        {"available": comp.get("availableDays"), "pending": comp.get("pendingDays")})

    # 起始日选「下周四」，结束日 = 下周一：自然日 5 天、工作日 3 天 —— 两种口径必然不同
    start = next_weekday(3)            # 周四
    end = start + timedelta(days=4)    # 下周一
    want = workdays(start, end)
    natural = (end - start).days + 1
    if want == natural:                # 防御：口径无法区分时直接报错，不给出无意义的绿灯
        rec("P0b 选到的区间能让「工作日/自然日」两种口径区分开", False,
            "want != natural", {"workdays": want, "natural": natural})
        return _summary()

    pending_before = float(comp.get("pendingDays") or 0)
    available_before = float(comp.get("availableDays") or 0)

    # ---- P1 提交（与 need_form 卡同一条接口） ----
    body = {"data": {
        "leave_type": "COMP",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "reason": "e2e 请假真链路验收（脚本自动撤销）",
        # ★ 故意传一个荒谬的天数：派生字段必须无视它。若这条生效，用户就能自报少扣额度。
        "days": 99,
    }, "runId": f"{RUN_TAG}-{int(__import__('time').time())}"}
    r = httpx.post(f"{API}/forms/{FORM_CODE}/submit", headers=h, json=body,
                   timeout=60, trust_env=False)
    resp = r.json()
    sub = resp.get("data") or {}
    receipt = sub.get("receipt") or {}
    rec("P1 提交成功（/forms/leave_request/submit，与 need_form 卡同一入口）",
        r.status_code == 200 and resp.get("code") == 0,
        "code=0", {"http": r.status_code, "code": resp.get("code"),
                   "message": resp.get("message")})
    if resp.get("code") != 0:
        return _summary()

    got_days = receipt.get("days")
    rec("P2a 回执天数 = 后端按 WORKDAY 算出的工作日数（不是用户传的 99、也不是自然日）",
        _num(got_days) == float(want),
        {"workdays": float(want), "natural": float(natural)},
        {"receipt.days": got_days, "sent": 99})

    leave_id = receipt.get("leaveRequestId")
    order_id = sub.get("approvalOrderId") or receipt.get("approvalOrderId")
    rec("P2b 回执带请假单号与审批单号（没有这两个，用户无从查询）",
        bool(leave_id) and bool(order_id), "两者均非空",
        {"leaveRequestId": leave_id, "approvalOrderId": order_id})

    # ---- P3 回库核 leave_request（第一方：库） ----
    row = sql_one(
        f"select concat_ws('|', id, days, order_id, user_id, leave_type_code, status) "
        f"from leave_request where id={int(leave_id)};") if leave_id else ""
    parts = row.split("|") if row else []
    rec("P3 leave_request 真的有这一行（不是只落 form_submission）",
        len(parts) >= 6, "存在该行", {"row": row})
    if len(parts) >= 6:
        rec("P3b 库里的天数 = 工作日数（三方一致：独立算 / 回执 / 库）",
            _num(parts[1]) == float(want), float(want),
            {"db.days": parts[1], "receipt.days": got_days, "computed": want})
        rec("P3c leave_request.order_id == 回执审批单号（审批通过才扣得掉余额）",
            str(parts[2]) == str(order_id), order_id, {"db.order_id": parts[2]})

    # ---- P4 form_submission 与请假单对齐（同一审批单号） ----
    srow = sql_one(
        f"select concat_ws('|', id, status, ifnull(approval_order_id,'')) from form_submission "
        f"where run_id like '{RUN_TAG}%' order by id desc limit 1;")
    sp = srow.split("|") if srow else []
    rec("P4 form_submission 为 APPROVING 且挂在同一张审批单上",
        len(sp) >= 3 and sp[1] == "APPROVING" and str(sp[2]) == str(order_id),
        {"status": "APPROVING", "approval_order_id": order_id},
        {"submission": srow})

    # ---- P5 在途额度真的被占 ----
    comp2 = balance_of(h, "COMP") or {}
    pending_after = float(comp2.get("pendingDays") or 0)
    available_after = float(comp2.get("availableDays") or 0)
    rec("P5 在途额度被占用（pending +N、可用 −N）—— 余额不再是「永远不扣」",
        _num(pending_after - pending_before) == float(want)
        and _num(available_before - available_after) == float(want),
        {"pending": f"+{want}", "available": f"-{want}"},
        {"pendingBefore": pending_before, "pendingAfter": pending_after,
         "availableBefore": available_before, "availableAfter": available_after})

    # ---- P6 字典里不存在的假种码必须被拒（PERSONAL 是 V86 的幽灵码） ----
    rb = httpx.post(f"{API}/forms/{FORM_CODE}/submit", headers=h, json={"data": {
        "leave_type": "PERSONAL",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "reason": "e2e 无效假种"}, "runId": f"{RUN_TAG}-bad"}, timeout=60, trust_env=False)
    jb = rb.json()
    rec("P6 字典里不存在的假种码（PERSONAL）被拒且提示可读",
        jb.get("code") not in (0, None) and "假种" in str(jb.get("message") or ""),
        "非 0 + 含「假种」", {"code": jb.get("code"), "message": jb.get("message")})

    # ---- P7 必填缺失时的提示用字段中文名 ----
    rb2 = httpx.post(f"{API}/forms/{FORM_CODE}/submit", headers=h, json={"data": {
        "leave_type": "COMP",
        "start_date": start.isoformat(),
        "end_date": end.isoformat()}, "runId": f"{RUN_TAG}-miss"}, timeout=60, trust_env=False)
    jb2 = rb2.json()
    msg = str(jb2.get("message") or "")
    rec("P7 缺必填时按字段中文名报错（不出现 reason / start_date 这类内部键）",
        ("请假事由" in msg) and ("reason" not in msg) and ("start_date" not in msg),
        "含「请假事由」且无内部键", msg)

    # ---- P8 撤销 ⇒ 额度释放（同一条链路的反向验证） ----
    rc = httpx.post(f"{API}/leave/requests/{int(leave_id)}/cancel", headers=h,
                    timeout=60, trust_env=False)
    comp3 = balance_of(h, "COMP") or {}
    pending_end = float(comp3.get("pendingDays") or 0)
    rec("P8 撤销后额度释放（pending 回到提交前）",
        rc.status_code == 200 and _num(pending_end) == _num(pending_before),
        {"pending": pending_before}, {"http": rc.status_code, "pendingAfterCancel": pending_end})

    # ---- 清场：删掉本次 e2e 的 form_submission（请假单保留 CANCELED，是真实撤销记录） ----
    sql(f"delete from form_submission where run_id like '{RUN_TAG}%';")
    return _summary()


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _summary():
    total = len(results)
    ok = sum(1 for _, v in results if v)
    print("\n" + "=" * 60)
    print(f"合计 {total} 项，通过 {ok}，失败 {total - ok}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
