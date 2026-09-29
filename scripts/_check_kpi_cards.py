#!/usr/bin/env python3
"""首页四张浮动指标卡（.kpi-float）自检 —— 卡片是完整形态（**不带任何尾巴/气泡尖角**）。

为什么需要这个脚本
    数字人四周那四张卡（待我审批 / 我发起的 / 知会未读 / 我的会话）是首页的固定构图。
    尾巴前后做过四套实现（写死静态三角 → 方块切角 → 自绘 SVG → 复用对话坞气泡组件），
    前两套被真实缺陷否决、后两套被口径否决，最终用户口径是**去掉这四个气泡**
    （pitfalls #105/#107 记全程）。本套件锁三件事：
      ① 四张卡仍在、且卡内**不再有任何尾巴元素**（防止尾巴从构建链里被重新带回来）；
      ② 卡片是交互 UI，矮视口下与数字人位图相交时必须渲染在插画**之上**；
      ③ console 干净。
    视口档覆盖手机常见高度与矮机（360×740）——矮视口是当初「尾巴被机器人吞掉」
    的真实现场，width-only 验证发现不了（pitfalls #107）。
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER = 'wjj_xu'
PWD = 'User@123'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_kpi')
WIDTHS = [(360, 844), (390, 844), (430, 844), (360, 740), (1280, 800)]

fails = []
errs = []


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=3, locale='zh-CN')
        page = await ctx.new_page()
        page.on('console', lambda m: errs.append('console.' + m.type + ': ' + m.text)
                if m.type == 'error' else None)
        page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))

        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.evaluate("() => localStorage.setItem('aioa_mode','oa')")
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        if not await page.query_selector('body.auth'):
            await page.fill('#lgUser', USER)
            await page.fill('#lgPass', PWD)
            await page.click('#lgBtn')
            await page.wait_for_selector('body.auth', timeout=15000)
        await page.wait_for_timeout(2600)

        # 静止态测量：r-bob / r-sway 的中间帧会污染 rect（pitfalls #98）
        await page.add_style_tag(content='.oa .r-bob,.oa .r-sway,.oa .robot-img{animation:none !important}'
                                         '.oa .kpi-float{transition:none !important}')
        await page.wait_for_timeout(400)

        chk('四张浮动卡都渲染出来了',
            await page.evaluate("() => document.querySelectorAll('.oa .kpi-float').length") == 4)

        # ① 尾巴必须彻底没有：卡内任何元素、任何 ::after/::before 都不该是三角
        left = await page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('.oa .kpi-float').forEach((c, i) => {
            if (c.querySelector('svg.tail, svg.ktail, .tail, .ktail')) out.push('k' + (i+1) + ':子元素');
            ['::after', '::before'].forEach(p => {
              const cs = getComputedStyle(c, p);
              if (cs.content && cs.content !== 'none' && cs.width !== 'auto'
                  && parseFloat(cs.width) > 2 && parseFloat(cs.height) > 2) {
                out.push('k' + (i+1) + ':' + p);
              }
            });
          });
          return out;
        }""")
        chk('四张卡都没有尾巴元素（无 .tail 子元素、无 ::after/::before 三角）', not left, left)

        for w, h in WIDTHS:
            await page.set_viewport_size({'width': w, 'height': h})
            await page.wait_for_timeout(450)
            d = await page.evaluate("""() => {
              const st = document.querySelector('.oa #oaStage').getBoundingClientRect();
              const out = {stage: [st.left, st.top, st.right, st.bottom], cards: []};
              document.querySelectorAll('.oa .kpi-float').forEach(c => {
                const r = c.getBoundingClientRect();
                const hit = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
                out.cards.push({box: [r.left, r.top, r.right, r.bottom],
                                above: !!(hit && c.contains(hit))});
              });
              return out;
            }""")
            inside = all(c['box'][0] >= d['stage'][0] - 0.5 and c['box'][2] <= d['stage'][2] + 0.5
                         for c in d['cards'])
            chk('%d×%d 四张卡都在舞台横向范围内且尺寸正常' % (w, h),
                inside and all(c['box'][2] - c['box'][0] > 80 for c in d['cards']),
                [round(c['box'][2] - c['box'][0], 1) for c in d['cards']])
            ab = [c['above'] for c in d['cards']]
            chk('%d×%d 四张卡渲染在数字人插画之上（UI 在上）' % (w, h), all(ab), ab)

        # 截图：手机整页 + 矮视口 + 桌面
        for (w, h), nm in [((390, 844), 'cards-home.png'),
                           ((360, 740), 'cards-short.png'),
                           ((1280, 800), 'cards-desktop.png')]:
            await page.set_viewport_size({'width': w, 'height': h})
            await page.wait_for_timeout(450)
            await page.screenshot(path=os.path.join(OUT, nm))

        chk('console 无 error / 无未捕获异常', not errs, errs[:2])
        await browser.close()

    print('\n失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
