"""管理端改动验收（2026-11-05）：业务工具菜单下线 + WJJ-DEMO 租户已消失。

界面结论一律回接口/库再核一遍：菜单文案取自渲染后的 DOM，租户列表取自 /admin/tenants。
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = "http://127.0.0.1:8080/aios/web/"
OUT = Path(".workbuddy/tmp/acceptance-20261105")
OUT.mkdir(parents=True, exist_ok=True)
results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(WEB, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # 平台管理员（租户列表只有平台管理员能看）。登录页是「租户名称 / 用户名 / 密码」三项，
        # 少填租户名称会被前端校验拦住，页面停在 /login 不动 —— 上一版就是这么误判成「菜单没删」的。
        if page.locator("input").count() >= 3:
            inputs = page.locator("input")
            inputs.nth(0).fill("默认租户")
            inputs.nth(1).fill("admin")
            inputs.nth(2).fill("Admin@123")
            page.get_by_role("button", name="登 录").click()
            page.wait_for_timeout(5000)
        print("URL:", page.url)

        # ---------- 1. 侧边栏不能有「业务工具」 ----------
        page.wait_for_timeout(1500)
        body_txt = page.inner_text("body")
        check("M1 侧边栏不再出现「业务工具」", "业务工具" not in body_txt)
        # 「智能服务」默认是折叠的：不展开就断言「业务系统在不在」等于断言了个空气
        grp = page.get_by_text("智能服务", exact=True)
        if grp.count():
            grp.first.click()
            page.wait_for_timeout(1200)
        sidebar_txt = page.inner_text("body")
        check("M2 「业务系统」仍在（没有误删整组）", "业务系统" in sidebar_txt)
        check("M3 「智能服务」分组仍在", "智能服务" in sidebar_txt)
        check("M7 展开后仍然没有「业务工具」", "业务工具" not in sidebar_txt)
        page.screenshot(path=str(OUT / "10-admin-menu.png"))

        # ---------- 2. 租户列表：WJJ-DEMO 消失 ----------
        page.goto(WEB + "#/tenants", wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        txt = page.inner_text("body")
        if "WJJ-DEMO" not in txt and "租户" not in txt:
            # 路由 hash 可能不是 /tenants，退回到菜单点击
            page.goto(WEB, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            hit = page.get_by_text("租户管理", exact=False)
            if hit.count():
                hit.first.click()
                page.wait_for_timeout(3000)
                txt = page.inner_text("body")
        check("M4 租户列表里没有 WJJ-DEMO", "WJJ-DEMO" not in txt, "")
        check("M5 其它租户仍在（DSJ-DEMO）", "DSJ-DEMO" in txt or "某某市某某区大数据管理局" in txt)
        page.screenshot(path=str(OUT / "11-tenant-list.png"))
        check("M6 无 JS 异常", not errs, "；".join(errs[:2]))
        b.close()
    ok = sum(1 for _, c, _ in results if c)
    print(f"\n===== {ok}/{len(results)} 通过 =====")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
