# -*- coding: utf-8 -*-
"""H5 HITL 澄清链行为级哨兵（Playwright 拦截网络、自造 SSE 帧，不依赖 :8080 真实行为）。

验证目标：H5 三层（共享 API + 经典 send + OA oaSend）对 ask_user → need_clarification →
单选卡 → resume 契约的真实渲染与回填。

判据全部回到事实源头：
  · 真实 DOM 属性（getAttribute('aria-checked') / .disabled / getAttribute('data-value') / textContent）
  · 拦截到的**真实** resume 请求体（route handler 内 request.post_data_json()）

负向对照（N8）：把事件名故意写成 need_clarificationX（未知事件），断言卡片**不出现**，
证明 N1 的判据不是恒真。

同时内嵌「三层线格式一致性」（任务 5）静态断言：agent / Java / H5 三处契约字面一致。

退出码非零 = 有断言失败。
"""
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(name, ok, detail=''):
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


# --------------------------------------------------------------------------- SSE 构造
def sse(*frames):
    return '\n\n'.join(frames) + '\n\n'


def frame(ev, data):
    return 'event: %s\ndata: %s' % (ev, json.dumps(data, ensure_ascii=False))


PRE_TEXT = '（澄清前：模型在调用 ask_user 之前已产出的片段。）'
POST_TEXT = '（澄清后续跑：用户选「本季度」后 agent 继续生成的回答。）'
Q_TEXT = '请选择要统计的时间范围？'
OPTS = [{'value': 'month', 'label': '本月'},
        {'value': 'quarter', 'label': '本季度'},
        {'value': 'year', 'label': '本年'}]


def events_body(event_name):
    return sse(
        frame('message.delta', {'text': PRE_TEXT}),
        frame(event_name, {'question': Q_TEXT, 'suggested_options': OPTS}),
    )


def resume_body():
    return sse(
        frame('message.delta', {'text': POST_TEXT}),
        frame('message.completed', {'content': PRE_TEXT + POST_TEXT, 'usage': {'prompt_tokens': 1, 'completion_tokens': 2}}),
        frame('run.completed', {'status': 'SUCCEEDED'}),
    )


# --------------------------------------------------------------------------- 路由（单一 catch-all 分发，避免 glob 匹配歧义）
import re as _re

_RX_RUNS = _re.compile(r'/api/v1/conversations/[^/]+/runs$')
_RX_EVENTS = _re.compile(r'/api/v1/runs/[^/]+/events$')
_RX_RESUME = _re.compile(r'/api/v1/runs/[^/]+/resume$')


async def install_routes(page, st):
    async def dispatcher(route, request):
        url = request.url
        method = request.method
        st['hits'].append('%s %s' % (method, url.split('127.0.0.1:5181')[-1]))
        path = url.split('127.0.0.1:5181')[-1]
        if path.endswith('/api/v1/conversations') and method == 'POST':
            await route.fulfill(status=200, content_type='application/json',
                                body=json.dumps({'id': 'conv-test-1'}))
            return
        if _RX_RUNS.search(path) and method == 'POST':
            await route.fulfill(status=200, content_type='application/json',
                                body=json.dumps({'id': 'run-test-1'}))
            return
        if _RX_EVENTS.search(path) and method == 'GET':
            await route.fulfill(status=200, content_type='text/event-stream',
                                body=events_body(st['events_event']))
            return
        if _RX_RESUME.search(path) and method == 'POST':
            try:
                raw = request.post_data
                if callable(raw):
                    raw = await raw()
                st['resume_body'] = json.loads(raw) if raw else None
            except Exception as ex:
                st['resume_body'] = 'PARSE_ERROR:' + str(ex)
            st['resume_called'] = True
            await route.fulfill(status=200, content_type='text/event-stream',
                                body=resume_body())
            return
        # 其它（登录/会话/统计/资源…）放行到真实后端
        await route.fallback()

    await page.route('**/api/v1/**', dispatcher)


async def login(page):
    await page.goto(BASE, wait_until='domcontentloaded')
    await page.wait_for_timeout(800)
    await page.fill('#lgUser', USER)
    await page.fill('#lgPass', PWD)
    await page.click('#lgBtn')
    try:
        await page.wait_for_selector('body.auth', timeout=15000)
    except Exception as e:
        chk('登录成功', False, str(e)[:80])
        return False
    chk('登录成功（%s）' % USER, True)
    await page.wait_for_timeout(2200)
    return True


# --------------------------------------------------------------------------- 断言工具
async def card_snapshot(page):
    return await page.evaluate("""() => {
      const cards = Array.from(document.querySelectorAll('.clar-card'));
      return {
        count: cards.length,
        opts: cards.length ? Array.from(cards[0].querySelectorAll('.clar-opt')).map(b => ({
          value: b.getAttribute('data-value'),
          label: (b.querySelector('.co-label') ? b.querySelector('.co-label').textContent : ''),
          aria: b.getAttribute('aria-checked')
        })) : [],
        okDisabled: cards.length ? cards[0].querySelector('.clar-ok').disabled : null,
        done: cards.length ? cards[0].classList.contains('done') : false,
        picked: cards.length ? (cards[0].querySelector('.clar-picked') ? cards[0].querySelector('.clar-picked').textContent : null) : null,
        selValue: cards.length ? (cards[0].querySelector('.clar-opt.sel') ? cards[0].querySelector('.clar-opt.sel').getAttribute('data-value') : null) : null
      };
    }""")


# --------------------------------------------------------------------------- 主流程
async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('pageerror', lambda e: print('  [pageerror] ' + str(e)))

        st = {'events_event': 'need_clarification', 'resume_body': None,
              'resume_called': False, 'hits': []}

        if not await login(page):
            await browser.close()
            return report()

        await install_routes(page, st)

        # ===================== A. OA 形态（默认）=====================
        print('\n=== OA 形态：N0-N8 ===')
        # N0 前置：发问前（且发问后尚未到达 need_clarification）页面无常驻卡片
        n0 = await page.evaluate("() => document.querySelectorAll('.clar-card').length")
        chk('N0 前置：页面无 .clar-card 常驻元素', n0 == 0, 'count=%s' % n0)

        # 触发 OA 发送（默认 OA 形态，#oaInput 存在）
        await page.fill('#oaInput', '帮我按时间范围统计一下')
        await page.evaluate('void oaSend()')

        # 等待澄清卡出现
        try:
            await page.wait_for_selector('.clar-card', timeout=15000)
            n1 = True
        except Exception:
            n1 = False
        snap = await card_snapshot(page)
        chk('N1 OA：need_clarification 后出现恰好 1 个 .clar-card', n1 and snap['count'] == 1, snap)

        # N2 选项恰好 3 个、顺序/label 与下发一致
        ok_n2 = (len(snap['opts']) == 3 and
                 [o['value'] for o in snap['opts']] == ['month', 'quarter', 'year'] and
                 [o['label'] for o in snap['opts']] == ['本月', '本季度', '本年'])
        chk('N2 OA：选项恰好 3 个且 value/label 与下发一致', ok_n2, snap['opts'])

        # N3 初始 .clar-ok 为 disabled
        chk('N3 OA：初始 .clar-ok 为 disabled', snap['okDisabled'] is True, 'disabled=%s' % snap['okDisabled'])

        # N4 点第 2 个选项 → 单选语义
        await page.locator('.clar-opt').nth(1).click()
        await page.wait_for_timeout(150)
        snap2 = await card_snapshot(page)
        aria = [o['aria'] for o in snap2['opts']]
        ok_n4 = (aria == ['false', 'true', 'false']) and snap2['okDisabled'] is False
        chk('N4 OA：点第 2 项后 aria-checked=[false,true,false] 且确认可用',
            ok_n4, {'aria': aria, 'okDisabled': snap2['okDisabled']})

        # N5 点确认 → 捕获 resume 请求体 == {"answer":"quarter"}
        await page.locator('.clar-ok').click()
        # 轮询直到 resume 被调用
        waited = 0
        while not st['resume_called'] and waited < 10000:
            await page.wait_for_timeout(200)
            waited += 200
        rb = st['resume_body']
        ok_n5 = (isinstance(rb, dict) and rb.get('answer') == 'quarter')
        chk('N5 OA：捕获 resume 请求体 == {"answer":"quarter"}', ok_n5, 'body=%s' % rb)

        # 等待续跑 delta 落位
        try:
            await page.wait_for_function(
                "() => { const c = document.querySelector('.clar-card'); return c && c.classList.contains('done'); }",
                timeout=15000)
        except Exception:
            pass
        # 等待续跑 delta 真正落到气泡（避免与 resume 流竞态）
        try:
            await page.wait_for_function(
                "() => { const c = document.querySelector('.clar-card'); const bub = c && (c.closest('.bub.ai') || c.parentElement); return !!(bub && bub.textContent.indexOf('续跑') >= 0); }",
                timeout=15000)
        except Exception:
            pass
        # N6 续跑 delta 落到「同一气泡」（同一 .bub.ai 同时含澄清前文本与续跑文本 + 卡）
        n6 = await page.evaluate("""() => {
          const card = document.querySelector('.clar-card');
          if(!card) return {ok:false, why:'no card'};
          const bub = card.closest('.bub.ai') || card.parentElement;
          const txt = bub ? bub.textContent : '';
          return {ok: txt.indexOf('澄清前') >= 0 && txt.indexOf('续跑') >= 0,
                  hasCardInBub: !!(bub && bub.querySelector('.clar-card')),
                  len: txt.length};
        }""")
        chk('N6 OA：续跑正文与澄清前文本落在同一气泡', n6.get('ok') and n6.get('hasCardInBub'), n6)

        # N7 卡片 done + 出现 .clar-picked 且含所选 label
        snap3 = await card_snapshot(page)
        ok_n7 = (snap3['done'] is True and snap3['selValue'] == 'quarter' and
                 snap3['picked'] and '本季度' in snap3['picked'])
        chk('N7 OA：卡片 done + .clar-picked 含所选 label「本季度」',
            ok_n7, {'done': snap3['done'], 'sel': snap3['selValue'], 'picked': snap3['picked']})

        print('  [diag] ROUTE HITS (OA):', st['hits'])
        print('  [diag] resume_body=', st['resume_body'])

        # ===================== N8 负向对照（未知事件）=====================
        print('\n=== N8 负向对照：need_clarificationX 不应出卡片 ===')
        st['events_event'] = 'need_clarificationX'
        st['resume_body'] = None
        st['resume_called'] = False
        # 重载清掉 DOM 里上一轮遗留的 done 卡，使 N8 判据干净（0 张）
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(1000)
        # 重载后若已带 token 自动登录，则无需再填登录框（登录框此时不可见）
        authed = await page.evaluate("() => document.body.classList.contains('auth')")
        if not authed:
            await page.fill('#lgUser', USER)
            await page.fill('#lgPass', PWD)
            await page.click('#lgBtn')
            try:
                await page.wait_for_selector('body.auth', timeout=15000)
            except Exception:
                pass
        await page.wait_for_timeout(2000)
        before = await page.evaluate("() => document.querySelectorAll('.clar-card').length")
        await page.fill('#oaInput', '负向对照：未知事件')
        await page.evaluate('void oaSend()')
        # 给足时间让流结束（无卡片 → oaSend 直接收口）
        await page.wait_for_timeout(4000)
        after = await page.evaluate("() => document.querySelectorAll('.clar-card').length")
        chk('N8 OA：need_clarificationX 不渲染 .clar-card（0 张）', after == 0,
            'before=%s after=%s' % (before, after))

        # ===================== B. 经典形态（#msgs .bubble）=====================
        print('\n=== 经典形态：N0-N7 ===')
        # 切到经典：OA「我的」按钮 → 经典
        try:
            await page.click('#oaTabs .tab[data-view="me"]')
            await page.wait_for_timeout(500)
            await page.click('#oaMeSwitch')
            await page.wait_for_timeout(1000)
            cls = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
            chk('B0 切到经典形态（oa-mode 关闭）', cls is False, 'oa-mode=%s' % cls)
        except Exception as e:
            chk('B0 切到经典形态', False, str(e)[:80])
            await task5(None)
            await browser.close()
            return report()

        st['events_event'] = 'need_clarification'
        st['resume_body'] = None
        st['resume_called'] = False

        # 经典输入 #chatInput 位于 #page-chat：先切到会话页使其可见
        await page.evaluate("() => { if(typeof switchTabById==='function') switchTabById('page-chat'); }")
        await page.wait_for_timeout(600)
        n0c = await page.evaluate("() => document.querySelectorAll('#msgs .clar-card').length")
        chk('N0 经典：#msgs 无 .clar-card 常驻', n0c == 0, 'count=%s' % n0c)

        # 经典 send：填充 #chatInput 后触发
        await page.evaluate("""() => { const i = document.getElementById('chatInput'); if(i){ i.focus(); } }""")
        await page.fill('#chatInput', '经典形态：帮我按时间范围统计')
        await page.evaluate('void send()')
        try:
            await page.wait_for_selector('#msgs .clar-card', timeout=15000)
            n1c = True
        except Exception:
            n1c = False
        snapc = await page.evaluate("""() => {
          const cards = Array.from(document.querySelectorAll('#msgs .clar-card'));
          return {count: cards.length,
            opts: cards.length ? Array.from(cards[0].querySelectorAll('.clar-opt')).map(b => ({
              value: b.getAttribute('data-value'),
              label: (b.querySelector('.co-label') ? b.querySelector('.co-label').textContent : ''),
              aria: b.getAttribute('aria-checked')})) : [],
            okDisabled: cards.length ? cards[0].querySelector('.clar-ok').disabled : null};
        }""")
        chk('N1 经典：出现 1 个 .clar-card', n1c and snapc['count'] == 1, snapc)

        ok_n2c = (len(snapc['opts']) == 3 and
                  [o['value'] for o in snapc['opts']] == ['month', 'quarter', 'year'] and
                  [o['label'] for o in snapc['opts']] == ['本月', '本季度', '本年'])
        chk('N2 经典：选项 3 个且一致', ok_n2c, snapc['opts'])

        chk('N3 经典：初始 .clar-ok disabled', snapc['okDisabled'] is True, 'disabled=%s' % snapc['okDisabled'])

        await page.locator('#msgs .clar-opt').nth(1).click()
        await page.wait_for_timeout(150)
        snapc2 = await page.evaluate("""() => {
          const c = document.querySelector('#msgs .clar-card');
          const opts = Array.from(c.querySelectorAll('.clar-opt')).map(b => b.getAttribute('aria-checked'));
          return {opts, okDisabled: c.querySelector('.clar-ok').disabled};
        }""")
        ok_n4c = (snapc2['opts'] == ['false', 'true', 'false']) and snapc2['okDisabled'] is False
        chk('N4 经典：单选语义 + 确认可用', ok_n4c, snapc2)

        await page.locator('#msgs .clar-ok').click()
        waited = 0
        while not st['resume_called'] and waited < 10000:
            await page.wait_for_timeout(200)
            waited += 200
        rbc = st['resume_body']
        ok_n5c = (isinstance(rbc, dict) and rbc.get('answer') == 'quarter')
        chk('N5 经典：resume 请求体 == {"answer":"quarter"}', ok_n5c, 'body=%s' % rbc)

        try:
            await page.wait_for_function(
                "() => { const c = document.querySelector('#msgs .clar-card'); return c && c.classList.contains('done'); }",
                timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_function(
                "() => { const c = document.querySelector('#msgs .clar-card'); const bub = c && (c.closest('.bubble') || c.parentElement); return !!(bub && bub.textContent.indexOf('续跑') >= 0); }",
                timeout=15000)
        except Exception:
            pass
        n6c = await page.evaluate("""() => {
          const card = document.querySelector('#msgs .clar-card');
          if(!card) return {ok:false};
          const bub = card.closest('.bubble') || card.parentElement;
          const txt = bub ? bub.textContent : '';
          return {ok: txt.indexOf('澄清前') >= 0 && txt.indexOf('续跑') >= 0, hasCard: !!(bub && bub.querySelector('.clar-card'))};
        }""")
        chk('N6 经典：续跑+澄清前文本落在同一气泡', n6c.get('ok') and n6c.get('hasCard'), n6c)

        snapc3 = await page.evaluate("""() => {
          const c = document.querySelector('#msgs .clar-card');
          return {done: c.classList.contains('done'),
                  sel: c.querySelector('.clar-opt.sel') ? c.querySelector('.clar-opt.sel').getAttribute('data-value') : null,
                  picked: c.querySelector('.clar-picked') ? c.querySelector('.clar-picked').textContent : null};
        }""")
        ok_n7c = (snapc3['done'] is True and snapc3['sel'] == 'quarter' and
                  snapc3['picked'] and '本季度' in snapc3['picked'])
        chk('N7 经典：done + .clar-picked 含「本季度」', ok_n7c, snapc3)

        await task5(page)
        print('\nROUTE HITS:', st['hits'])
        await browser.close()
        return report()


# --------------------------------------------------------------------------- 任务 5：三层线格式一致性（静态）
def read(p):
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


async def task5(page):
    print('\n=== 任务 5：三层线格式一致性（静态）===')
    ask = read(os.path.join(REPO, 'agent', 'aios_ai', 'tools', 'ask_user.py'))
    facade = read(os.path.join(REPO, 'agent', 'aios_ai', 'graph', 'facade.py'))
    run_svc = read(os.path.join(REPO, 'server', 'aios-chat', 'src', 'main', 'java', 'cn', 'aios', 'chat', 'service', 'RunService.java'))
    backup = read(os.path.join(REPO, 'user-client', '_backup_index_pre_oa.html'))

    # agent：build_clarification 产出 question + suggested_options，每项 value + label
    chk('L1 agent build_clarification 含 key question',
        '"question"' in ask and 'return {"question"' in ask)
    chk('L2 agent build_clarification 含 key suggested_options',
        '"suggested_options"' in ask and 'suggested_options' in ask)
    chk('L3 agent 选项 key 为 value + label',
        '"value"' in ask and '"label"' in ask)
    # agent：facade 事件字面量 need_clarification
    chk('L4 agent facade 事件字面量 == "need_clarification"',
        'type="need_clarification"' in facade or "type='need_clarification'" in facade
        or 'need_clarification' in facade)
    # Java：EVENT_NEED_CLARIFICATION 字面量
    chk('L5 Java EVENT_NEED_CLARIFICATION == "need_clarification"',
        'EVENT_NEED_CLARIFICATION = "need_clarification"' in run_svc)
    # H5：分支比较 'need_clarification'、读 suggested_options、resume 路径 + body {answer:}
    chk('L6 H5 识别事件 "need_clarification"', "ev.event === 'need_clarification'" in backup)
    chk('L7 H5 读取 suggested_options', 'p.suggested_options' in backup)
    chk('L8 H5 resume 路径 /v1/runs/ + /resume',
        "/v1/runs/'+runId+'/resume" in backup or "/v1/runs/" in backup and "/resume" in backup)
    chk('L9 H5 resume body 含 answer', "body:JSON.stringify({answer:answer})" in backup)

    # 跨层字面量一致：三处均为 "need_clarification"
    three = ('need_clarification' in facade) and ('need_clarification' in run_svc) \
        and ("ev.event === 'need_clarification'" in backup)
    chk('L10 三层事件名字面量一致（need_clarification）', three)


def report():
    total = 0
    # 简单统计打印的 OK/FAIL 通过全局 fails 反推
    print('\n──────── 收口 ────────')
    print('失败项（共 %d）：' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
