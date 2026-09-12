# -*- coding: utf-8 -*-
"""V34 管理端「内容审核」页渲染校验（无头 Edge）。

用 localStorage 注入会话免登录；页面必须在待审状态下渲染出表格，且未通过审核时不显示操作按钮。
"""
import json
import sys

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"

results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))


def main():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()
    if d.get("code") != 0:
        raise SystemExit("登录失败：" + str(d.get("message")))
    tok = d["data"]["accessToken"]
    me = d["data"].get("user") or d["data"]

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            "localStorage.setItem('aioa.token', %s); localStorage.setItem('aioa.user', %s);"
            % (json.dumps(tok), json.dumps(json.dumps(me, ensure_ascii=False)))
        )
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(SHELL + "/content-reviews", wait_until="networkidle")
        page.wait_for_timeout(3500)

        body = page.inner_text("body")
        check("菜单出现「内容审核」", "内容审核" in body)
        check("页面标题渲染", "租户管理员创建的数字员工 / 专家需经平台管理员审核" in body)
        check("审核开关状态可见", "审核开关" in body)
        check("无 JS 运行时异常", len(errs) == 0, "; ".join(errs[:3]))

        # 待审清单（若无待审项，应渲染空态而不是报错）
        has_table = page.query_selector("table") is not None
        has_empty = "暂无" in body
        check("待审清单渲染（表格或空态）", has_table or has_empty,
              f"table={has_table} empty={has_empty}")

        # 造一条待审，验证「通过 / 驳回」按钮真的出现且可用
        ta = c.post(f"{API}/auth/login", json={"username": "jyj_admin", "password": "User@123"}).json()
        ht = {"Authorization": "Bearer " + ta["data"]["accessToken"]}
        w = c.post(f"{API}/workers", headers=ht,
                   json={"name": "V34审核台渲染校验", "icon": "bot", "description": "渲染校验用",
                         "runMode": "ON_DEMAND", "taskPrompt": "x"}).json()
        wid = (w.get("data") or {}).get("id")
        c.get(f"{API}/admin/content-reviews?status=PENDING",
              headers={"Authorization": "Bearer " + tok})   # 触发一次刷新（无关断言）

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)
        body2 = page.inner_text("body")
        check("待审内容出现在审核台", "V34审核台渲染校验" in body2)
        check("待审行显示「通过 / 驳回」操作", "通过" in body2 and "驳回" in body2)

        if wid:
            c.post(f"{API}/admin/content-reviews/worker/{wid}/review",
                   headers={"Authorization": "Bearer " + tok}, json={"approve": True})
            c.delete(f"{API}/workers/{wid}", headers=ht)

        page.screenshot(path="scripts/_v34_content_reviews.png")

        # 非平台管理员应看到无权提示
        ctx2 = b.new_context(viewport={"width": 1440, "height": 900})
        d2 = c.post(f"{API}/auth/login", json={"username": "jyj_admin", "password": "User@123"}).json()
        me2 = d2["data"].get("user") or d2["data"]
        ctx2.add_init_script(
            "localStorage.setItem('aioa.token', %s); localStorage.setItem('aioa.user', %s);"
            % (json.dumps(d2["data"]["accessToken"]), json.dumps(json.dumps(me2, ensure_ascii=False)))
        )
        p2 = ctx2.new_page()
        p2.goto(SHELL + "/content-reviews", wait_until="networkidle")
        p2.wait_for_timeout(2500)
        b2 = p2.inner_text("body")
        # 路由守卫应把租户管理员弹回首页
        check("租户管理员被路由守卫挡在审核台之外",
              "内容审核" not in b2 or "仅平台管理员" in b2, f"url={p2.url}")
        b.close()

    n = len(results)
    bad = [r for r in results if not r[1]]
    print(f"\n==== 结果：{n - len(bad)}/{n} 通过 ====")
    for t, _, d in bad:
        print(f"  FAIL  {t}  {d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
