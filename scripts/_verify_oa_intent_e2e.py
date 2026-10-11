# -*- coding: utf-8 -*-
"""OA 对话意图 → 真窗口 的**端到端**哨兵（2026-10，堵真实覆盖缺口）。

为什么需要这一条（已核实）：
  scripts/_verify_oa_action_popup.py 只用 `page.evaluate("() => window.oaMaybeProjectAction(
  {action:'UPLOAD_FILE'})")` **直接喂一个手工构造的 intent**，而且跑在 `file://` 下、
  `API.req` 还是**打桩**的。它证明不了「用户真打一句话 → 真弹出窗口 → 真去后端取文件夹」
  这段端到端链路。本脚本走**完整真实链路**：

    用户在 OA 对话坞输入 → oaSend() → await API.workerIntent(q)
    （POST /v1/workers/intent，由 agent :8000 真分类器判定）
    → oaAfterOaAnswer() → oaMaybeProjectAction(intent)
    → oaOpenUploadForm()/oaOpenExpenseForm() → 真窗口 + 真拉 GET /v1/pm/projects/{id}/docs/tree。

  所有断言都回到「事实源头」（状态对象 / 后端接口真实返回 / 真实 DOM），不读界面自己的副本。

判据（每条都回到事实源头）：
  前置   登录成功 → 切到 OA 形态 → 进入一个项目；
         **必须断言 window.oaState.currentProject 非空**（以状态对象为真值源，不读界面文案）。
         若该账号当前**没有可见项目**（卡片数 0）⇒ 记 SKIP + 非0，**不伪装 PASS**。
  I1    「我要上传文档」→ 真弹「上传项目文档」窗口（含 #upFile）；
        #upFolder 真从后端取到项目文件夹（选中 value 非空，folderId 契约源头）；
        #upFile 在文件夹就绪后被解锁（!disabled）；关闭后 .notif-mask 计数回到 0。
  I2    「上报一笔花费」→ 真弹「上报项目花费」窗口（含 #expAmt）；关闭后计数回 0。
  I3 ★ 负向对照「请简单介绍一下你能做什么」→ 全程不得出现任何 .notif-mask
        （监听 + 结束时计数，证明 I1/I2 的「窗口出现」不是恒真）。

SKIP 纪律（同 _verify_pm_doc_upload.py / _check_gitee_repo_write.py / _check_gitee_repo_write.py）：
  ① 该账号当前没有可见项目（卡片数 0）⇒ SKIP + 非0，不伪装 PASS；
  ② agent :8000（意图分类器）不在线 ⇒ I1/I2 拿不到 action ⇒ SKIP + 非0，说明是环境，不硬跑断言。

前置：本地静态服务 127.0.0.1:5181（H5 经它把 /api 代理到后端 :8080）；
      :8080 与 agent :8000 当前在线。账号常量照抄 _e2e_oa.py。
用法：python scripts/_verify_oa_intent_e2e.py
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'          # 普通成员（科员）：与 _e2e_oa.py 同一账号
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_oa_intent')

PASS, FAIL, SKIP = [], [], []
errors = []
shots = []


def chk(name, ok, detail=''):
    (PASS if ok else FAIL).append(name + (' — ' + str(detail) if detail else ''))
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    return ok


async def shot(page, name):
    p = os.path.join(OUT, name + '.png')
    await page.screenshot(path=p)
    shots.append(name)
    return p


async def dock_text(page):
    return await page.evaluate("() => { var el=document.getElementById('oaDockList'); return el?el.innerText:''; }") or ''


async def install_mask_observer(page):
    """监听 document.body 下新增的 .notif-mask 节点，累计计数（I3 负向对照用）。"""
    await page.evaluate("""() => {
      if(window.__maskObsInstalled) return;
      window.__maskAdds = 0;
      const obs = new MutationObserver(function(muts){
        muts.forEach(function(m){ m.addedNodes.forEach(function(n){
          if(n && n.nodeType === 1 && n.classList && n.classList.contains('notif-mask')) window.__maskAdds++;
        }); });
      });
      obs.observe(document.body, {childList:true, subtree:true});
      window.__maskObsInstalled = true;
    }""")


def report():
    print('\n截图：%d 张 → %s/' % (len(shots), OUT))
    print('通过：%d / 失败：%d / SKIP：%d' % (len(PASS), len(FAIL), len(SKIP)))
    for f in FAIL:
        print('  - FAIL ' + f)
    for s in SKIP:
        print('  - SKIP ' + s)
    if errors:
        print('控制台错误 %d 条：' % len(errors))
        for e in errors[:10]:
            print('  ' + e[:180])
    return 1 if FAIL else (2 if SKIP else 0)


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                         device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('console', lambda m: errors.append('console.' + m.type + ': ' + m.text)
                if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))

        # ---------------- 登录 ----------------
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        try:
            await page.wait_for_selector('body.auth', timeout=15000)
        except Exception as e:
            chk('登录成功', False, str(e)[:80])
            await shot(page, '00-login-fail')
            await browser.close()
            return report()
        chk('登录成功（%s）' % USER, True)
        await page.wait_for_timeout(2500)

        # ---------------- 切到 OA 形态 ----------------
        await page.evaluate("() => { if(window.oaSetMode) window.oaSetMode('oa'); }")
        await page.wait_for_timeout(800)
        oa = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
        chk('已切到 OA 形态（.phone.oa-mode 生效）', oa)

        await install_mask_observer(page)

        # ---------------- 进入一个项目 ----------------
        await page.click('#oaTabs .tab[data-view="collab"]')
        await page.wait_for_timeout(800)
        await page.click('#oaRail .rail-item[data-panel="projects"]')
        # 等面板渲染：要么出现项目卡片，要么出现「暂无可见项目」空态
        try:
            await page.wait_for_function(
                """() => {
                  const el = document.getElementById('p-projects');
                  if(!el) return false;
                  if(el.querySelector('[data-project]')) return true;
                  return el.innerText.indexOf('暂无可见项目') >= 0;
                }""", timeout=15000)
        except Exception:
            pass
        n_cards = await page.evaluate("() => document.querySelectorAll('#p-projects [data-project]').length")
        if n_cards == 0:
            why = await page.evaluate("""() => {
              const el = document.getElementById('p-projects');
              return el ? el.innerText.slice(0, 80) : '面板缺失'; }""")
            SKIP.append('进入项目')
            print('  SKIP 进入项目 | 该账号当前没有可见项目（卡片数=0）：%s' % why)
            await browser.close()
            return report()
        # 点第一张项目卡片（真实用户路径 → enterProject）
        await page.click('#p-projects [data-project]')
        try:
            await page.wait_for_function(
                "() => !!(window.oaState && window.oaState.currentProject)", timeout=20000)
        except Exception as e:
            chk('进入项目：window.oaState.currentProject 非空', False, str(e)[:80])
            await browser.close()
            return report()
        cp = await page.evaluate("() => window.oaState.currentProject")
        chk('进入项目：window.oaState.currentProject 非空（以状态对象为真值源）',
            bool(cp and cp.get('id')), cp)
        await page.wait_for_timeout(1500)   # 等会话/上下文稳定
        await shot(page, '01-in-project')

        # ---------------- 分类器环境探针（agent :8000）----------------
        # 直接走真实 API.workerIntent：验证分类器在线且能给出 action。
        # 不在线 ⇒ I1/I2 拿不到 action ⇒ SKIP（环境），不硬跑后面断言。
        probe = await page.evaluate("""async () => {
          try {
            const r = await API.workerIntent('我要上传文档');
            return { action: (r && r.action) || null };
          } catch(e) { return { action: 'ERR:' + (e && e.message || e) }; }
        }""")
        if not probe.get('action') or str(probe.get('action')).startswith('ERR'):
            SKIP.append('I1/I2 分类器')
            print('  SKIP I1/I2 | 意图分类器不可用（agent :8000）：%s' % probe)
            await browser.close()
            return report()

        # ---------------- I1 上传意图端到端 ----------------
        await page.fill('#oaInput', '我要上传文档')
        await page.click('#oaSendBtn')
        # 等「真窗口出现且含 #upFile」：分类器走 agent，给足超时（90s）。
        try:
            await page.wait_for_function(
                """() => {
                  const m = document.querySelector('.notif-mask');
                  return !!m && !!m.querySelector('#upFile');
                }""", timeout=90000)
            i1_mask = True
        except Exception:
            i1_mask = False
        if not i1_mask:
            diag = await dock_text(page)
            chk('I1 上传意图：真弹出「上传项目文档」窗口（含 #upFile）',
                False, '90s 内未出现 .notif-mask #upFile；对话坞=%s' % diag[:120])
        else:
            head = await page.evaluate("""() => {
              const m = document.querySelector('.notif-mask');
              const h = m && m.querySelector('.notif-head');
              return h ? h.textContent.trim() : ''; }""")
            chk('I1 上传意图：窗口标题 == 「上传项目文档」', head == '上传项目文档', head)

            # 「文件夹就绪才解锁」：先等 #upFile 最终 !disabled（= 真去后端取到了文件夹）
            try:
                await page.wait_for_function(
                    """() => {
                      const m = document.querySelector('.notif-mask');
                      const el = m && m.querySelector('#upFile');
                      return !!el && !el.disabled;
                    }""", timeout=20000)
                unlocked = True
            except Exception:
                unlocked = False
            chk('I1 上传意图：#upFile 在取到文件夹后被解锁（!disabled）', unlocked)

            # 文件夹：真从后端取到（folderId 契约源头）；选中 value 非空证明真取到了根文件夹
            folder = await page.evaluate("""() => {
              const m = document.querySelector('.notif-mask');
              const sel = m && m.querySelector('#upFolder');
              if(!sel) return {n:0, val:'', txt:''};
              const o = sel.selectedOptions && sel.selectedOptions[0];
              return {n: sel.options.length, val: o ? o.value : '', txt: o ? o.text : ''};
            }""")
            chk('I1 上传意图：#upFolder 已从后端取到项目文件夹（options>=1 且选中 value 非空）',
                folder['n'] >= 1 and bool(folder['val']), folder)

            # 关闭窗口并断言计数回到 0
            await page.evaluate("""() => {
              const m = document.querySelector('.notif-mask');
              const c = m && m.querySelector('[data-dlg-cancel]');
              if(c) c.click(); }""")
            await page.wait_for_timeout(400)
            n_mask = await page.evaluate("() => document.querySelectorAll('.notif-mask').length")
            chk('I1 上传意图：关闭后 .notif-mask 计数回到 0', n_mask == 0, 'count=%d' % n_mask)
            await shot(page, '02-i1-upload-window')

        # ---------------- I2 花费意图端到端 ----------------
        await page.fill('#oaInput', '上报一笔花费')
        await page.click('#oaSendBtn')
        try:
            await page.wait_for_function(
                """() => {
                  const m = document.querySelector('.notif-mask');
                  return !!m && !!m.querySelector('#expAmt');
                }""", timeout=90000)
            i2_mask = True
        except Exception:
            i2_mask = False
        if not i2_mask:
            diag = await dock_text(page)
            chk('I2 花费意图：真弹出「上报项目花费」窗口（含 #expAmt）',
                False, '90s 内未出现 .notif-mask #expAmt；对话坞=%s' % diag[:120])
        else:
            head2 = await page.evaluate("""() => {
              const m = document.querySelector('.notif-mask');
              const h = m && m.querySelector('.notif-head');
              return h ? h.textContent.trim() : ''; }""")
            chk('I2 花费意图：窗口标题 == 「上报项目花费」', head2 == '上报项目花费', head2)
            await page.evaluate("""() => {
              const m = document.querySelector('.notif-mask');
              const c = m && m.querySelector('[data-dlg-cancel]');
              if(c) c.click(); }""")
            await page.wait_for_timeout(400)
            n_mask2 = await page.evaluate("() => document.querySelectorAll('.notif-mask').length")
            chk('I2 花费意图：关闭后 .notif-mask 计数回到 0', n_mask2 == 0, 'count=%d' % n_mask2)
            await shot(page, '03-i2-expense-window')

        # ---------------- I3 ★ 负向对照 ----------------
        # 重置监听计数器（I1/I2 期间累加的计数清零），证明 I1/I2 的「窗口出现」不是恒真。
        await page.evaluate("() => { window.__maskAdds = 0; }")
        await page.fill('#oaInput', '请简单介绍一下你能做什么')
        await page.click('#oaSendBtn')
        # 等回答收口（S.busy 释放），再给足 8s 让后台 intent 跑完
        try:
            await page.wait_for_function("() => !window.oaState.busy", timeout=90000)
        except Exception:
            pass
        await page.wait_for_timeout(8000)
        neg = await page.evaluate("""() => ({
          adds: window.__maskAdds,
          live: document.querySelectorAll('.notif-mask').length })""")
        chk('I3 ★ 负向对照：非动作语句全程未弹出任何 .notif-mask 窗口',
            neg['adds'] == 0 and neg['live'] == 0, neg)
        await shot(page, '04-i3-negative')

        # 控制台无未捕获错误
        chk('控制台无 error / 无未捕获异常', len(errors) == 0, errors[:5])

        await browser.close()
    return report()


if __name__ == '__main__':
    try:
        rc = asyncio.run(main())
    except Exception as exc:
        chk('流程未跑完（异常中断）', False, '%s: %s' % (type(exc).__name__, str(exc)[:160]))
        rc = 1
    sys.exit(rc or (1 if FAIL else 0))
