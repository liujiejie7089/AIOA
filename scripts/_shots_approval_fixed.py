# -*- coding: utf-8 -*-
"""方案 C 修复后 UI 截图：我的申请出现费用报销审批单 + 历史台账留痕行 + 管理端待办。"""
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import asyncio
import json
import os
from playwright.async_api import async_playwright

SHOT = r"D:\aios\docs\screenshots\approval-chain-2026-11-17"
MARK = "FIXC-1117204449"
out = {"mark": MARK}


async def shot(p, name):
    await p.screenshot(path=os.path.join(SHOT, name + ".png"), full_page=False)
    print("[SHOT]", name)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="msedge", headless=True)

        # 用户端：我的申请
        c1 = await b.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
        p1 = await c1.new_page()
        await p1.goto("http://127.0.0.1:5181/", wait_until="domcontentloaded")
        await p1.wait_for_timeout(1000)
        await p1.fill("#lgUser", "zhangsan")
        await p1.fill("#lgPass", "User@123")
        await p1.click("#lgBtn")
        await p1.wait_for_timeout(2200)
        await p1.evaluate("() => gotoTodo()")
        await p1.wait_for_timeout(700)
        await p1.evaluate("() => switchTodoTab('mine')")
        await p1.wait_for_timeout(1600)
        mine = await p1.evaluate("""() => ({
          rows:[...document.querySelectorAll('#page-todo .todo-item')].map(x=>(x.innerText||'').replace(/\\s+/g,' ').slice(0,90)),
          text:(document.getElementById('page-todo')||{}).innerText?.slice(0,300)
        })""")
        out["mine"] = mine
        await shot(p1, "12-fixed-h5-mine")
        # 打开全量弹层，截台账留痕 + 审批单并列
        await p1.evaluate("() => openAllMine()")
        await p1.wait_for_timeout(700)
        await shot(p1, "13-fixed-h5-all-mine")
        out["allMine"] = await p1.evaluate("""() => (document.querySelector('.all-mine')||{}).innerText?.slice(0,500)""")

        # 管理端：部门负责人待办
        c2 = await b.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        p2 = await c2.new_page()
        await p2.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
        await p2.wait_for_timeout(1300)
        # 管理端是独立租户体系，用 dsj_admin 看「我发起的」核对费用报销审批单
        await p2.evaluate("""() => {
          const ins=[...document.querySelectorAll('input')];
          const set=(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));};
          set(ins[0],'某某市某某区大数据管理局'); set(ins[1],'dsj_admin'); set(ins[2],'Admin@123');
          const btn=[...document.querySelectorAll('button')].find(x=>/登\\s*录/i.test(x.textContent||''));
          if(btn) btn.click();
        }""")
        await p2.wait_for_timeout(2600)
        await p2.evaluate("""() => {
          const el=[...document.querySelectorAll('div,span,li')].find(x=>(x.textContent||'').trim()==='审批中心');
          if(el) el.click();
        }""")
        await p2.wait_for_timeout(1800)
        await shot(p2, "14-fixed-admin-approval-center")
        out["adminText"] = await p2.evaluate("() => document.body.innerText.slice(0,400)")
        await b.close()

    with open(os.path.join(SHOT, "fixed-result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("MINE ROWS:", json.dumps(out["mine"]["rows"], ensure_ascii=False)[:800])
    print("ALL MINE:", str(out["allMine"])[:400])


asyncio.run(main())
