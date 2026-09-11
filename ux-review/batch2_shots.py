# -*- coding: utf-8 -*-
"""批次二改进效果截图（localhost:5181）。"""
import json, os, urllib.request as u
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5181"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch2")


def api(path, method="GET", token=None, body=None):
    req = u.Request(BASE + "/api/v1" + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    with u.urlopen(req, data=data, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def login(u_, p_):
    d = api("/auth/login", "POST", body={"username": u_, "password": p_}).get("data") or {}
    return d.get("accessToken"), d.get("user") or {}


def sess(tok, user):
    return "try{localStorage.setItem('aioa_session', %s);}catch(e){}" % json.dumps(
        json.dumps({"token": tok, "user": user}))


def shot(page, name):
    os.makedirs(OUT, exist_ok=True)
    page.locator(".phone").screenshot(path=os.path.join(OUT, name + ".png"))
    print("  [shot] " + name, flush=True)


def main():
    zt, zu = login("zhangsan", "User@123")
    at, au = login("admin", "Admin@123")
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)

        # 管理员：待办列表（类型图标着色 + 关键字段）
        ctx = b.new_context(viewport={"width": 460, "height": 920}, device_scale_factor=2, locale="zh-CN")
        ctx.add_init_script(sess(at, au))
        pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector(".phone", timeout=15000)
        pg.wait_for_function("() => document.body.classList.contains('auth')", timeout=15000)
        pg.wait_for_timeout(2800)
        pg.evaluate("()=>switchTabById('page-todo')")
        pg.wait_for_timeout(1500)
        shot(pg, "01-admin-todo-typed-icons")
        ctx.close()

        # 普通成员：我的申请 / 查看全部 / 表单校验 / 结果卡
        ctx2 = b.new_context(viewport={"width": 460, "height": 920}, device_scale_factor=2, locale="zh-CN")
        ctx2.add_init_script(sess(zt, zu))
        p2 = ctx2.new_page()
        p2.goto(BASE + "/", wait_until="domcontentloaded")
        p2.wait_for_selector(".phone", timeout=15000)
        p2.wait_for_function("() => document.body.classList.contains('auth')", timeout=15000)
        p2.wait_for_timeout(2800)
        p2.evaluate("()=>switchTabById('page-todo')")
        p2.wait_for_timeout(700)
        p2.evaluate("(n)=>switchTodoTab(n)", "mine")
        p2.wait_for_timeout(1000)
        shot(p2, "02-user-mine-with-viewall")
        p2.evaluate("()=>document.querySelector('#page-todo .mine-more').click()")
        p2.wait_for_timeout(1000)
        shot(p2, "03-user-all-mine-modal")
        p2.evaluate("()=>{const m=document.querySelector('[data-all-close]'); if(m) m.click();}")
        p2.wait_for_timeout(500)

        # 表单校验：结束早于开始
        p2.evaluate("()=>openLeaveFlow()")
        p2.wait_for_timeout(900)
        p2.select_option("#lfType", "年假")
        p2.fill("#lfStart", "2026-11-10")
        p2.fill("#lfEnd", "2026-11-08")
        p2.fill("#lfReason", "截图用：非法区间")
        p2.evaluate("()=>{const b=[...document.querySelectorAll('#leaveForm button')].find(x=>/提交请假申请/.test(x.innerText)); if(b) b.click();}")
        p2.wait_for_timeout(1000)
        shot(p2, "04-leave-inline-validation")

        # 合法提交 → 结果卡
        p2.fill("#lfStart", "2026-11-10")
        p2.fill("#lfEnd", "2026-11-11")
        p2.fill("#lfReason", "截图用：合法区间提交")
        p2.evaluate("()=>{const b=[...document.querySelectorAll('#leaveForm button')].find(x=>/提交请假申请/.test(x.innerText)); if(b) b.click();}")
        try:
            p2.wait_for_selector(".result-card", timeout=25000)
        except Exception as e:
            print("  等待结果卡:", e, flush=True)
        p2.wait_for_timeout(900)
        p2.evaluate("()=>{const b=document.querySelector('#msgs'); if(b) b.scrollTop=b.scrollHeight;}")
        p2.wait_for_timeout(400)
        shot(p2, "05-leave-result-card")
        ctx2.close()
        b.close()
    print("完成 ->", OUT, flush=True)


main()
