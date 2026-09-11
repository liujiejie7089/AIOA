# -*- coding: utf-8 -*-
"""用户端 H5 (localhost:5181) 公开页面体验走查：截图 + 关键文本提取。
重点：数字员工与审批相关页面。两角色：zhangsan(普通成员) / admin(租户管理员)。
"""
import json, os, sys, time, urllib.request as u
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5181"
# 输出目录可用 WALKTHROUGH_OUT 指定，便于「改进前 / 改进后」分别留档而不互相覆盖
OUT = os.environ.get("WALKTHROUGH_OUT") or os.path.dirname(os.path.abspath(__file__))
LOG = []


def log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def api(path, method="GET", token=None, body=None):
    req = u.Request(BASE + "/api/v1" + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    with u.urlopen(req, data=data, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def login(username, password):
    d = api("/auth/login", "POST", body={"username": username, "password": password})
    d = d.get("data") or {}
    return d.get("accessToken"), d.get("user") or {}


def sess_script(token, user):
    payload = json.dumps({"token": token, "user": user})
    return "try{localStorage.setItem('aioa_session', %s);}catch(e){}" % json.dumps(payload)


def shot(page, name):
    p = os.path.join(OUT, name + ".png")
    try:
        page.locator(".phone").screenshot(path=p)
        log("  [shot] " + name + ".png")
        return p
    except Exception as e:
        log("  [shot-FAIL] %s: %s" % (name, e))
        return None


def wait_home(page):
    page.wait_for_selector(".phone", timeout=15000)
    page.wait_for_function(
        "() => document.body.classList.contains('auth')", timeout=15000)


def go_tab(page, pid):
    page.evaluate("(p)=>switchTabById(p)", pid)
    page.wait_for_selector("#%s.active" % pid, timeout=8000)
    page.wait_for_timeout(700)


def text_of(page, sel):
    try:
        return page.locator(sel).inner_text(timeout=4000).strip()
    except Exception:
        return ""


def run_persona(pw, label, token, user, is_admin):
    log("\n===== 角色: %s (%s) =====" % (label, "管理员" if is_admin else "普通成员"))
    b = pw.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 460, "height": 920}, device_scale_factor=2,
                        locale="zh-CN")
    ctx.add_init_script(sess_script(token, user))
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded")
    wait_home(page)
    page.wait_for_timeout(2500)   # 等 loadLiveData 完成

    # 1) 工作台
    go_tab(page, "page-home")
    page.wait_for_timeout(1200)
    shot(page, "%s-01-home" % label)
    log("  工作台正文片段: " + text_of(page, "#page-home")[:160].replace("\n", " | "))

    # 2) 待办（三标签）
    go_tab(page, "page-todo")
    page.wait_for_timeout(1200)
    shot(page, "%s-02-todo-pending" % label)
    for tb in ("pending", "done", "mine"):
        try:
            page.evaluate("(n)=>switchTodoTab(n)", tb)
            page.wait_for_timeout(900)
            shot(page, "%s-03-todo-%s" % (label, tb))
            t = text_of(page, ".todo-panel[data-panel='%s']" % tb)
            log("  待办[%s] 文本: %s" % (tb, (t[:200] or "(空)").replace("\n", " | ")))
        except Exception as e:
            log("  待办[%s] 切换失败: %s" % (tb, e))

    # 3) 专家与员工
    go_tab(page, "page-agent")
    page.wait_for_timeout(1500)
    shot(page, "%s-04-agent-workers" % label)
    log("  员工页主体: " + text_of(page, "#page-agent")[:220].replace("\n", " | "))
    log("  agentActions 可见: %s | agentAdminHint 可见: %s | expertList 可见: %s" % (
        page.locator("#agentActions").is_visible(),
        page.locator("#agentAdminHint").is_visible(),
        page.locator("#expertList").is_visible(),
    ))
    # 员工卡片滚动截图
    page.evaluate("()=>{const p=document.querySelector('#page-agent'); p.scrollTop=430;}")
    page.wait_for_timeout(600)
    shot(page, "%s-05-agent-cards" % label)
    # 专家服务标签
    try:
        page.evaluate("()=>switchAgentTab('experts')")
        page.wait_for_timeout(900)
        shot(page, "%s-06-agent-experts" % label)
    except Exception as e:
        log("  专家标签失败: %s" % e)

    # 4) 数字员工会话（请假助手）
    page.evaluate("()=>switchAgentTab('workers')")
    page.wait_for_timeout(500)
    idx = page.evaluate("""()=>{
        const ws = (typeof state!=='undefined' && state.workers) || [];
        return ws.findIndex(w => (w.name||'').indexOf('请假') >= 0);
    }""")
    log("  请假数字员工索引: %s" % idx)
    if idx is not None and idx >= 0:
        page.evaluate("(i)=>useAgent(i)", idx)
        page.wait_for_timeout(1200)
        shot(page, "%s-07-chat-open" % label)
        log("  会话头: %s" % text_of(page, ".chat-head").replace("\n", " | "))
        # 发一句请假请求
        page.fill("#chatInput", "我要请假两天，怎么申请？")
        page.click("#sendBtn")
        try:
            page.wait_for_function(
                "()=>!state.busy && document.querySelectorAll('#msgs .msg').length>=2",
                timeout=90000)
        except Exception as e:
            log("  等待回答超时: %s" % e)
        page.wait_for_timeout(2500)
        shot(page, "%s-08-chat-answer" % label)
        log("  回答正文: " + text_of(page, "#msgs")[-320:].replace("\n", " | "))
        has_form = page.locator("#leaveForm").count() > 0
        log("  出现请假表单: %s" % has_form)
        if has_form:
            page.locator("#leaveForm").scroll_into_view_if_needed()
            page.wait_for_timeout(400)
            shot(page, "%s-09-leave-form" % label)
            # 填好
            page.select_option("#lfType", "年假")
            page.fill("#lfStart", "2026-09-15")
            page.fill("#lfEnd", "2026-09-16")
            page.fill("#lfReason", "家庭事务，需请假两天")
            page.wait_for_timeout(400)
            shot(page, "%s-10-leave-filled" % label)

    # 5) 我的
    go_tab(page, "page-me")
    page.wait_for_timeout(1200)
    shot(page, "%s-11-me" % label)
    log("  我的页: " + text_of(page, "#page-me")[:200].replace("\n", " | "))

    ctx.close()
    b.close()


def main():
    zt, zu = login("zhangsan", "User@123")
    at, au = login("admin", "Admin@123")
    log("token zhangsan=%s admin=%s" % (bool(zt), bool(at)))
    with sync_playwright() as pw:
        run_persona(pw, "zh", zt, zu, False)
        run_persona(pw, "ad", at, au, True)
    with open(os.path.join(OUT, "walkthrough.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    log("\n完成，截图见 %s" % OUT)


main()
