# -*- coding: utf-8 -*-
"""批次三改进效果截图（localhost:5181）。"""
import json, os, urllib.request as u
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5181"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch3")


def login(u_, p_):
    req = u.Request(BASE + "/api/v1/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    with u.urlopen(req, data=json.dumps({"username": u_, "password": p_}).encode(), timeout=20) as r:
        d = (json.loads(r.read().decode() or "{}").get("data") or {})
    return d.get("accessToken"), d.get("user") or {}


def sess(t, usr):
    return "try{localStorage.setItem('aioa_session', %s);}catch(e){}" % json.dumps(
        json.dumps({"token": t, "user": usr}))


def shot(page, name):
    os.makedirs(OUT, exist_ok=True)
    page.locator(".phone").screenshot(path=os.path.join(OUT, name + ".png"))
    print("  [shot] " + name, flush=True)


def open_page(pw, tok, usr):
    b = pw.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 460, "height": 920}, device_scale_factor=2, locale="zh-CN")
    ctx.add_init_script(sess(tok, usr))
    p = ctx.new_page()
    p.goto(BASE + "/", wait_until="domcontentloaded")
    p.wait_for_selector(".phone", timeout=15000)
    p.wait_for_function("() => document.body.classList.contains('auth')", timeout=15000)
    p.wait_for_timeout(2800)
    return b, ctx, p


def main():
    at, au = login("admin", "Admin@123")
    zt, zu = login("zhangsan", "User@123")
    with sync_playwright() as pw:
        # 管理员：员工卡片 + 溢出菜单 + 专家页
        b, ctx, p = open_page(pw, at, au)
        p.evaluate("()=>switchTabById('page-agent')")
        p.wait_for_timeout(1600)
        shot(p, "01-admin-agents-clean")
        p.evaluate("""()=>{
            const c=document.querySelector('#agentList .agent-card');
            const btn=[...c.querySelectorAll('.agent-ops > button')].find(x=>/⋯/.test(x.innerText));
            if(btn) btn.click();
        }""")
        p.wait_for_timeout(700)
        shot(p, "02-admin-agent-menu")
        p.evaluate("()=>document.querySelectorAll('.agent-menu.show').forEach(m=>m.classList.remove('show'))")
        p.evaluate("""()=>{
            const el=document.querySelector('#agentList .agent-card .out-clamp');
            if(el) el.classList.add('open');
            const btn=document.querySelector('#agentList .agent-card .out-toggle');
            if(btn) btn.textContent='收起';
        }""")
        p.wait_for_timeout(500)
        shot(p, "03-admin-output-expanded")
        p.evaluate("()=>switchAgentTab('experts')")
        p.wait_for_timeout(1200)
        shot(p, "04-admin-experts-instantiated")
        ctx.close(); b.close()

        # 普通成员：会话头 + 知识库 chip + 请假表单排版 + 相对时间
        b, ctx, p = open_page(pw, zt, zu)
        p.evaluate("()=>switchTabById('page-agent')")
        p.wait_for_timeout(1300)
        idx = p.evaluate("()=> (state.workers||[]).findIndex(w=>(w.name||'').indexOf('请假')>=0)")
        p.evaluate("(i)=>useAgent(i)", idx)
        p.wait_for_timeout(1300)
        shot(p, "05-user-chat-head-no-kb")
        p.evaluate("()=>openLeaveFlow()")
        p.wait_for_timeout(1000)
        p.evaluate("()=>{const f=document.querySelector('#leaveForm'); if(f) f.scrollIntoView({block:'center'});}")
        p.wait_for_timeout(500)
        shot(p, "06-user-leave-form-layout")
        p.evaluate("()=>switchTabById('page-todo')")
        p.wait_for_timeout(1400)
        shot(p, "07-user-todo-relative-time")
        ctx.close(); b.close()
    print("完成 ->", OUT, flush=True)


main()
