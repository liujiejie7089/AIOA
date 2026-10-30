# -*- coding: utf-8 -*-
"""确认交互（need_confirm）离线哨兵 —— Playwright + file://，不需要后端。

验证目标：2026-10-31 新增的第三条 HITL 链在**前端**是否真的按契约工作
（docs/39 §11.6）。五条要求逐条对应到判据，每条都能因缺陷变红：

  R1  卡片形状：`confirmCardHtml` 产出 .confirm-card / .cf-title / .confirm-row，
      两个按钮 data-cf-cancel 在左、data-cf-ok 在右，文案取 payload 的
      confirm_label / cancel_label；无 description 时不渲染 .cf-desc（不留空白格）。
  R2  转义：title 传 XSS 向量，产出不得含裸 <img（防注入）。
  R3  危险态可区分：danger=true 时 .confirm-card.danger 且确认键底色与普通态**不同**
      （负向对照：同一样式取两次必须相同，证明判据不是恒真）。
  R4  点「确认」：两键**立即** disabled + 确认键文案转「处理中…」+ runner 收到 decision=true；
      加载未结束时再点一次:**不会**二次调用 runner（busy + disabled 双闸）。
  R5  成功后：出现 .cf-note.ok「已确认」，两键**保持禁用**（永久不可再点），
      Promise resolve 值 = {decision:true}。
  R6  点「取消」：runner 收到 decision=false，note 为「已取消」，resolve 值 = {decision:false}。
  R7  失败态：runner reject ⇒ 两键**恢复可点** + .cf-note.err 含失败原因（可重试），
      再点一次成功 ⇒ 转为已完成（证明恢复可用不是摆设）。
  R8  need_confirm 分发：拦截 SSE 返回 event: need_confirm，断言 h.onConfirm 被调用且
      payload 正确；负向对照换成 need_clarification 时 onConfirm **不被**调用。
  R9  随对话滚动不溢出：卡挂在气泡内后 scrollWidth <= clientWidth + 1（不出横向滚动条），
      且卡属于气泡的一部分（parentElement 就是气泡），跟着对话一起滚。
  S1  静态：confirmCardHtml / mountConfirmCard / appendSysNote / cancelConfirmCard 四个
      入口都在文件中存在，且 handle 里有 need_confirm 分支、两个形态的收口循环都带 cfm。

跑法（playwright 装在该环境）：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_confirm_card.py

退出码非零 = 有断言失败。
"""
import asyncio
import os
import sys
import urllib.parse

from playwright.async_api import async_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, 'user-client', 'index.html')

fails = []
oks = 0


def chk(name, ok, detail=''):
    global oks
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''), flush=True)
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


async def main():
    if not os.path.exists(INDEX):
        chk('index.html 存在', False, INDEX)
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('pageerror', lambda e: print('  [pageerror] ' + str(e), flush=True))

        file_url = 'file:///' + urllib.parse.quote(INDEX.replace('\\', '/'), safe='/')
        await page.goto(file_url, wait_until='domcontentloaded')
        await page.wait_for_timeout(400)

        # ===================== R1：卡片形状 =====================
        print('\n=== R1：卡片形状 ===')
        html = await page.evaluate("""(p) => confirmCardHtml(p)""", {
            "kind": "confirm", "title": "向张三发送这封邮件",
            "description": "收件人 1 人，发送后不可撤回。",
            "confirm_label": "确认发送", "cancel_label": "暂不发送", "danger": False})
        chk('R1 产出含 .confirm-card', 'class="confirm-card"' in html)
        chk('R1 产出含 .cf-title 且渲染标题', ('class="cf-title"' in html) and ('向张三发送这封邮件' in html))
        chk('R1 渲染 description', ('class="cf-desc"' in html) and ('收件人 1 人' in html))
        chk('R1 确认键取 confirm_label', ('data-cf-ok="1"' in html) and ('确认发送' in html))
        chk('R1 取消键取 cancel_label', ('data-cf-cancel="1"' in html) and ('暂不发送' in html))
        chk('R1 取消在左、确认在右（顺序）',
            html.index('data-cf-cancel') < html.index('data-cf-ok'),
            'cancel@%d ok@%d' % (html.index('data-cf-cancel'), html.index('data-cf-ok')))
        chk('R1 恰好两个按钮（不是单选卡）', html.count('class="cbtn') == 2,
            'cbtn=%d' % html.count('class="cbtn'))
        chk('R1 不是澄清卡（无 .clar-opt / 无 data-clar-ok）',
            ('clar-opt' not in html) and ('data-clar-ok' not in html))

        html_nodesc = await page.evaluate("""(p) => confirmCardHtml(p)""", {"title": "删除这 5 条记录"})
        chk('R1 无 description 时不渲染 .cf-desc（不留空白格）', 'cf-desc' not in html_nodesc)
        chk('R1 缺省文案回默认「确认 / 取消」',
            ('>确认<' in html_nodesc) and ('>取消<' in html_nodesc))
        html_empty = await page.evaluate("() => confirmCardHtml({title:''})")
        chk('R1 空标题回默认「请确认是否继续」', '请确认是否继续' in html_empty, html_empty[:80])

        # ===================== R2：转义 =====================
        print('\n=== R2：转义 / 防注入 ===')
        html_xss = await page.evaluate("""() => confirmCardHtml({title:'<img src=x onerror=alert(1)>删库'})""")
        chk('R2 产出不含裸 <img', '<img' not in html_xss, 'contains: %s' % ('<img' in html_xss))
        chk('R2 script 标签未原样注入', '<script' not in html_xss.lower())

        # ===================== R3：危险态可区分 =====================
        print('\n=== R3：危险态（删除类）视觉区分 ===')
        bg = await page.evaluate("""() => {
          function bgOf(danger){
            const d = document.createElement('div');
            d.innerHTML = confirmCardHtml({title:'将删除 5 条历史记录', danger: danger});
            document.body.appendChild(d);
            const btn = d.querySelector('[data-cf-ok]');
            const v = getComputedStyle(btn).backgroundColor;
            d.parentNode.removeChild(d);
            return v;
          }
          return {danger: bgOf(true), normal: bgOf(false), againnormal: bgOf(false)};
        }""")
        chk('R3 danger 与普通态底色不同（红色 ≠ 蓝色）', bg['danger'] != bg['normal'],
            'danger=%s normal=%s' % (bg['danger'], bg['normal']))
        chk('R3 负向对照：同参两次取色必须一致（非恒真）',
            bg['normal'] == bg['againnormal'], bg)
        has_cls = await page.evaluate(
            """() => confirmCardHtml({title:'x', danger:true}).indexOf('confirm-card danger') >= 0""")
        chk('R3 danger 带 .danger 类（选中器依据）', has_cls is True)

        # ===================== R4/R5：点「确认」=====================
        print('\n=== R4/R5：确认路径（加载中 + 防重复 + 成功冻结）===')
        snap = await page.evaluate("""() => new Promise(async (resolve) => {
          const host = document.createElement('div');
          host.className = 'bub'; host.id = 'cfHost1';
          document.body.appendChild(host);
          let calls = [];
          const p = mountConfirmCard(host, {title:'向张三发送这封邮件', confirm_label:'确认发送'},
            function(decision){
              calls.push(decision);
              return new Promise((res, rej) => { window.__cfRelease = (mode) => {
                mode === 'fail' ? rej(new Error('网络超时')) : res(); }; });
            });
          await new Promise(r => setTimeout(r, 30));
          const card = host.querySelector('.confirm-card');
          const ok = card.querySelector('[data-cf-ok]');
          const no = card.querySelector('[data-cf-cancel]');
          const before = { okDisabled: ok.disabled, noDisabled: no.disabled, okText: ok.textContent };
          ok.click();
          await new Promise(r => setTimeout(r, 0));
          const loading = { okDisabled: ok.disabled, noDisabled: no.disabled, okText: ok.textContent,
                            busy: card.classList.contains('busy'), calls: calls.slice() };
          // 加载未结束时再点两次：runner 绝不能被第二次调用
          ok.click(); no.click();
          await new Promise(r => setTimeout(r, 0));
          const afterDouble = { calls: calls.slice() };
          window.__cfRelease('ok');
          const out = await p;
          resolve({before, loading, afterDouble, out,
                   doneClass: card.classList.contains('done'),
                   note: (card.querySelector('.cf-note') || {}).textContent || '',
                   noteCls: (card.querySelector('.cf-note') || {}).className || '',
                   finalOkDisabled: ok.disabled, finalNoDisabled: no.disabled});
        })""")
        chk('R4 初始两键均可点', snap['before']['okDisabled'] is False and snap['before']['noDisabled'] is False,
            snap['before'])
        chk('R4 点击后两键立即 disabled（防重复提交）',
            snap['loading']['okDisabled'] is True and snap['loading']['noDisabled'] is True,
            snap['loading'])
        chk('R4 确认键文案转「处理中…」（加载中可见）', '处理中' in snap['loading']['okText'],
            'text=%s' % snap['loading']['okText'])
        chk('R4 卡片进入 busy 态', snap['loading']['busy'] is True)
        chk('R4 runner 收到 decision=true', snap['loading']['calls'] == [True], snap['loading']['calls'])
        chk('R4 加载中重复点击不二次调用 runner', snap['afterDouble']['calls'] == [True],
            snap['afterDouble']['calls'])
        chk('R5 resolve 值为 {decision:true}',
            isinstance(snap['out'], dict) and snap['out'].get('decision') is True, snap['out'])
        chk('R5 成功后标注「已确认」', '已确认' in snap['note'], snap['note'])
        chk('R5 标注用 ok 样式（非红色错误）', 'ok' in snap['noteCls'], snap['noteCls'])
        chk('R5 成功后两键保持禁用（永久不可再点）',
            snap['finalOkDisabled'] is True and snap['finalNoDisabled'] is True)

        # ===================== R6：点「取消」=====================
        print('\n=== R6：取消路径 ===')
        snap2 = await page.evaluate("""() => new Promise(async (resolve) => {
          const host = document.createElement('div');
          host.className = 'bub'; document.body.appendChild(host);
          let calls = [];
          const p = mountConfirmCard(host, {title:'删除这 5 条记录'},
            function(decision){ calls.push(decision); return Promise.resolve(); });
          await new Promise(r => setTimeout(r, 30));
          const card = host.querySelector('.confirm-card');
          const no = card.querySelector('[data-cf-cancel]');
          no.click();
          const out = await p;
          resolve({out: out, calls: calls,
                   note: (card.querySelector('.cf-note') || {}).textContent || '',
                   disabled: no.disabled});
        })""")
        chk('R6 runner 收到 decision=false', snap2['calls'] == [False], snap2['calls'])
        chk('R6 resolve 值为 {decision:false}',
            isinstance(snap2['out'], dict) and snap2['out'].get('decision') is False, snap2['out'])
        chk('R6 取消后给出「已取消」提示', '已取消' in snap2['note'], snap2['note'])
        chk('R6 取消后按钮禁用（同防重复）', snap2['disabled'] is True)

        # ===================== R7：失败态可恢复 + 可重试 =====================
        print('\n=== R7：失败态 ===')
        snap3 = await page.evaluate("""() => new Promise(async (resolve) => {
          const host = document.createElement('div');
          host.className = 'bub'; document.body.appendChild(host);
          let calls = [];
          let fail = true;
          const p = mountConfirmCard(host, {title:'提交用印申请'}, function(decision){
            calls.push(decision);
            return fail ? Promise.reject(new Error('网络超时')) : Promise.resolve();
          });
          await new Promise(r => setTimeout(r, 30));
          const card = host.querySelector('.confirm-card');
          const ok = card.querySelector('[data-cf-ok]');
          ok.click();
          // 注意：失败时 Promise **不会** reject（这是设计：卡片留在原地等用户重试），
          // 所以这里不能 await p —— 那会等到地老天荒。用一小段时间让错误处理跑完。
          await new Promise(r => setTimeout(r, 60));
          const failed = { okDisabled: ok.disabled, okText: ok.textContent,
                           noteCls: (card.querySelector('.cf-note') || {}).className || '',
                           note: (card.querySelector('.cf-note') || {}).textContent || '',
                           busy: card.classList.contains('busy') };
          // 重试：第二次放行
          fail = false;
          ok.click();
          const out = await p;
          resolve({failed, calls, out, done: card.classList.contains('done'),
                   note2: (card.querySelector('.cf-note') || {}).textContent || ''});
        })""")
        chk('R7 失败后按钮恢复可点（用户可以重试，不卡死）',
            snap3['failed']['okDisabled'] is False, snap3['failed'])
        chk('R7 失败后文案复位（不再是「处理中…」）', '处理中' not in snap3['failed']['okText'],
            snap3['failed']['okText'])
        chk('R7 失败标注用 err 样式并给出原因',
            ('err' in snap3['failed']['noteCls']) and ('网络超时' in snap3['failed']['note']),
            '%s / %s' % (snap3['failed']['noteCls'], snap3['failed']['note']))
        chk('R7 失败后退出 busy 态', snap3['failed']['busy'] is False)
        chk('R7 重试后成功（同一张卡恢复可用）',
            isinstance(snap3['out'], dict) and snap3['out'].get('decision') is True, snap3['out'])
        chk('R7 重试共调用两次 runner', snap3['calls'] == [True, True], snap3['calls'])

        # ===================== R8：need_confirm 分发 =====================
        print('\n=== R8：SSE 分发（拦截 need_confirm）===')
        await page.evaluate("() => { API.base = 'https://sentinel.local'; }")

        async def route_confirm(route, request):
            await route.fulfill(status=200,
                                headers={'content-type': 'text/event-stream',
                                         'access-control-allow-origin': '*'},
                                body='event: need_confirm\n'
                                     'data: {"kind":"confirm","title":"向张三发送这封邮件",'
                                     '"confirm_label":"确认发送","cancel_label":"取消","danger":false}\n\n')

        await page.route('**/v1/runs/x/events', route_confirm)
        try:
            await page.evaluate("""() => new Promise((resolve) => {
              window.__cfCalled = false; window.__cfPayload = null;
              window.__cfCompleted = false;
              const h = { onConfirm: (p) => { window.__cfCalled = true; window.__cfPayload = p; },
                          onDelta: () => {}, onCompleted: () => { window.__cfCompleted = true; },
                          onError: () => {}, onStarted: () => {} };
              API.stream('x', h).then(resolve).catch(resolve);
            })""")
            called = await page.evaluate("() => !!window.__cfCalled")
            payload = await page.evaluate("() => window.__cfPayload || null")
            completed = await page.evaluate("() => !!window.__cfCompleted")
            chk('R8 need_confirm 触发 h.onConfirm', called is True, 'called=%s' % called)
            chk('R8 payload 透传正确',
                isinstance(payload, dict) and payload.get('title') == '向张三发送这封邮件'
                and payload.get('confirm_label') == '确认发送', payload)
            chk('R8 暂停帧后不再等 message.completed（拿到卡即返回）', completed is False)
        finally:
            await page.unroute('**/v1/runs/x/events')

        # 负向对照：澄清帧不得当作确认帧（否则 UI 语义错位）
        async def route_clar(route, request):
            await route.fulfill(status=200,
                                headers={'content-type': 'text/event-stream',
                                         'access-control-allow-origin': '*'},
                                body='event: need_clarification\n'
                                     'data: {"question":"你要哪种？","suggested_options":[]}\n\n')

        await page.route('**/v1/runs/y/events', route_clar)
        try:
            await page.evaluate("""() => new Promise((resolve) => {
              window.__cfCalled2 = false;
              const h = { onConfirm: (p) => { window.__cfCalled2 = true; },
                          onClarification: () => {}, onDelta: () => {}, onCompleted: () => {},
                          onError: () => {}, onStarted: () => {} };
              API.stream('y', h).then(resolve).catch(resolve);
            })""")
            called2 = await page.evaluate("() => !!window.__cfCalled2")
            chk('R8 负向对照：need_clarification 不触发 onConfirm', called2 is False,
                'onConfirm called=%s' % called2)
        finally:
            await page.unroute('**/v1/runs/y/events')

        # ===================== R9：布局 ====
        print('\n=== R9：随对话滚动、不溢出 ===')
        layout = await page.evaluate("""() => {
          const host = document.createElement('div');
          host.className = 'bub';
          host.style.maxWidth = '300px';
          document.body.appendChild(host);
          host.innerHTML = confirmCardHtml({title:'向张三发送一封很长的邮件并抄送整个部门全体同事'});
          const card = host.querySelector('.confirm-card');
          const r = { cardW: card.scrollWidth, cardC: card.clientWidth,
                      hostW: host.scrollWidth, hostC: host.clientWidth,
                      parentIsHost: card.parentElement === host,
                      cardRight: Math.round(card.getBoundingClientRect().right),
                      hostRight: Math.round(host.getBoundingClientRect().right) };
          host.parentNode.removeChild(host);
          return r;
        }""")
        chk('R9 卡片不横向溢出（scrollWidth <= clientWidth+1）',
            layout['cardW'] <= layout['cardC'] + 1,
            '%s vs %s' % (layout['cardW'], layout['cardC']))
        chk('R9 宿主气泡不被撑宽', layout['hostW'] <= layout['hostC'] + 1,
            '%s vs %s' % (layout['hostW'], layout['hostC']))
        chk('R9 卡片挂在气泡内（随对话一起滚动）', layout['parentIsHost'] is True)
        chk('R9 卡片右缘不出气泡', layout['cardRight'] <= layout['hostRight'] + 1,
            '%s vs %s' % (layout['cardRight'], layout['hostRight']))

        await browser.close()

    # ===================== S1：静态契约 =====================
    print('\n=== S1：静态契约 ===')
    with open(INDEX, 'r', encoding='utf-8') as f:
        src = f.read()
    for name in ('confirmCardHtml', 'mountConfirmCard', 'appendSysNote', 'cancelConfirmCard'):
        chk('S1 %s 存在' % name, ('function %s(' % name) in src)
    chk('S1 SSE 分派有 need_confirm 分支', "ev.event === 'need_confirm'" in src)
    chk('S1 两形态都注册 onConfirm（callbacks）', src.count('onConfirm:') >= 2,
        'count=%d' % src.count('onConfirm:'))
    chk('S1 两形态收口循环都带 cfm', src.count('while(clar || form || cfm)') == 2,
        'count=%d' % src.count('while(clar || form || cfm)'))
    chk('S1 停止生成时收掉未决确认卡', 'cancelConfirmCard();' in src)
    chk('S1 确认键走 decision 回填（不是标量 answer）', '{decision: decision}' in src)

    print('\n──────── 收口 ────────')
    print('通过：%d / 失败：%d' % (oks, len(fails)))
    if fails:
        print('失败项：')
        for f in fails:
            print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
