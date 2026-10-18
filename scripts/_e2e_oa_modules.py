#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OA 模块目录端到端点击自检（Playwright + msedge 无头，390x844）。

判据（每条都能因缺陷而变红，禁止恒真 —— 铁律 7/12）：

  K0  状态读取点 window.oaState 可读且 view='home'（H5 把内部状态暴露为 window.oaState，
      不是 window.S；读取点失效时后面 43 条会变成空转，所以先单独钉一条）。
  K1  抽屉里有「OA 模块」入口；点击后进入 #v-modules，且恰好 43 张卡。
  K2  43 张卡的 data-oa-mod 互不相同、全部以 OA 开头（防重复/漏建/错挂）。
  K3  **逐张点击 43 次**：每次点完都断言
        · 视图回到 #v-home（点击卡片就是开始对话，不留在目录页）
        · oaState.worker.workerType 等于该卡声明的值（不是"点了没反应"）
        · 对话坞出现「已选择数字员工「<卡上名称>」」气泡（名称与卡一致，防错位）
  K4  负向对照：末张点击后 oaState.worker.workerType 必须**等于末张**且**不等于首张**
      —— 证明 K3 的等值断言不是"任何值都通过"。
  K5  **线协议 43 次**：逐个模块「点卡 → 输入 → 发送」，拦截 POST /api/v1/conversations，
      断言请求体 workerId == 该卡的 data-worker（点得对≠传得对）；K5b 另外断言
      43 次发送恰好创建 43 个会话（换人即换会话，不能复用上一个人的）。
  K6a 登录前的 console 错误必须**全部**能归因于 /v1/asr/status 的 401（输入栏初始化
      时的语音探活，无 token 必然 401，属设计内 fail-open）；出现无法归因的噪声即红。
  K6b 登录后（含 43 卡点击全程）console 零 error。

跑法（需 :5181 静态+反代、:8080 后端在线）：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
      scripts/_e2e_oa_modules.py [--user wjj_xu] [--pwd User@123] [--mutate]

  --mutate = 自检模式（证明这套断言不是恒真）：把返回的文档在路由层改一个字符——
  「每张卡都绑到第一个模块」——此时 K3/K4 必须变红。若变异后仍全绿，说明断言空转，
  本脚本以退出码 1 报警。产品文件一个字节都不改。
退出码 = 失败条数（--mutate 下「变异被捕获」= 0）。
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_oa')
USER, PWD = 'wjj_xu', 'User@123'
EXPECT = 43

fails, console_errors, bad_responses = [], [], []
MUTATE = '--mutate' in sys.argv


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)
    return ok


async def main():
    global USER, PWD
    argv = sys.argv[1:]
    if '--user' in argv:
        USER = argv[argv.index('--user') + 1]
    if '--pwd' in argv:
        PWD = argv[argv.index('--pwd') + 1]
    os.makedirs(OUT, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('pageerror', lambda e: console_errors.append('pageerror: ' + str(e)))
        page.on('console', lambda m: console_errors.append('console.error: ' + m.text)
                if m.type == 'error' else None)
        # 4xx/5xx 一律留 URL：console 只说「某个资源 401」，不说是哪个 ⇒ 无法判断是
        # 登录前的正常探活还是真缺陷。这里把状态码与路径一起记下来，失败信息才可复核。
        page.on('response', lambda r: bad_responses.append('%s %s' % (r.status, r.url))
                if r.status >= 400 else None)

        # ---------------- 自检变异（只改路由层返回的文本，磁盘上的产品文件不动） ----------------
        if MUTATE:
            raw = (await (await ctx.request.get(BASE)).body()).decode('utf-8')
            mut = raw.replace('if(w) oaPickWorker(w);', 'if(w) oaPickWorker(ws[0]);')
            if mut == raw:
                chk('变异注入点存在', False, '未找到 "if(w) oaPickWorker(w);"（产品改名了，请同步改本脚本）')
                await browser.close()
                return report()
            await page.route(BASE, lambda r: r.fulfill(status=200,
                              content_type='text/html; charset=utf-8', body=mut))
            print('[MUTATE] 已注入「每张卡都绑第一个模块」，期望 K3/K4 变红')

        # ---------------- 登录 ----------------
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        try:
            await page.wait_for_selector('body.auth', timeout=20000)
        except Exception:
            chk('登录成功', False, 'body.auth 未出现（账号/后端/额度）')
            await browser.close()
            return report()

        # 登录前的时间窗单独结算：输入栏初始化时 probeAsr() 会打 /v1/asr/status，
        # 此时还没有 token ⇒ 浏览器必然在 console 记一条 401（这是浏览器层面的网络日志，
        # 应用代码 catch 不掉）。该探活由设计决定 fail-open（_backup_index_pre_oa.html:4539-4568）。
        # ★不豁免、只钉身份：登录前的每条错误都必须能对上「/v1/asr/status 的 401」，
        #   对不上就是真有缺陷；登录后则必须一条都没有。
        await page.wait_for_timeout(300)   # 让登录前那批探活的响应落定，避免跨窗口计数
        pre_console, pre_resp = list(console_errors), list(bad_responses)
        console_errors.clear()
        bad_responses.clear()

        # ---------------- K0 状态读取点自证 ----------------
        # 本套 43 条断言全部依赖 window.oaState 可读。若将来有人改了这个全局名，
        # 所有等于比较都会因 undefined 而"看起来失败"、或因读不到而静默跳过，
        # 所以先把「读取点本身活着」钉成一条独立断言（否则后面全是空转）。
        probe = await page.evaluate("""() => ({
            has: typeof window.oaState === 'object' && window.oaState !== null,
            view: (window.oaState || {}).view,
            keys: Object.keys(window.oaState || {}).length
        })""")
        if not chk('K0 状态读取点 window.oaState 可读', probe['has'] and probe['view'] == 'home',
                   'has=%s view=%s keys=%s' % (probe['has'], probe['view'], probe['keys'])):
            await browser.close()
            return report()


        await page.click('#oaLeft')
        await page.wait_for_timeout(400)
        has_entry = await page.evaluate("() => !!document.getElementById('odModules')")
        if not chk('K1a 抽屉有「OA 模块」入口', has_entry):
            await browser.close()
            return report()
        await page.click('#odModules')
        await page.wait_for_timeout(900)

        meta = await page.evaluate("""() => ({
            view: (window.oaState || {}).view,
            onHome: !!document.querySelector('#v-modules.on'),
            codes: Array.from(document.querySelectorAll('#oaModGrid .mod-card')).map(b => b.dataset.oaMod),
            names: Array.from(document.querySelectorAll('#oaModGrid .mod-card')).map(b => b.getAttribute('aria-label')),
            workerIds: Array.from(document.querySelectorAll('#oaModGrid .mod-card')).map(b => b.dataset.worker)
        })""")
        chk('K1b 进入 OA 模块视图', meta['view'] == 'modules' and meta['onHome'],
            'view=%s on=%s' % (meta['view'], meta['onHome']))
        chk('K1c 模块卡数量 = %d' % EXPECT, len(meta['codes']) == EXPECT, len(meta['codes']))
        if len(meta['codes']) != EXPECT:
            await page.screenshot(path=os.path.join(OUT, 'modules-count-fail.png'))
            await browser.close()
            return report()

        # ---------------- K2 唯一性 ----------------
        uniq = len(set(meta['codes'])) == EXPECT
        chk('K2a data-oa-mod 互不相同', uniq, '%d 个唯一值' % len(set(meta['codes'])))
        bad_prefix = [c for c in meta['codes'] if not str(c).startswith('OA')]
        chk('K2b 全部以 OA 开头', not bad_prefix, bad_prefix[:3])
        await page.screenshot(path=os.path.join(OUT, 'oa-modules-grid.png'))

        # ---------------- K3 逐张点击 43 次 ----------------
        ok_all = True
        for i, code in enumerate(meta['codes']):
            card = page.locator('#oaModGrid .mod-card[data-oa-mod="%s"]' % code)
            await card.click()
            try:
                await page.wait_for_function(
                    "c => window.oaState && window.oaState.view === 'home'"
                    " && window.oaState.worker && window.oaState.worker.workerType === c",
                    arg=code, timeout=6000)
            except Exception:
                pass      # 等不到就让下面的断言按事实判红，异常本身不进 console 计数
            st = await page.evaluate("""() => ({
                view: (window.oaState || {}).view,
                wid: (window.oaState || {}).worker && (window.oaState || {}).worker.id,
                wtype: (window.oaState || {}).worker && (window.oaState || {}).worker.workerType,
                wname: (window.oaState || {}).worker && (window.oaState || {}).worker.name,
                bubble: (document.querySelector('#oaDockList') || {}).innerText || ''
            })""")
            same = (st['view'] == 'home'
                    and str(st['wtype']) == code
                    and str(st['wname']) == meta['names'][i]
                    and ('「' + str(meta['names'][i]) + '」') in st['bubble'])
            if not same:
                ok_all = False
                chk('K3 %02d %s' % (i + 1, code), False,
                    'view=%s type=%s name=%s bubble=%r' % (st['view'], st['wtype'], st['wname'], st['bubble'][:60]))
            # 回目录，点下一张
            if i < len(meta['codes']) - 1:
                await page.click('#oaLeft')
                await page.wait_for_selector('.dnav-item', state='attached')
                await page.click('#odModules')
                await page.wait_for_selector('#v-modules.on', timeout=8000)
        chk('K3 43 张卡逐一点击（视图/绑定/气泡名称全对）', ok_all,
            '逐条见上，仅打印失败项')
        await page.screenshot(path=os.path.join(OUT, 'oa-modules-last-clicked.png'))

        # ---------------- K4 负向对照 ----------------
        neg = await page.evaluate("() => (window.oaState||{}).worker && (window.oaState||{}).worker.workerType")
        first, last = meta['codes'][0], meta['codes'][-1]
        chk('K4 负向对照：末张=%s 且 != 首张=%s（状态跟随点击，不是常量）' % (last, first),
            str(neg) == last and (first == last or str(neg) != first),
            '当前=%s' % neg)

        # ---------------- K5 线协议：43 个模块逐个「点卡 → 输入 → 发送」 ----------------
        # K3 只证明「点了状态对」，K5 证明「发出去的对」。两者之间隔着 conversations 组包；
        # 单点抽查会漏掉「换了模块却复用上一个人的会话」这类缺陷，所以 43 个全发一遍。
        # 后端不参与：三个端点本地打桩，断言只落在请求体（workerId）与会话创建次数上。
        seq = {'n': 0}
        bodies = []
        # 失败时要知道「到底是没发，还是发到了别的 URL」——把每次迭代的会话/运行请求都记下来。
        itlog = {'mark': 0, 'reqs': []}
        page.on('request', lambda r: itlog['reqs'].append('%d %s %s' % (itlog['mark'], r.method, r.url))
                if ('/conversations' in r.url or '/runs' in r.url) else None)

        async def on_conv(route):
            seq['n'] += 1
            bodies.append(route.request.post_data or '{}')
            await route.fulfill(status=200, content_type='application/json',
                                body='{"code":0,"message":"ok","data":{"id":%d}}' % (900000 + seq['n']))

        async def on_run(route):
            await route.fulfill(status=200, content_type='application/json',
                                body='{"code":0,"message":"ok","data":{"runId":"stub-run"}}')

        async def on_events(route):
            await route.fulfill(status=200, content_type='text/event-stream', body='')

        await page.route('**/api/v1/conversations', on_conv)
        await page.route('**/api/v1/conversations/*/runs', on_run)
        await page.route('**/api/v1/runs/*/events', on_events)

        ok_wire = True
        stuck = []
        for i, code in enumerate(meta['codes']):
            itlog['mark'] = i + 1
            # 抽屉有滑入动画：固定 sleep 会偶发「卡片点击被还盖在上面的抽屉吃掉」，
            # 现象是"状态没换 ⇒ 复用上一个人的会话 ⇒ 根本没有 conversations 请求"。
            # 所以每一步都等**可观察事实**，而不是等时间。
            await page.click('#oaLeft')
            await page.wait_for_selector('.dnav-item', state='attached')
            await page.click('#odModules')
            await page.wait_for_selector('#v-modules.on', timeout=8000)
            await page.wait_for_selector('#oaModGrid .mod-card[data-oa-mod="%s"]' % code, timeout=8000)
            await page.locator('#oaModGrid .mod-card[data-oa-mod="%s"]' % code).click()
            # 点完必须真的切到这个模块（等状态，不等时间）——等不到就直接判红，
            # 不然后面的发送会对着上一个人的会话发，把"点失败"伪装成"发失败"。
            try:
                await page.wait_for_function(
                    "c => window.oaState && window.oaState.worker && window.oaState.worker.workerType === c",
                    arg=code, timeout=6000)
            except Exception:
                now = await page.evaluate("() => (window.oaState||{}).worker && (window.oaState||{}).worker.workerType")
                ok_wire = False
                chk('K5 %02d %s' % (i + 1, code), False, '点卡后状态未切换（当前=%s）' % now)
                continue
            n0 = len(bodies)
            await page.fill('#oaInput', '模块线协议探针 %02d' % (i + 1))
            await page.click('#oaSendBtn')
            for _ in range(40):                      # 等这一次的 conversations 请求落地（≤4s）
                if len(bodies) > n0:
                    break
                await page.wait_for_timeout(100)
            got = bodies[n0] if len(bodies) > n0 else None
            want = meta['workerIds'][i]
            if got is None or ('"workerId":%s' % want) not in got.replace(' ', ''):
                ok_wire = False
                diag = await page.evaluate("""() => ({
                    input: (document.getElementById('oaInput')||{}).value,
                    send: !!document.getElementById('oaSendBtn'),
                    convId: (window.oaState||{}).convId,
                    bubble: (document.querySelector('#oaDockList')||{}).innerText.slice(0,80) })""")
                chk('K5 %02d %s' % (i + 1, code), False,
                    'want workerId=%s body=%s diag=%s reqs=%s' % (
                        want, (got or '<未发出>')[:100], diag,
                        [r for r in itlog['reqs'] if r.startswith('%d ' % (i + 1))][:4]))
            # ★必须等上一条真的收口（busy 自己回 false）再发下一条。
            # 强制把 busy 改成 false 会让上一条尚未返回的 oaEnsureConv 回调把**旧** convId
            # 写回到刚切换的新模块上 ⇒ 新模块复用旧会话、连 conversations 都不发。
            # 这正是本循环最初 5/43、后来 2/43 偶发失败的真因（不是产品缺陷）。
            try:
                await page.wait_for_function("() => !window.oaState.busy", timeout=8000)
            except Exception:
                stuck.append(code)
                await page.evaluate("""() => { var s = window.oaState;
                    if (s.controller) { try { s.controller.abort(); } catch(e){} s.controller = null; }
                    s.busy = false; }""")
                await page.wait_for_timeout(400)   # 让被强杀那条的尾部回调落定，再进下一条
        if stuck:
            print('    · 打桩流未自行收口、被迫复位 busy 的模块：%s' % stuck)
        chk('K5 43 个模块逐个发送，workerId 全部命中该模块数字人', ok_wire,
            '捕获会话创建 %d 次，逐条见上（仅打印失败项）' % len(bodies))
        chk('K5b 43 次发送创建 43 个会话（未跨模块复用上一个人的会话）',
            len(bodies) == EXPECT, len(bodies))

        await page.unroute('**/api/v1/conversations')
        await page.unroute('**/api/v1/conversations/*/runs')
        await page.unroute('**/api/v1/runs/*/events')

        # ---------------- K6 控制台 ----------------
        # 登录前：全部噪声必须能归因到「/v1/asr/status 的 401」这唯一来源。
        unexplained = [e for e in pre_console
                       if not any('asr/status' in r and r.startswith('401') for r in pre_resp)]
        stranged_pre = [r for r in pre_resp if not ('asr/status' in r and r.startswith('401'))]
        chk('K6a 登录前的 console 错误可全部归因于 ASR 探活（无其它未知噪声）',
            not unexplained and not stranged_pre,
            '登录前 console=%d 4xx=%s' % (len(pre_console), pre_resp[:4]))
        chk('K6b 登录后（含 43 卡点击全程）console 无 error', not console_errors,
            '%s || 4xx/5xx: %s' % ('; '.join(console_errors[:3]), bad_responses[:6]))

        await browser.close()
    return report()


def report():
    if MUTATE:
        caught = ('K3 43 张卡逐一点击（视图/绑定/气泡名称全对）' in fails
                  and any(f.startswith('K4') for f in fails))
        print('\n[MUTATE] %s' % ('变异被捕获（K3/K4 变红）✅ 断言非恒真' if caught
                                 else '⚠️ 变异未被捕获 —— 这套断言是空转的，必须修'))
        return 0 if caught else 1
    print('\n[RESULT] %s' % ('全绿（K0–K6）' if not fails else 'FAIL %d 项' % len(fails)))
    return len(fails)


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
