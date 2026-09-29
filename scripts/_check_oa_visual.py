#!/usr/bin/env python3
"""新版形态「视觉令牌是否真的落到页面上」自检（Playwright + msedge 无头，390x844 @2x）。

为什么需要这个脚本
    _oa_polish.css 是一层「覆盖」：它能否生效取决于 CSS 层叠（同权重看先后、
    异权重看 specificity）。把令牌的值改对了，不等于页面上的元素真的变了 ——
    被更高权重压住、被内联样式盖掉、选择器拼错，三种情况都会静默失效。
    因此这里一律读浏览器算出来的 computed style，而不是读样式表里写了什么。

⚠ 探针必须限定在 #oaRoot 内，且**不得留可见性回退**
    经典与新版的类名大量重名（card / muted / tabbar / empty …），而经典标记在
    DOM 里**排在 #oaRoot 之前**。裸用 document.querySelector('.card') 会挑到经典那个，
    于是「经典没改」会被读成「新版没改」—— 这是本脚本第一版踩过的坑。
    第二版把 `all.find(vis) || all[0]` 当成修复，其实只挡住了一半：**回退分支
    `all[0]` 恰恰就是经典元素**。首页上 `.card` / `.empty div` 一个都不可见，
    于是断言量的是一批 display:none 的经典节点（吃 :root 旧令牌），
    报出「阴影只有 1 层 / 对比度 2.60」的假缺陷，而新版其实早已改对。
    因此：① 选择器一律加 `OAROOT` 前缀；② 挑不到可见元素即记 missing 并**跳过**，
    不回退、也不判失败（本页没这个元素，断言不成立也不该判红）。
    同理，容器内可能有 display:none 的同类元素（#oaStop 就是），只能挑可见的那个。

判定口径（按「层角色 → 梯级」逐层验，不是只数几个样例）
    A 阴影梯级   —— 平铺层=无影；卡片/抬起/浮动/覆盖各落在预期梯级，且为「双层」结构
    B 文字对比度 —— 正文级文字（<18.66px）对实际背景 ≥ 4.5:1，大字号 ≥ 3.0:1
    C 品牌填充   —— 白字压品牌底 ≥ 4.5:1
    D 品牌面     —— 头部渐变已避开最亮端 #12b39a（白字仅 2.64:1）
    E 命中区     —— 外壳与主操作 ≥ 44px

退出码非零 = 有断言失败。
"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'

fails = []
skips = []

OAROOT = '#oaRoot '   # 新版唯一容器：探针一律在此范围内取元素（见上文 ⚠）


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name,
                         (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


# 探针：一律在 #oaRoot 内取「可见」的那个；量不到就标 missing（由调用方决定跳过还是失败）
PROBE = r"""() => {
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const SCOPE = '__OAROOT__';
  const pick = (sel) => {
    // 只在新版容器内找，且只认可见的那个。**不回退到 all[0]**：
    // 那会挑到 #oaRoot 之前的经典元素，把「新版已改对」读成「没改」。
    const all = [...document.querySelectorAll(SCOPE + sel)];
    return all.find(vis) || null;
  };
  const lum = (c) => {
    const m = String(c).match(/\d+(\.\d+)?/g) || ['0','0','0'];
    const [r,g,b] = m.slice(0,3).map(Number).map(v => {
      v /= 255; return v <= 0.04045 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4);
    });
    return 0.2126*r + 0.7152*g + 0.0722*b;
  };
  const cr = (a, b) => {
    const la = lum(a), lb = lum(b);
    const hi = Math.max(la, lb), lo = Math.min(la, lb);
    return +(((hi + 0.05) / (lo + 0.05))).toFixed(2);
  };
  const bgOf = (el) => {
    let n = el;
    while (n && n.nodeType === 1) {
      const bg = getComputedStyle(n).backgroundColor;
      if (bg && bg !== 'transparent' && !/,\s*0\)$/.test(bg)) return bg;
      n = n.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor;
  };
  const info = (sel) => {
    const el = pick(sel);
    if (!el) return {sel, missing: true};
    const cs = getComputedStyle(el);
    const bg = bgOf(el);
    const sh = cs.boxShadow || 'none';
    const r = el.getBoundingClientRect();
    return {sel, inOA: !!el.closest('#oaRoot'), fg: cs.color, bg, ratio: cr(cs.color, bg),
            size: +parseFloat(cs.fontSize).toFixed(2),
            bold: (parseInt(cs.fontWeight, 10) || 400) >= 700,
            shadow: sh, layers: sh === 'none' ? 0 : sh.split(/,(?![^(]*\))/).length,
            w: Math.round(r.width), h: Math.round(r.height),
            img: cs.backgroundImage};
  };
  const list = (sels) => sels.map((s) => info(s));
  return {
    elev: list(['.lrow', '.card', '.task-card', '.kpi-float', '.robot-tag',
                '.composer .box', '.searchbar', '.drawer', '.sheet']),
    txt: list(['.assist-hint', '.dnav-label', '.kpi-float .k-label',
               '.muted', '.sec-title', '.sec-title .more', '.tab.on',
               '.empty div', '.lrow .t2']),
    fill: list(['.cbtn.send', '.ab-pill', '.org-chip.on']),
    panel: list(['.profile', '.layout-btn']),
    hit: list(['.ab-btn', '.cbtn.send', '.org-chip', '.icon-act', '.tab', '.sheet-cancel']),
    brandShape: list(['.kb-tile .ic', '.recent-item .ri-ico', '.rail-item.on'])
  };
}"""

PROBE = PROBE.replace('__OAROOT__', OAROOT)   # 作用域只有一个来源，避免选择器与常量各写一份


async def goto_view(page, view):
    await page.click('#oaTabs .tab[data-view="%s"]' % view)
    await page.wait_for_timeout(900)


async def probe(page):
    return await page.evaluate(PROBE)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2)
        page = await ctx.new_page()
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))

        await page.goto(BASE, wait_until='domcontentloaded')
        # 只验样式，不验默认形态（默认形态由 _e2e_oa.py 负责），故显式落记忆
        await page.evaluate("() => localStorage.setItem('aioa_mode', 'oa')")
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        await page.wait_for_selector('body.auth', timeout=15000)
        await page.wait_for_timeout(3000)
        om = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
        chk('前置：已进入新版形态', om is True, 'oa-mode=%s' % om)

        agg = {}
        stages = [('首页', 'home'), ('我的', 'me'), ('知识库', 'kb')]
        for label, view in stages:
            await goto_view(page, view)
            r = await probe(page)
            for k, v in r.items():
                agg.setdefault(k, {})
                for e in v:
                    if not e.get('missing') and e['sel'] not in agg[k]:
                        agg[k][e['sel']] = dict(e, stage=label)
        # 抽屉（覆盖层）单独开一次。注意顶栏左键只在**首页**是「打开目录」，
        # 在子页它是「返回」（_oa_app.js oaRender: isHomeTab = S.view==='home'）——
        # 不先回首页就点它，抽屉根本不开，覆盖层那一级会被静默漏验。
        await goto_view(page, 'home')
        await page.click('#oaLeft')
        await page.wait_for_timeout(700)
        opened = await page.evaluate(
            "() => document.querySelector('#oaRoot').classList.contains('drawer-open')")
        chk('前置：抽屉已打开（覆盖层那一级要验得到）', opened is True)
        r = await probe(page)
        for e in r['elev']:
            if e['sel'] == '.drawer' and not e.get('missing'):
                agg['elev']['.drawer'] = dict(e, stage='抽屉')
        # 用 Esc 关：抽屉开启时遮罩中心被抽屉本体盖住，点遮罩会被判为不可点
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(500)

        # 探针口径自检：凡参与判定的元素必须都在新版容器内。
        # 这不是恒真断言 —— 作用域一旦被改回裸选择器，就会捞进经典节点，这里立刻变红。
        outside = sorted({s for d in agg.values() for s, e in d.items() if not e.get('inOA')})
        chk('探针口径：参与判定的元素全部在 #oaRoot 内', not outside, outside)

        # ---- A. 阴影梯级 ----
        print('\n--- A. 阴影梯级（按层角色逐层验） ---')
        RUNG = {'.lrow': ('平铺', 0), '.card': ('卡片', 2), '.task-card': ('卡片', 2),
                '.kpi-float': ('浮动', 2), '.robot-tag': ('浮动', 2),
                '.composer .box': ('浮动', 2), '.searchbar': ('浮动', 2),
                '.drawer': ('覆盖', 2), '.sheet': ('覆盖', 2)}
        for sel, (role, minlayer) in RUNG.items():
            e = agg['elev'].get(sel)
            if not e:
                skips.append('A %s（%s）本页未出现，未验' % (sel, role))
                print('   [skip] %-16s 未出现' % sel)
                continue
            print('   %-16s %-4s 层数=%d  %s' % (sel, role, e['layers'], e['shadow'][:70]))
            if minlayer == 0:
                chk('A %s 属平铺层（不给阴影）' % sel, e['layers'] == 0, e['shadow'])
            else:
                chk('A %s 属%s层且为双层结构' % (sel, role), e['layers'] >= minlayer,
                    '层数=%d' % e['layers'])
        # 梯子要「读得出来」：卡片有影、同一卡片内的行没有
        c, l = agg['elev'].get('.card'), agg['elev'].get('.lrow')
        if c and l:
            chk('A 梯级可辨：卡片有影而行内平铺（两者不同级）',
                c['layers'] >= 2 and l['layers'] == 0)

        # ---- B. 文字对比度 ----
        print('\n--- B. 文字对比度 ---')
        for sel, e in agg['txt'].items():
            big = e['size'] >= 18.66 or (e['bold'] and e['size'] >= 14)
            need = 3.0 if big else 4.5
            print('   %-22s %5.2f  需≥%.1f  %.1fpx  %s' % (sel, e['ratio'], need, e['size'], e['stage']))
            chk('B %s 对比度 %.2f ≥ %.1f' % (sel, e['ratio'], need), e['ratio'] >= need,
                '%s on %s' % (e['fg'], e['bg']))

        # ---- C. 品牌填充 ----
        print('\n--- C. 品牌填充：白字压品牌底 ---')
        for sel, e in agg['fill'].items():
            print('   %-16s %s on %s = %.2f' % (sel, e['fg'], e['bg'], e['ratio']))
            chk('C %s 白字 ≥ 4.5' % sel, e['ratio'] >= 4.5, e['ratio'])

        # ---- D. 品牌面 ----
        print('\n--- D. 品牌面：头部渐变已避开最亮端 ---')
        for sel, e in agg['panel'].items():
            print('   %-14s bg=%s img=%s' % (sel, e['bg'], (e['img'] or 'none')[:70]))
        p = agg['panel'].get('.profile')
        if p:
            chk('D1 .profile 未再用最亮端 #12b39a（白字仅 2.64:1）',
                '18, 179, 154' not in (p['img'] or ''))
        b = agg['panel'].get('.layout-btn')
        if b:
            chk('D2 .layout-btn = 白底 + 品牌墨字', '255, 255, 255' in b['bg'] and b['ratio'] >= 4.5,
                '%s on %s = %s' % (b['fg'], b['bg'], b['ratio']))
        for sel, e in agg['brandShape'].items():
            print('   %-22s %5.2f（图形阈值 3.0）' % (sel, e['ratio']))
            chk('D %s 图形对比度 ≥ 3.0' % sel, e['ratio'] >= 3.0, e['ratio'])

        # ---- E. 命中区 ----
        print('\n--- E. 命中区 ≥ 44px ---')
        for sel, e in agg['hit'].items():
            print('   %-16s %sx%s  %s' % (sel, e['w'], e['h'], e['stage']))
            chk('E %s 高度 ≥ 44' % sel, e['h'] >= 44, e['h'])

        chk('前置：console 无未捕获异常', not errs, errs[:2])
        await browser.close()

    if skips:
        print('\n未验（元素未出现，不算通过也不算失败）：')
        for s in skips:
            print('  - ' + s)
    print('\n失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
