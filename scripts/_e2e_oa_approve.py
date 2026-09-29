#!/usr/bin/env python3
"""OA 内「审批决策」端到端验收（唯一会写库的 OA 套件，夹具零额度成本）。

为什么单独一个套件：`_e2e_oa.py` 用的是普通成员 `wjj_xu`，其「待我审批」恒为空，
**只能验负向**（非该范围不出现决策按钮），验不到正向「通过/驳回按钮确实出现且点了真生效」。
而「业务要接后端，如审核之类的」是本轮的核心要求，必须真跑一次。

三段互相独立（判据不共用同源数据，见技能铁律二十二）：
  ① 申请人 `wjj_xu` 提单（事假 CASUAL：quota=0 / 免证明 / 提前 1 天 ⇒ **不消耗任何额度**）
  ② 审批人 `wjj_admin`（ROLE_TENANT_ADMIN+ROLE_ORG_ADMIN，canApprove=true）在 **OA 形态**里
     待我审批 → 打开详情（断言「通过/驳回」出现）→ 点通过 → 填意见 → 确认
  ③ 回到申请人会话，用 `API.workflowMine()` 独立读回该单，断言终态 = APPROVED
     （终态判据取接口，不取审批人会话里的内存对象）

夹具说明：会新增一条**已通过的事假记录**（零额度成本、可被人工忽略，reason 里带自动化标记）。
不留清理步骤 —— 请假单无删除接口，且已通过的单据正是演示数据的一部分。
"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
APPLICANT, APPLICANT_PWD = 'wjj_xu', 'User@123'      # 普通成员（科员）
APPROVER, APPROVER_PWD = 'wjj_admin', 'User@123'     # 机构管理员（局长），canApprove=true
MARK = 'OA 端到端验收·自动化'
START, END = '2026-10-05', '2026-10-06'              # 事假 2 个工作日，advance=1 满足

fails = []


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


async def login(page, user, pwd, label):
    """登录并切到 OA 形态（复用调用方传来的 page —— 自己 new_page 会让调用方
    继续持有一个从未导航的空白页，evaluate 时 API 未定义）。"""
    await page.goto(BASE, wait_until='domcontentloaded')
    await page.wait_for_timeout(900)
    await page.fill('#lgUser', user)
    await page.fill('#lgPass', pwd)
    await page.click('#lgBtn')
    await page.wait_for_selector('body.auth', timeout=15000)
    chk('%s 登录成功' % label, True)
    await page.evaluate("() => localStorage.setItem('aioa_mode','oa')")
    await page.reload(wait_until='domcontentloaded')
    await page.wait_for_timeout(3200)
    return page


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        errors = []

        # ---------------- ① 申请人提单 ----------------
        c1 = await browser.new_context(viewport={'width': 390, 'height': 844}, locale='zh-CN')
        p1 = await c1.new_page()
        p1.on('pageerror', lambda e: errors.append('applicant pageerror: ' + str(e)))
        p1.on('console', lambda m: errors.append('applicant console.error: ' + m.text)
              if m.type == 'error' else None)
        await login(p1, APPLICANT, APPLICANT_PWD, '申请人 %s' % APPLICANT)

        before = await p1.evaluate("""async () => {
          const r = await API.workflowMine();
          const l = Array.isArray(r) ? r : (r.items || []);
          return l.length;
        }""")
        created = await p1.evaluate("""async (args) => {
          try {
            const r = await API.leaveSubmit({leaveTypeCode:'CASUAL',
              startDate:args[0], endDate:args[1], reason:args[2]});
            const l = await API.workflowMine();
            const list = Array.isArray(l) ? l : (l.items || []);
            const hit = list.filter(a => String(a.content||'').includes(args[2]))[0] || {};
            return { ok:true, resp:r, id:hit.id, status:hit.status,
                     n:list.length, bizType:hit.bizType, title:hit.title };
          } catch(e) { return { ok:false, err: (e && e.message) || String(e) }; }
        }""", [START, END, '%s（事假 %s~%s，可忽略）' % (MARK, START, END)])
        chk('① 申请人提单成功（事假，零额度成本）', created['ok'] is True, created.get('err', ''))
        if not created['ok']:
            await browser.close()
            return report()
        chk('① 单据进入申请人「我发起的」且为待审批',
            created.get('id') is not None and created.get('status') == 'PENDING',
            {'id': created.get('id'), 'status': created.get('status'),
             'n_before': before, 'n_after': created.get('n')})
        appr_id = created.get('id')
        if appr_id is None:
            await browser.close()
            return report()

        # ---------------- ② 审批人在 OA 里决策 ----------------
        c2 = await browser.new_context(viewport={'width': 390, 'height': 844}, locale='zh-CN')
        p2 = await c2.new_page()
        p2.on('pageerror', lambda e: errors.append('approver pageerror: ' + str(e)))
        p2.on('console', lambda m: errors.append('approver console.error: ' + m.text)
              if m.type == 'error' else None)
        await login(p2, APPROVER, APPROVER_PWD, '审批人 %s' % APPROVER)

        can = await p2.evaluate("() => !!state.canApprove")
        chk('② 审批人具备审批权限（state.canApprove）', can is True, can)

        await p2.click('#oaTabs .tab[data-view="collab"]')
        await p2.wait_for_timeout(900)
        await p2.click('#oaRail .rail-item[data-panel="approvals"]')
        await p2.wait_for_timeout(900)
        await p2.click('#v-collab .org-chip[data-scope="todo"]')
        await p2.wait_for_timeout(1200)

        todo = await p2.evaluate("""(id) => {
          const rows = [...document.querySelectorAll('#v-collab [data-appr]')];
          const row = rows.filter(r => r.dataset.appr === String(id))[0];
          return { n: rows.length, found: !!row,
                   texts: rows.map(r => (r.querySelector('.tl-name')||{}).textContent) };
        }""", appr_id)
        chk('② 新单出现在 OA「待我审批」', todo['found'] is True,
            {'n': todo['n'], 'want_id': appr_id, 'titles': todo['texts']})

        await p2.evaluate("""(id) => {
          const rows = [...document.querySelectorAll('#v-collab [data-appr]')];
          const row = rows.filter(r => r.dataset.appr === String(id))[0];
          if (row) row.click();
        }""", appr_id)
        await p2.wait_for_timeout(1000)

        det = await p2.evaluate("""() => ({
          view: window.oaState.view,
          hasOk: !!document.getElementById('oaApOk'),
          hasRej: !!document.getElementById('oaApRej'),
          body: (document.getElementById('v-appr')||{}).textContent.slice(0,120)
        })""")
        chk('② 待我审批的详情**出现**通过/驳回（正向，此前无法验）',
            det['view'] == 'appr' and det['hasOk'] and det['hasRej'],
            {'view': det['view'], 'ok': det['hasOk'], 'rej': det['hasRej']})

        await p2.click('#oaApOk')          # → askApprovalNote('APPROVE') 弹意见框
        await p2.wait_for_timeout(900)
        modal = await p2.evaluate("""() => {
          const ta = document.getElementById('approvalNote');
          return { open: !!ta, ok: !!document.querySelector('[data-note-ok]'),
                   val: ta ? ta.value : null };
        }""")
        chk('② 点「通过」弹出意见框（复用经典 askApprovalNote）',
            modal['open'] is True and modal['ok'] is True, modal)

        await p2.evaluate("""() => {
          const ta = document.getElementById('approvalNote');
          if (ta) ta.value = 'OA 端到端验收：同意';
        }""")
        await p2.click('[data-note-ok]')
        await p2.wait_for_timeout(2200)

        after = await p2.evaluate("""(id) => {
          const rows = [...document.querySelectorAll('#v-collab [data-appr]')];
          return { stillTodo: rows.some(r => r.dataset.appr === String(id)),
                   todoN: rows.length,
                   toast: (document.getElementById('toast')||{}).textContent || '' };
        }""", appr_id)
        chk('② 决策后该单退出「待我审批」列表', after['stillTodo'] is False, after)

        # ---------------- ③ 申请人侧独立核实终态 ----------------
        p3 = await c1.new_page()
        await p3.goto(BASE, wait_until='domcontentloaded')
        await p3.wait_for_timeout(3200)
        final = await p3.evaluate("""async (id) => {
          const r = await API.workflowMine();
          const list = Array.isArray(r) ? r : (r.items || []);
          const a = list.filter(x => String(x.id) === String(id))[0] || null;
          return a ? { status: a.status, decided: a.decidedAt,
                       note: a.decisionNote, title: a.title } : { status: 'NOT_FOUND' };
        }""", appr_id)
        chk('③ 独立读回：终态 = APPROVED（判据取接口，不取审批人内存）',
            final['status'] == 'APPROVED', final)

        chk('三段 console 无 error / 无未捕获异常', len(errors) == 0, errors[:4])
        await browser.close()
    return report()


def report():
    print('\n失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
