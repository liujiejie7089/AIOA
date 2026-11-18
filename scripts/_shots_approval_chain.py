# -*- coding: utf-8 -*-
"""费用报销审批全链路 UI 截图：登录 → 提交 → 回执 → 我的申请 → 管理端待办。

产物落 docs/screenshots/approval-chain-2026-11-17/，每步结果写 result.json。
"""
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import asyncio
import json
import os
import time

from playwright.async_api import async_playwright

BASE_H5 = "http://127.0.0.1:5181/"
BASE_ADMIN = "http://127.0.0.1:5173/"
SHOT_DIR = r"D:\aios\docs\screenshots\approval-chain-2026-11-17"
MARK = "UISHOT-%s" % time.strftime("%m%d%H%M%S")
os.makedirs(SHOT_DIR, exist_ok=True)
result = {"mark": MARK, "steps": [], "shots": []}


def log(name, detail):
    result["steps"].append({"step": name, "detail": detail})
    print("[STEP] %s :: %s" % (name, json.dumps(detail, ensure_ascii=False)[:400]))


async def shot(page, name):
    path = os.path.join(SHOT_DIR, name + ".png")
    await page.screenshot(path=path, full_page=False)
    result["shots"].append(path)
    print("[SHOT]", path)
    return path


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="msedge", headless=True)
        errors = []

        # ---------- A. 用户端 ----------
        c1 = await b.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
        p1 = await c1.new_page()
        p1.on("pageerror", lambda e: errors.append("H5 pageerror: " + str(e)))
        p1.on("console", lambda m: errors.append("H5 console.error: " + m.text) if m.type == "error" else None)

        await p1.goto(BASE_H5, wait_until="domcontentloaded")
        await p1.wait_for_timeout(1200)
        await shot(p1, "01-h5-login")
        log("登录页", {"title": await p1.title(), "lgBtn": await p1.locator("#lgBtn").count()})

        await p1.fill("#lgUser", "zhangsan")
        await p1.fill("#lgPass", "User@123")
        await p1.click("#lgBtn")
        await p1.wait_for_timeout(2500)
        await shot(p1, "02-h5-home")
        log("登录用户端", {"bodyClass": await p1.evaluate("() => document.body.className")})

        # 进入待办 → 我的申请（提交前）
        await p1.evaluate("() => gotoTodo()")
        await p1.wait_for_timeout(900)
        await p1.evaluate("() => switchTodoTab('mine')")
        await p1.wait_for_timeout(1500)
        before = await p1.evaluate("""() => ({
          tab: (document.querySelector('#todoTabs .todo-tab.active')||{}).textContent,
          rows: [...document.querySelectorAll('#page-todo .todo-row, #page-todo [data-appr]')].map(x=>(x.innerText||'').slice(0,80)),
          text: (document.getElementById('page-todo')||{}).innerText?.slice(0,500)
        })""")
        await shot(p1, "03-h5-mine-before")
        log("我的申请（提交前）", before)

        # 真实提交费用报销（走前端 API 封装，等价于表单卡提交）
        submitted = await p1.evaluate("""async (mark) => {
          try {
            const r = await API.formSubmit('expense_form', {
              expense_type:'TRAVEL', amount:100, occur_date:'2026-11-17',
              reason:mark+' 费用报销全链路 UI 验收', invoice:'UI-SHOT-INVOICE'
            });
            return {ok:true, resp:r};
          } catch(e) { return {ok:false, err:(e&&e.message)||String(e)}; }
        }""", MARK)
        log("提交费用报销", submitted)
        await p1.wait_for_timeout(800)

        # 提交回执：直接读接口返回并渲染一段可见文字到页面顶部供截图取证
        await p1.evaluate("""(r) => {
          let box = document.getElementById('fullchainProof');
          if(!box){ box=document.createElement('div'); box.id='fullchainProof';
            box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99999;background:#fffbe6;color:#7a5b00;padding:10px 12px;font:12px/1.5 sans-serif;border-bottom:2px solid #f0c000;';
            document.body.appendChild(box); }
          box.textContent = '提交回执：status=' + (r&&r.status) + ' | submissionId=' +
            (r&&r.submissionId) + ' | approvalOrderId=' + ((r&&r.receipt&&r.receipt.approvalOrderId)||'NONE') +
            ' | ' + (r&&r.receipt&&r.receipt.statusLabel||'');
        }""", submitted.get("resp"))
        await shot(p1, "04-h5-submit-receipt")

        # 提交后刷新我的申请
        await p1.evaluate("() => gotoTodo()")
        await p1.wait_for_timeout(700)
        await p1.evaluate("() => switchTodoTab('mine')")
        await p1.wait_for_timeout(1600)
        after = await p1.evaluate("""() => ({
          tab: (document.querySelector('#todoTabs .todo-tab.active')||{}).textContent,
          rows: [...document.querySelectorAll('#page-todo .todo-row, #page-todo [data-appr]')].map(x=>(x.innerText||'').slice(0,80)),
          text: (document.getElementById('page-todo')||{}).innerText?.slice(0,500)
        })""")
        await shot(p1, "05-h5-mine-after")
        log("我的申请（提交后）", after)
        log("我的申请是否出现本次费用报销", {
            "appeared": any(MARK in x for x in after.get("rows", [])) or MARK in (after.get("text") or ""),
            "mark": MARK,
        })

        # ---------- B. 管理端 ----------
        c2 = await b.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        p2 = await c2.new_page()
        p2.on("pageerror", lambda e: errors.append("admin pageerror: " + str(e)))
        await p2.goto(BASE_ADMIN, wait_until="domcontentloaded")
        await p2.wait_for_timeout(1500)
        login_dom = await p2.evaluate("""() => ({
          inputs:[...document.querySelectorAll('input')].map(x=>({id:x.id,ph:x.placeholder,type:x.type})),
          buttons:[...document.querySelectorAll('button')].map(x=>({txt:(x.textContent||'').trim().slice(0,20)}))
        })""")
        log("管理端登录页 DOM", login_dom)
        await shot(p2, "06-admin-login")

        # 按 LoginView.vue 顺序：ins[0]=租户名, ins[1]=用户名, ins[2]=密码
        for uname, tenant in (("dsj_admin", "默认租户"), ("dsj_admin", "某某市某某区大数据管理局")):
            done = await p2.evaluate("""([u, tenantName, p]) => {
              const ins=[...document.querySelectorAll('input')];
              if(ins.length<3) return false;
              const set=(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));};
              set(ins[0],tenantName); set(ins[1],u); set(ins[2],p);
              const btn=[...document.querySelectorAll('button')].find(x=>/登\\s*录/i.test(x.textContent||''));
              if(btn) btn.click();
              return true;
            }""", [uname, tenant, "Admin@123"])
            if done:
                await p2.wait_for_timeout(2800)
                logged = await p2.evaluate("() => location.pathname + ' | ' + document.body.innerText.slice(0,220)")
                log("管理端登录尝试 " + uname + "@" + tenant, {"done": done, "state": logged})
                if "login" not in (logged or "").lower():
                    break
        await shot(p2, "07-admin-home")
        admin_menu = await p2.evaluate("""() => ({
          links:[...document.querySelectorAll('a')].map(a=>({href:a.getAttribute('href'),txt:(a.textContent||'').trim().slice(0,20)})).filter(x=>x.txt),
          text:document.body.innerText.slice(0,900)
        })""")
        log("管理端菜单", admin_menu)

        # 导航到待审批（从菜单里挑审批相关路由，兜底常见路由）
        routes = [x["href"] for x in admin_menu["links"]
                  if x.get("href") and any(k in (x["txt"] + x["href"]) for k in ("审批", "workflow", "approval"))]
        routes += ["/workflow/tasks", "/approval", "/approvals", "/workflow"]
        for route in dict.fromkeys(routes):
            if not route.startswith("/"):
                continue
            await p2.goto("http://127.0.0.1:5173" + route, wait_until="domcontentloaded")
            await p2.wait_for_timeout(1300)
            txt = await p2.evaluate("() => document.body.innerText.slice(0,400)")
            if "待" in txt or "审批" in txt:
                log("管理端审批页 " + route, {"text": txt})
                await shot(p2, "08-admin-todo")
                break
        log("管理端是否看到本次申请", {"appeared": MARK in (await p2.evaluate("() => document.body.innerText"))})

        result["errors"] = errors
        await b.close()

    with open(os.path.join(SHOT_DIR, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\nDONE. shots=%d errors=%d" % (len(result["shots"]), len(errors)))


asyncio.run(main())
