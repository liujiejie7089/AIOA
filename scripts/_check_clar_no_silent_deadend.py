# -*- coding: utf-8 -*-
"""澄清卡「选了之后没下文」离线哨兵 —— Playwright + file://，不需要后端。

## 为什么要有这个哨兵

2026-10-31 用户现场截图：澄清卡上点「确认」，卡片变成「已选择：策划书.docx」，
然后整条气泡**再无任何下文** —— 用户的原话是「选择了之后并没有返回内容」。

根因不是网络失败，而是**收口逻辑静默**：`POST /v1/runs/{id}/resume` 完全可能
一点正文都不产出（模型没再产出 / 又停在不产生文本的分支 / 后端只回 run.completed）。
此时 `text` 长度不变，`if(!text)` 不成立（上一轮已有正文），`else` 分支用
`formatAnswer(同一段旧正文)` 重渲染 —— 观感就是「按钮点了没反应」。

同一处还有一个更隐蔽的坑：`onError` 把**真实原因**写进 tx 之后，`text` 仍为空串，
`if(!text)` 的空输出兜底会把它整段覆盖成「这次没有拿到任何内容」⇒ 用户永远看不到报错。

## 判据（每条都能因缺陷变红）

  R1  续跑**零正文** + 上一轮有正文 ⇒ 气泡内出现 `.sys-notes .sys-note`，
      文案含「已提交你的选择」与被选项文案（这就是用户看到的「有回音」）。
  R2  负向对照：续跑**有正文** ⇒ **不得**出现该提示，且正文真的渲染进 `.tx`
      （证明 R1 的判据不是「恒出现」，否则等于没测）。
  R3  续跑回 `run.failed` ⇒ `.tx` 必须是「生成失败：<真实原因>」，
      **不得**变成「这次没有拿到任何内容」（报错不许被兜底文案冲掉）。
  R4  首轮零正文（没有澄清卡）⇒ `.tx` 是三类原因兜底，且三类关键词都在
      （连接器 / 超时 / 数据），不能只剩一句「再问一次」。
  S1  静态契约：两形态（经典 send / OA oaSend）各有 beforeClar 比较 + appendSysNote 兜底；
      errored 三个动作齐全（声明 / 置位 / 判断），且判断写成**嵌套**形式
      —— 写成 `if(!text && !errored){...} else {...}` 会让 errored 掉进 else
      被 `formatAnswer('')` 冲成空，哨兵必须能抓到这个退化写法。

跑法：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_clar_no_silent_deadend.py

退出码非零 = 有断言失败。
"""
import asyncio
import os
import re
import sys
import urllib.parse

from playwright.async_api import async_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# AIOS_INDEX 可覆盖：负向自检要在**改坏的副本**上跑（证明判据不是恒真）
INDEX = os.environ.get('AIOS_INDEX') or os.path.join(REPO, 'user-client', 'index.html')

fails = []
oks = 0

SSE_HEADERS = {'content-type': 'text/event-stream',
               'access-control-allow-origin': '*',
               'cache-control': 'no-cache'}

# 澄清卡载荷：与 clarCardHtml 的契约一致（question + suggested_options[value,label]）
CLAR_FRAME = ('event: need_clarification\n'
              'data: {"question":"要给哪个文件？",'
              '"suggested_options":[{"value":"f-1","label":"策划书.docx"}]}\n\n')


def chk(name, ok, detail=''):
    global oks
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''), flush=True)
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


async def drive(page, resume_body, first_body='', expect_card=True):
    """跑一遍真实的 send()：首轮流 -> 澄清卡 -> 点确认 -> 续流 -> 记录收口结果。

    全程只替换 fetch 的网络层（page.route），**不替换任何业务函数** ——
    否则测的就是桩，不是被测代码。
    """
    routes = {'events': first_body, 'resume': resume_body}

    async def handler(route, request):
        url = request.url
        if url.endswith('/resume'):
            body = routes['resume']
        elif url.endswith('/events'):
            body = routes['events']
        elif re.search(r'/v1/conversations/[^/]+/runs$', url):
            await route.fulfill(status=200, headers={'content-type': 'application/json',
                                                     'access-control-allow-origin': '*'},
                                body='{"code":0,"data":{"id":"r1"}}')
            return
        elif re.search(r'/v1/conversations$', url):
            # send() 内的 ensureChatPage()/ensureDefaultChatTarget() 会重置会话态，
            # 所以不能只在外部预先塞 state.conversationId —— 这里必须能应答建会话。
            await route.fulfill(status=200, headers={'content-type': 'application/json',
                                                     'access-control-allow-origin': '*'},
                                body='{"code":0,"data":{"id":"c1"}}')
            return
        else:
            await route.fulfill(status=200, headers={'content-type': 'application/json',
                                                     'access-control-allow-origin': '*'},
                                body='{"code":0,"data":{}}')
            return
        await route.fulfill(status=200, headers=SSE_HEADERS, body=body)

    await page.route('**/v1/**', handler)
    try:
        # 复位页面状态：state.busy 可能被上一场景留在 true（send 开头就会 return）
        await page.evaluate("""() => {
          state.busy = false;
          state.conversationId = 'c1';
          state.quotaInfo = null;
          state.controller = null;
          clarPendingResolve = null;
          const box = $('msgs'); if (box) box.innerHTML = '';
        }""")

        # 输入问题并触发 send()。onclick 绑的是全局 send，直接调即可。
        await page.evaluate("""() => { $('chatInput').value = '把这个文件传上去'; }""")
        task = asyncio.ensure_future(page.evaluate("() => send()"))

        if expect_card:
            # 等澄清卡出现
            try:
                await page.wait_for_selector('.clar-card .clar-opt', timeout=5000)
                card_ok = True
            except Exception:
                card_ok = False
            if not card_ok:
                await task
                return {'card': False, 'settled': None, 'note': None, 'tx': None}

            # 点选项 -> 点确认（都走 JS click，页面此时可能处于隐藏容器，绕过可见性检查）
            await page.evaluate("""() => {
              const c = document.querySelector('.clar-card');
              c.querySelector('.clar-opt').click();
              c.querySelector('.clar-ok').click();
            }""")
        await task
    finally:
        await page.unroute('**/v1/**')

    return await page.evaluate("""() => {
      const bubbles = Array.from(document.querySelectorAll('#msgs .bubble'));
      const b = bubbles[bubbles.length - 1];
      if (!b) return {card: true, settled: null, note: null, tx: null};
      const notes = Array.from(b.querySelectorAll('.sys-notes .sys-note'))
                         .map(function(n){ return n.textContent || ''; });
      const txEl = b.querySelector('.tx');
      return {
        card: true,
        picked: (b.querySelector('.clar-picked') || {}).textContent || '',
        notes: notes,
        note: notes.length ? notes[notes.length - 1] : null,
        noteCount: notes.length,
        tx: txEl ? (txEl.textContent || '') : '',
        bubbleCount: bubbles.length
      };
    }""")


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
        # 必须等 boot() 跑完：它启动时还会写 state / 渲染首页，
        # 早于它开跑就 send()，会被它的初始化盖掉（第一版哨兵 R1 全红即此因）。
        await page.wait_for_function("() => typeof state !== 'undefined' && !!$('msgs')",
                                     timeout=8000)
        await page.wait_for_timeout(2000)
        # 哨兵不走真后端：把 base 指到一个本地不存在的域，全部由 page.route 兜住
        await page.evaluate("() => { API.base = 'https://sentinel.local'; state.token = ''; }")

        # ============ R1：续跑零正文 —— 必须给回音 ============
        print('\n=== R1：续跑零正文（用户现场复现）===')
        r1 = await drive(page,
                         resume_body='event: run.completed\ndata: {}\n\n',
                         first_body='event: message.delta\ndata: {"text":"你指的是哪个文件？"}\n\n'
                                    + CLAR_FRAME)
        chk('R1 澄清卡真实渲染并可选中', r1.get('card') is True, r1)
        chk('R1 卡片落款为「已选择」', '已选择' in (r1.get('picked') or ''), r1.get('picked'))
        note1 = r1.get('note') or ''
        chk('R1 零正文时出现系统提示（不再静默）', bool(note1), r1.get('notes'))
        chk('R1 提示说明「已提交你的选择」', '已提交你的选择' in note1, note1)
        chk('R1 提示回显被选项文案', '策划书.docx' in note1, note1)
        chk('R1 上一轮正文仍在（没被清空）', '你指的是哪个文件' in (r1.get('tx') or ''),
            r1.get('tx'))

        # ============ R2：负向对照 —— 有正文时不许乱加提示 ============
        print('\n=== R2：负向对照（续跑有正文）===')
        r2 = await drive(page,
                         resume_body='event: message.delta\ndata: {"text":"已经传到你的企业微信群了。"}\n\n'
                                     'event: run.completed\ndata: {}\n\n',
                         first_body='event: message.delta\ndata: {"text":"你指的是哪个文件？"}\n\n'
                                    + CLAR_FRAME)
        chk('R2 正文已渲染进 .tx', '已经传到你的企业微信群了' in (r2.get('tx') or ''), r2.get('tx'))
        chk('R2 有正文时**不**出现「没有新的内容」提示',
            '已提交你的选择' not in (r2.get('note') or ''), r2.get('notes'))

        # ============ R3：报错不许被兜底文案冲掉 ============
        print('\n=== R3：续跑回 run.failed（本轮已有正文）===')
        r3 = await drive(page,
                         resume_body='event: run.failed\ndata: 连接器 qq_mail 调用失败：401\n\n',
                         first_body='event: message.delta\ndata: {"text":"正在为你查询。"}\n\n'
                                    + CLAR_FRAME)
        tx3 = r3.get('tx') or ''
        chk('R3 上一轮正文被保留', '正在为你查询' in tx3, tx3)
        chk('R3 真实原因挂在正文下方（.sys-note）',
            '401' in (r3.get('note') or ''), r3.get('notes'))
        chk('R3 报错标注为「本轮生成中断」',
            '本轮生成中断' in (r3.get('note') or ''), r3.get('note'))
        chk('R3 真实原因未被空输出兜底覆盖',
            '这次没有拿到任何内容' not in tx3, tx3)

        print('\n=== R3b：首轮就 run.failed（无正文）===')
        r3b = await drive(page,
                          resume_body='event: run.completed\ndata: {}\n\n',
                          first_body='event: run.failed\ndata: 模型服务不可用：502\n\n',
                          expect_card=False)
        tx3b = r3b.get('tx') or ''
        chk('R3b 无正文时报错写进 .tx', ('生成失败' in tx3b) and ('502' in tx3b), tx3b)
        chk('R3b 无正文时**不**退回三类原因兜底',
            '这次没有拿到任何内容' not in tx3b, tx3b)

        # ============ R4：首轮零正文 —— 三类原因兜底 ============
        print('\n=== R4：首轮零正文 ===')
        r4 = await drive(page,
                         resume_body='event: run.completed\ndata: {}\n\n',
                         first_body='event: run.completed\ndata: {}\n\n',
                         expect_card=False)
        tx4 = r4.get('tx') or ''
        chk('R4 .tx 给出空输出说明', '这次没有拿到任何内容' in tx4, tx4)
        for kw in ('连接器', '超时', '数据'):
            chk('R4 三类原因含「%s」' % kw, kw in tx4, tx4)
        chk('R4 不再只有「再问一次」', '再问一次' not in tx4, tx4)

        await browser.close()

    # ============ S1：静态契约 ============
    print('\n=== S1：静态契约 ===')
    with open(INDEX, 'r', encoding='utf-8') as f:
        src = f.read()

    # 两形态各一处：beforeClar 快照 + 零新增时的 appendSysNote 兜底
    chk('S1 两形态都有 beforeClar 快照', src.count('beforeClar = text.length') == 2,
        'count=%d' % src.count('beforeClar = text.length'))
    chk('S1 两形态都有「已提交你的选择」兜底',
        src.count("已提交你的选择") == 2, 'count=%d' % src.count('已提交你的选择'))
    chk('S1 beforeClar 比较是严格零新增',
        src.count('if(text.length === beforeClar)') == 2,
        'count=%d' % src.count('if(text.length === beforeClar)'))

    # errored：声明（各 1）、置位（各 1）、判断（各 1）
    chk('S1 errored 两形态都声明', src.count('errored = false') == 2,
        'count=%d' % src.count('errored = false'))
    chk('S1 errored 两形态都在 onError 置位', src.count('errored = true') == 2,
        'count=%d' % src.count('errored = true'))
    chk('S1 报错原因两形态都记账（errMsg）', src.count("errMsg = (err && err.message) || '未知错误'") == 2,
        'count=%d' % src.count('errMsg = (err'))
    # 退化写法：`if(!text && !errored){` —— errored 会掉进 else 被 formatAnswer('') 冲成空
    chk('S1 未退化成 if(!text && !errored){（会掉进 else 把报错冲成空）',
        'if(!text && !errored){' not in src)
    chk('S1 两形态都把报错补在正文下方（appendSysNote）',
        src.count("appendSysNote(bubble, '本轮生成中断：' + errMsg)") == 2,
        'count=%d' % src.count('本轮生成中断'))

    chk('S1 空输出兜底三类原因两形态各一份',
        src.count('这次没有拿到任何内容。可能是：') == 2,
        'count=%d' % src.count('这次没有拿到任何内容。可能是：'))

    print('\n' + ('=' * 60))
    if fails:
        print('FAILED %d / %d' % (len(fails), oks + len(fails)))
        for x in fails:
            print('  - ' + x)
        return 1
    print('ALL PASS  %d 项' % oks)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
