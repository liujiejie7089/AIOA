# -*- coding: utf-8 -*-
"""V39 · 管理端「审批中心」菜单红点渲染校验（无头 Edge）。

需求原文：「管理端存在未处理申请时，菜单右上角需显示小红点提醒」。
关键点不只是「有红点」，而是**只在该轮到我处理时**才亮 —— 一条多级单据
不能同时点亮链条上所有审批人，否则红点等于噪音。

断言路径（tenant 9 真实账号）：
  A. 普通成员提交权限申请 → 部门负责人（当前节点）红点 = 1
  B. 企业管理员 / 租户管理员 / 平台管理员（尚未轮到）→ **无红点**
  C. 部门负责人通过 → **一级即终审**（V42 起 PERMISSION_GRANT 为 `levels=1`）。
     机构管理员**不再进入审批链**，而是收到**知会（抄送）**：
     红点仍不亮（知会不进待办），但 `summary.cc ≥ 1` 且 `scope=cc` 可见本单。
  D. 知会任务**不可审批**（决策被拒）；终审后全链待办计数回落为 0。
  E. 无任何审批待办的普通成员 → 无红点

前置：后端 :8080、管理端 shell :5173 已启动。
"""
import json
import sys

import httpx
import pymysql
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"

BADGE = '[title$="条待你处理"]'

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", autocommit=True)
TEST_UIDS = (3145, 3144, 3143)

C = httpx.Client(timeout=60, trust_env=False)
results = []


def reset():
    """清理 tenant 9 测试账号的 PERMISSION_GRANT 残留，保证可重复运行。"""
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM approval_order WHERE tenant_id=9 AND deleted_at IS NULL "
                "AND biz_type='PERMISSION_GRANT' AND user_id IN %s", (TEST_UIDS,))
            oids = [r[0] for r in cur.fetchall()]
            if oids:
                cur.execute("DELETE FROM approval_task WHERE order_id IN %s", (oids,))
                cur.execute("DELETE FROM notification WHERE ref_id IN %s", (oids,))
                cur.execute("DELETE FROM approval_order WHERE id IN %s", (oids,))
            cur.execute("DELETE FROM permission_grant WHERE tenant_id=9 AND user_id IN %s",
                        (TEST_UIDS,))
        conn.commit()
        print(f"[reset] 清理审批单 {len(oids)} 张、授权单 {cur.rowcount} 条\n")
    finally:
        conn.close()


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def login(name, pwd="User@123"):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"].get("user") or {}


def req(method, path, tok, **kw):
    r = C.request(method, API + path, headers={"Authorization": f"Bearer {tok}"}, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"code": -1}


def badge(page):
    """返回 (是否存在, 文案)。"""
    el = page.query_selector(BADGE)
    return (el is not None), (el.inner_text().strip() if el else "")


def open_shell(pw, b, tok, user, path="/approvals"):
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s); localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(json.dumps(user, ensure_ascii=False)))
    )
    page = ctx.new_page()
    page.goto(SHELL + path, wait_until="networkidle")
    page.wait_for_timeout(3000)
    return page


def main():
    reset()

    # ---------- 造一单停在「部门负责人」的权限申请 ----------
    member = login("znsfb_m01")
    dept = login("znsfb_ldr")
    org = login("znkjyf_admin")
    ten = login("znkj_admin")
    plat = login("admin", "Admin@123")

    st, b = req("POST", "/org/permissions/apply", member[0],
                json={"permissionCode": "worker:manage", "reason": "V39 红点渲染校验"})
    if b.get("code") != 0:
        raise SystemExit(f"造单失败：{b.get('message')}")
    order_id = int(b["data"]["orderId"])
    print(f"[prep] 权限申请 orderId={order_id}，当前节点 = 部门负责人\n")

    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)

        # ---------- A / B：当前节点亮，其余不亮 ----------
        cases = [
            ("A 部门负责人（当前节点）", dept, True),
            ("B 企业管理员（未轮到）", org, False),
            ("B 租户管理员（未轮到）", ten, False),
            ("B 平台管理员（未轮到）", plat, False),
            ("E 普通成员（无审批待办）", member, False),
        ]
        for tag, acc, expect_badge in cases:
            page = open_shell(pw, br, acc[0], acc[1])
            exists, text = badge(page)
            if expect_badge:
                check(f"{tag} → 菜单右上角出现红点", exists and text.isdigit() and int(text) >= 1,
                      f"exists={exists} text={text!r}")
            else:
                check(f"{tag} → 不被点亮（无红点）", not exists, f"exists={exists} text={text!r}")
            page.context.close()

        # ---------- C：部门负责人通过 → 一级即终审；机构管理员仅收「知会」 ----------
        st, b = req("GET", "/workflow/tasks?scope=todo", dept[0])
        task = next((r for r in (b.get("data") or []) if int(r.get("id")) == order_id), None)
        if not check("C 部门负责人待办里取到本单", task is not None):
            sys.exit(1)
        st, b = req("POST", f"/workflow/tasks/{task['taskId']}/decide", dept[0],
                    json={"decision": "APPROVE", "note": "红点校验·通过"})
        check("C 部门负责人通过成功", b.get("code") == 0, f"code={b.get('code')}")
        check("C ★一级即终审（V42 levels=1，不再流转到企业管理员）",
              (b.get("data") or {}).get("finalDone") is True,
              f"finalDone={(b.get('data') or {}).get('finalDone')}")

        # 机构管理员不进待办，但必须收到知会（分账，不阻塞流转）
        st2, b2 = req("GET", "/workflow/tasks/summary", org[0])
        d2 = b2.get("data") or {}
        check("C 企业管理员待办计数为 0（已非审批节点）", d2.get("todo") == 0, f"todo={d2.get('todo')}")
        check("C ★企业管理员「抄送我的」≥ 1（知会到位）",
              (d2.get("cc") or 0) >= 1, f"cc={d2.get('cc')}")

        page = open_shell(pw, br, org[0], org[1])
        exists, text = badge(page)
        check("C ★企业管理员（知会）→ 菜单待办红点不亮", not exists, f"exists={exists} text={text!r}")
        page.context.close()

        page = open_shell(pw, br, dept[0], dept[1])
        exists, _ = badge(page)
        check("C 部门负责人（已处理完）→ 红点回落", not exists)
        page.context.close()

        # ---------- D：知会不可审批；终审后全链无人被点亮 ----------
        st, b = req("GET", "/workflow/tasks?scope=cc", org[0])
        cc_rows = b.get("data") or []
        cc_row = next((r for r in cc_rows if int(r.get("id")) == order_id), None)
        check("D ★企业管理员「抄送我的」取到本单（知会可见、可督办）", cc_row is not None,
              f"n={len(cc_rows)}")
        if cc_row is not None:
            st, b = req("POST", f"/workflow/tasks/{cc_row['taskId']}/decide", org[0],
                        json={"decision": "APPROVE", "note": "知会不应可审批"})
            check("D ★知会任务不可审批（决策被拒）", b.get("code") != 0,
                  f"code={b.get('code')} msg={b.get('message')}")

        for tag, acc in (("D 企业管理员", org), ("D 租户管理员", ten), ("D 平台管理员", plat)):
            st2, b2 = req("GET", "/workflow/tasks/summary", acc[0])
            d2 = b2.get("data") or {}
            n = d2.get("todo") if b2.get("code") == 0 else None
            check(f"{tag} → 终审后待办计数为 0", n == 0, f"todo={n}")

        br.close()

    reset()
    passed = sum(1 for _, c, _ in results if c)
    print("\n" + "=" * 62)
    print(f"V39 管理端待办红点渲染校验：{passed}/{len(results)} 通过")
    if passed != len(results):
        for t, c, d in results:
            if not c:
                print(f"  - {t}  {d}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
