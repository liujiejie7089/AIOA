# -*- coding: utf-8 -*-
"""审批意见弹层（批次一 A-1）截图。"""
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


def shot(page, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".png")
    page.locator(".phone").screenshot(path=p)
    print("  [shot] " + p, flush=True)


def main():
    at, au = login("admin", "Admin@123")
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 460, "height": 920}, device_scale_factor=2, locale="zh-CN")
        ctx.add_init_script("try{localStorage.setItem('aioa_session', %s);}catch(e){}"
                            % json.dumps(json.dumps({"token": at, "user": au})))
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_selector(".phone", timeout=15000)
        page.wait_for_function("() => document.body.classList.contains('auth')", timeout=15000)
        page.wait_for_timeout(2800)
        page.evaluate("()=>switchTabById('page-todo')")
        page.wait_for_timeout(1500)

        first = page.evaluate("""()=>{
            const items=[...document.querySelectorAll('#page-todo .todo-item')];
            const t=items.find(i=>/待审批/.test(i.innerText||''));
            if(t){ t.scrollIntoView({block:'center'}); t.click(); return t.innerText.replace(/\\n/g,' | '); }
            return null;
        }""")
        print("  点击待审批行:", first, flush=True)
        page.wait_for_timeout(1500)
        shot(page, "08-approval-detail")
        btns = page.evaluate("""()=>[...document.querySelectorAll('button,.btn')]
            .filter(b=>b.offsetParent && /同意|不同意|驳回|审批/.test(b.innerText||''))
            .map(b=>b.innerText.trim())""")
        print("  可见审批按钮:", btns, flush=True)
        clicked = page.evaluate("""()=>{
            const bs=[...document.querySelectorAll('button,.btn')]
              .filter(b=>b.offsetParent && /不同意|驳回/.test(b.innerText||''));
            if(bs[0]){ bs[0].click(); return bs[0].innerText.trim(); } return null;
        }""")
        print("  点击:", clicked, flush=True)
        page.wait_for_timeout(1200)
        cnt = page.locator(".notif-modal").count()
        print("  .notif-modal 数量:", cnt, flush=True)
        shot(page, "09-approval-note-modal")
        modal_txt = ""
        if cnt:
            modal_txt = page.locator(".notif-modal").first.inner_text().replace("\n", " | ")
        print("  弹层文本:", modal_txt[:300], flush=True)
        ctx.close(); b.close()
    print("完成", flush=True)


main()
