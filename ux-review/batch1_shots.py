# -*- coding: utf-8 -*-
"""批次一改进效果截图（localhost:5181）。
聚焦本次改动：数字员工产出两态 / 运行模式徽标 / 待办口径 / 审批意见弹层。
"""
import json, os, urllib.request as u
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5181"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch1")


def api(path, method="GET", token=None, body=None):
    req = u.Request(BASE + "/api/v1" + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    with u.urlopen(req, data=data, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def login(username, password):
    d = api("/auth/login", "POST", body={"username": username, "password": password}).get("data") or {}
    return d.get("accessToken"), d.get("user") or {}


def sess_script(token, user):
    payload = json.dumps({"token": token, "user": user})
    return "try{localStorage.setItem('aioa_session', %s);}catch(e){}" % json.dumps(payload)


def shot(page, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".png")
    page.locator(".phone").screenshot(path=p)
    print("  [shot] " + p, flush=True)
    return p


def open_page(pw, token, user):
    b = pw.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 460, "height": 920}, device_scale_factor=2, locale="zh-CN")
    ctx.add_init_script(sess_script(token, user))
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_selector(".phone", timeout=15000)
    page.wait_for_function("() => document.body.classList.contains('auth')", timeout=15000)
    page.wait_for_timeout(2800)
    return b, ctx, page


def main():
    at, au = login("admin", "Admin@123")
    zt, zu = login("zhangsan", "User@123")
    print("token admin=%s zhangsan=%s" % (bool(at), bool(zt)), flush=True)
    with sync_playwright() as pw:
        # ---- 管理员视角：数字员工卡片 ----
        b, ctx, page = open_page(pw, at, au)
        page.evaluate("()=>switchTabById('page-agent')")
        page.wait_for_timeout(1800)
        shot(page, "01-admin-agent-workers-top")
        page.evaluate("()=>{const p=document.querySelector('#page-agent'); p.scrollTop=560;}")
        page.wait_for_timeout(700)
        shot(page, "02-admin-agent-cards")
        # ---- 管理员：待办 ----
        page.evaluate("()=>switchTabById('page-todo')")
        page.wait_for_timeout(1400)
        shot(page, "03-admin-todo-pending")
        # ---- 管理员：审批意见弹层 ----
        clicked = page.evaluate("""()=>{
            const btns=[...document.querySelectorAll('#todoPanelPending button, .todo-panel[data-panel=pending] button')];
            const t=btns.find(b=>/审批|同意|处理|查看|去处理/.test(b.innerText||''));
            if(t){t.click();return t.innerText.trim();} return null;
        }""")
        print("  审批入口点击:", clicked, flush=True)
        page.wait_for_timeout(1200)
        shot(page, "04-admin-todo-after-click")
        try:
            note_btns = page.evaluate("""()=>{
                const bs=[...document.querySelectorAll('button')].filter(b=>/不同意|驳回|同意/.test(b.innerText||'') && b.offsetParent);
                return bs.map(b=>b.innerText.trim());
            }""")
            print("  可见决定按钮:", note_btns, flush=True)
            page.evaluate("""()=>{
                const bs=[...document.querySelectorAll('button')].filter(b=>/不同意|驳回/.test(b.innerText||'') && b.offsetParent);
                if(bs[0]) bs[0].click();
            }""")
            page.wait_for_timeout(1000)
            modal = page.locator(".notif-modal").count()
            print("  意见弹层 .notif-modal 数量:", modal, flush=True)
            shot(page, "05-admin-approval-note-modal")
        except Exception as e:
            print("  弹层探测失败:", e, flush=True)
        ctx.close(); b.close()

        # ---- 普通成员视角：待办 ----
        b, ctx, page = open_page(pw, zt, zu)
        page.evaluate("()=>switchTabById('page-todo')")
        page.wait_for_timeout(1500)
        shot(page, "06-user-todo-pending")
        labels = page.evaluate("""()=>{
            const s=[...document.querySelectorAll('.todo-tabs button,.todo-tab')].map(b=>b.innerText.trim());
            const bd=[...document.querySelectorAll('.badge')].map(b=>b.innerText.trim());
            return {tabs:s, badges:bd.slice(0,12)};
        }""")
        print("  成员侧标签/徽标:", labels, flush=True)
        page.evaluate("(n)=>switchTodoTab(n)", "done")
        page.wait_for_timeout(1000)
        shot(page, "07-user-todo-done")
        ctx.close(); b.close()
    print("完成，截图目录:", OUT, flush=True)


main()
