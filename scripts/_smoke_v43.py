# -*- coding: utf-8 -*-
"""V43/V44 手工冒烟：二期部门申请 + 三期待阅已读（不经 E2E 框架）。"""
import httpx
import pymysql

API = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=30, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa", charset="utf8mb4")
created_orders = []


def login(u, p="User@123"):
    d = C.post(f"{API}/auth/login", json={"username": u, "password": p}).json()
    assert d.get("code") == 0, f"login {u}: {d}"
    return d["data"]["accessToken"]


def req(m, path, tok, **kw):
    r = C.request(m, API + path, headers={"Authorization": f"Bearer {tok}"}, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def purge_smoke():
    """删除所有 reason LIKE '冒烟%' 的残留（含上次中断留下的）。"""
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM approval_order WHERE content LIKE '%冒烟%' OR title LIKE '%冒烟%'")
            ids = sorted({r[0] for r in cur.fetchall()})
            if ids:
                cur.execute("DELETE FROM approval_task WHERE order_id IN %s", (tuple(ids),))
                cur.execute("DELETE FROM notification WHERE ref_id IN %s", (tuple(ids),))
                cur.execute("DELETE FROM permission_grant WHERE order_id IN %s", (tuple(ids),))
                cur.execute("DELETE FROM approval_order WHERE id IN %s", (tuple(ids),))
                conn.commit()
            print(f"[purge] 清理冒烟残留 orderIds={ids}")
    finally:
        conn.close()


def cleanup():
    if not created_orders:
        return
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM approval_task WHERE order_id IN %s", (tuple(created_orders),))
            cur.execute("DELETE FROM notification WHERE ref_id IN %s", (tuple(created_orders),))
            cur.execute("DELETE FROM permission_grant WHERE order_id IN %s", (tuple(created_orders),))
            cur.execute("DELETE FROM approval_order WHERE id IN %s", (tuple(created_orders),))
        conn.commit()
        print(f"[cleanup] 删除冒烟单据 {created_orders}")
    finally:
        conn.close()


def main():
    purge_smoke()
    tok_ldr = login("jybgs_ldr")          # 部门正职（inst17/dept77）
    tok_mem = login("jybgs_m01")          # 同部门普通成员
    tok_org = login("jyfzyjy_admin")      # inst17 企业管理员（3048）
    tok_oth = login("zbglk_ldr")          # 他机构正职（inst18）
    tok_plt = login("admin", "Admin@123")  # 平台管理员

    print("== A. catalog：部门开关数据源 ==")
    _, c = req("GET", "/org/permissions/catalog", tok_ldr)
    d = c.get("data", {})
    print(f"  负责人 canApplyAsDepartment={d.get('canApplyAsDepartment')} ledDepartments={d.get('ledDepartments')}")
    _, c2 = req("GET", "/org/permissions/catalog", tok_mem)
    d2 = c2.get("data", {})
    print(f"  普通成员 canApplyAsDepartment={d2.get('canApplyAsDepartment')} ledDepartments={d2.get('ledDepartments')}")
    assert d.get("canApplyAsDepartment") is True and any(x.get("id") == 77 for x in d.get("ledDepartments", []))
    assert d2.get("canApplyAsDepartment") is False and d2.get("ledDepartments") == []

    print("== B. 个人申请（缺省）→ USER ==")
    st, b = req("POST", "/org/permissions/apply", tok_mem, json={"permissionCode": "approval:leave", "reason": "冒烟·个人缺省"})
    print(f"  HTTP {st} code={b.get('code')} applicantType={b.get('data',{}).get('applicantType')} applicantDepartmentId={b.get('data',{}).get('applicantDepartmentId')}")
    assert b.get("code") == 0, b
    oid_mem = int(b["data"]["orderId"]); created_orders.append(oid_mem)
    assert b["data"].get("applicantType") == "USER" and b["data"].get("applicantDepartmentId") is None
    tl = b["data"].get("timeline") or []
    print(f"  个人链首节点={tl[0]['approverType']} id={tl[0]['approverId']} ccCount={b['data'].get('ccCount')}")
    assert tl and tl[0]["approverType"] == "DEPT_LEADER"

    print("== C. 部门名义申请（负责人）→ DEPARTMENT，起点=机构管理员 ==")
    st, b = req("POST", "/org/permissions/apply", tok_ldr,
                json={"permissionCode": "expert:manage", "reason": "冒烟·部门申请", "applyAsDepartment": True, "departmentId": 77})
    print(f"  HTTP {st} code={b.get('code')} applicantType={b.get('data',{}).get('applicantType')} applicantDepartmentId={b.get('data',{}).get('applicantDepartmentId')}")
    assert b.get("code") == 0, b
    oid_dept = int(b["data"]["orderId"]); created_orders.append(oid_dept)
    assert b["data"].get("applicantType") == "DEPARTMENT" and b["data"].get("applicantDepartmentId") == 77
    tl_dept = b["data"].get("timeline") or []
    print(f"  部门链={[(n['approverType'], n['approverId']) for n in tl_dept]} nodeCount={b['data'].get('nodeCount')} ccCount={b['data'].get('ccCount')}")
    assert tl_dept and tl_dept[0]["approverType"] == "ORG_ADMIN" and int(tl_dept[0]["approverId"]) == 3048
    assert int(b["data"].get("nodeCount")) == 1

    print("== D. 越权：非正职 403 / 跨机构 404 / 平台 404，且不落库 ==")
    for tag, tok in [("非本部门正职", tok_mem), ("跨机构正职", tok_oth), ("平台账号", tok_plt)]:
        st, b = req("POST", "/org/permissions/apply", tok, json={"permissionCode": "expert:manage", "reason": "越权", "applyAsDepartment": True, "departmentId": 77})
        print(f"  {tag}: HTTP {st} code={b.get('code')} msg={b.get('message')}")

    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("SELECT applicant_type, applicant_department_id FROM approval_order WHERE id IN (%s,%s)", (oid_mem, oid_dept))
        rows = cur.fetchall()
        print(f"  落库主体: {rows}")
        assert ("USER", None) in rows and ("DEPARTMENT", 77) in rows, rows
        cur.execute("SELECT COUNT(*) FROM approval_order WHERE content LIKE '%越权%' AND created_at > NOW(6) - INTERVAL 5 MINUTE")
        assert cur.fetchone()[0] == 0, "越权必须不落库"
    conn.close()

    print("== E. summary：cc 总条数 + ccUnread ==")
    _, s0 = req("GET", "/workflow/tasks/summary", tok_org)
    d0 = s0.get("data", {})
    print(f"  企业管理员 summary={d0}")
    assert d0.get("cc", 0) >= 1 and d0.get("ccUnread", 0) >= 1
    cc_total_before = int(d0.get("cc")); cc_unread_before = int(d0.get("ccUnread"))

    print("== F. scope=cc 行带 read/readAt ==")
    _, b = req("GET", "/workflow/tasks?scope=cc", tok_org)
    rows = b.get("data") or []
    row = next((r for r in rows if int(r.get("id")) == oid_mem), None)
    print(f"  命中本单={row is not None} read={row.get('read') if row else None} readAt={row.get('readAt') if row else None}")
    assert row is not None and row.get("read") is False and row.get("readAt") is None
    cc_task = int(row["taskId"])

    print("== G. 标记已读：首次 / 幂等 / 他人 404 / APPROVE 错误 ==")
    st, b1 = req("POST", f"/workflow/cc/{cc_task}/read", tok_org)
    print(f"  首次 read={b1.get('data',{}).get('read')} readAt={b1.get('data',{}).get('readAt')} ccUnread={b1.get('data',{}).get('ccUnread')}")
    assert b1.get("code") == 0 and b1["data"]["read"] is True and b1["data"]["readAt"]
    st, b2 = req("POST", f"/workflow/cc/{cc_task}/read", tok_org)
    print(f"  重复 readAt 不倒退: {b1['data']['readAt']} == {b2['data']['readAt']} -> {b1['data']['readAt']==b2['data']['readAt']}")
    assert b2["data"]["readAt"] == b1["data"]["readAt"]
    st, b3 = req("POST", f"/workflow/cc/{cc_task}/read", tok_mem)
    print(f"  他人标记: HTTP {st} code={b3.get('code')} msg={b3.get('message')}")
    assert b3.get("code") == 404
    _, btodo = req("GET", "/workflow/tasks?scope=todo", tok_ldr)
    appr_task = next((int(r["taskId"]) for r in (btodo.get("data") or []) if int(r.get("id")) == oid_mem), None)
    st, b4 = req("POST", f"/workflow/cc/{appr_task}/read", tok_ldr)
    print(f"  APPROVE 任务 taskId={appr_task}: HTTP {st} code={b4.get('code')} msg={b4.get('message')}")
    assert b4.get("code") != 0

    print("== H. 已读后 cc 不减、ccUnread 减 1 ==")
    _, s1 = req("GET", "/workflow/tasks/summary", tok_org)
    d1 = s1.get("data", {})
    print(f"  读后 summary={d1}（before cc={cc_total_before} ccUnread={cc_unread_before}）")
    assert int(d1.get("cc")) == cc_total_before, "cc 语义不得因已读减少"
    assert int(d1.get("ccUnread")) == cc_unread_before - 1, "ccUnread 应减 1"

    print("\n全部冒烟断言通过 ✅")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
