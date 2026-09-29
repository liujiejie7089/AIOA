#!/usr/bin/env python3
"""首页四张浮动指标卡（.kpi-float）的尾巴必须是对话坞气泡的**同一个尾巴组件**，
且落点在边上（不楔转角）、顶点指向数字人 —— 几何 + 像素自检。

为什么需要这个脚本
    数字人四周那四张卡（待我审批 / 我发起的 / 知会未读 / 我的会话）是首页的固定构图。
    尾巴的演进（四轮，详见 pitfalls #105）：
      ① 四组写死的静态 CSS 三角 —— 四张全背对数字人；
      ② 「转 45° 的方块压边切角」只 rotate —— 切出斜方块（用户报「出错了」）；
      ③ 自绘 SVG 三角（rotate+skew / 直接画 path）—— 1x 下像折角，被否决；
      ④ 终版：**复用对话坞气泡的尾巴组件**（.tail，13×13 旋转三角，用户口径
         「用气泡组件来生成」），落点沿边收进离转角 ≥14px 后重新指向数字人。
    为什么必须收进：桌面宽度下「卡片中心 → 数字人」射线恰好从卡片**转角**穿出
    （1280px 实测四个落点离转角全部 0.0px），尾巴楔在角上读不出「长在边上」；
    手机宽度（360–430）落点在边中部附近，所以只测手机宽度发现不了（pitfalls #106）。

⚠ 判据独立于页面内的算法：尾巴朝向从 computed `--tail-angle` 减去组件基准态
   （13×13 path 顶点朝上 = 屏幕角 −90°）得到，与「最终落点 → 数字人」方向比对；
   落点从 computed `--tail-x/--tail-y` 读回。不引用页面里的任何中间量。
⚠ 多宽度（360/390/430 手机 + 1280×800 桌面）同时验：角度必须是算的、
   resize 后重新落位、且桌面宽度下不楔转角。
"""
import asyncio
import math
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER = 'wjj_xu'
PWD = 'User@123'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_kpi')
WIDTHS = [(360, 844), (390, 844), (430, 844), (360, 740), (1280, 800)]
TAIL_D = 'M6.5 0.5 12.5 12.5 0.5 12.5z'   # 对话坞气泡尾巴组件的 path 签名
INSET = 14                                 # 与 _oa_app.js 的 TAIL_INSET 同值

fails = []
errs = []

# 每张卡「朝数字人那一侧」的边：上两张贴下边、下两张贴上边（手机与桌面实测一致）
EXPECT_SIDE = {'k1': 'B', 'k2': 'B', 'k3': 'T', 'k4': 'T'}

MEASURE_JS = """() => {
  // 同一帧内先刷新落位再测量：resize 后若布局产物（图片解码等）晚于 resize 事件稳定，
  // 分两次取会拿到「旧落位 + 新几何」的错位快照（本轮实测数字人位置差 4px ⇒ 朝向差 0.9°）
  oaLayoutTails();
  const num = s => { const v = parseFloat(s); return isNaN(v) ? NaN : v; };
  const rr = document.querySelector('#oaRobot').getBoundingClientRect();
  const out = {robot: [rr.left, rr.top, rr.right, rr.bottom],
               A: {x: rr.left + rr.width/2, y: rr.top + rr.height/2}, cards: {}};
  ['k1','k2','k3','k4'].forEach(k => {
    const el = document.querySelector('.oa .kpi-float.' + k);
    const r = el.getBoundingClientRect();
    const t = el.querySelector('.tail');
    const cs = getComputedStyle(el);
    out.cards[k] = {
      box: [r.left, r.top, r.right, r.bottom],
      w: r.width, h: r.height,
      d: t ? (t.querySelector('path.tf').getAttribute('d') || '') : null,
      np: t ? t.querySelectorAll('path').length : 0,
      tx: num(cs.getPropertyValue('--tail-x')),
      ty: num(cs.getPropertyValue('--tail-y')),
      ang: num(cs.getPropertyValue('--tail-angle'))
    };
  });
  return out;
}"""


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


def verify(width, d):
    """按宽度逐卡核对：组件同源 + 贴边不楔角 + 顶点指向数字人。"""
    A = d['A']
    print('— 视口 %dpx：数字人盒 %s 中心 (%.1f, %.1f)'
          % (width, [round(v, 1) for v in d['robot']], A['x'], A['y']))
    for k in ['k1', 'k2', 'k3', 'k4']:
        c = d['cards'][k]
        # ① 组件同源：填充 path 的签名必须与对话坞气泡尾巴完全一致（是复用，不是又画一个）；
        #    另有一条开放 path 只描两条斜边（整周描边会把底边线画进卡片内部）
        chk('%dpx %s 尾巴是气泡组件本体（填充 path d 与 .bub .tail 一致）' % (width, k),
            c['d'] == TAIL_D, c['d'])
        chk('%dpx %s 尾巴为双 path（闭合填充 + 开放描边）' % (width, k), c['np'] == 2, c['np'])
        if c['d'] != TAIL_D:
            continue
        # ② 落点：computed --tail-x/y 相对 padding box，补回 1px 边框
        ax_ = c['box'][0] + 1 + c['tx']
        ay_ = c['box'][1] + 1 + c['ty']
        box = c['box']
        dist = {'L': ax_ - box[0], 'T': ay_ - box[1],
                'R': box[2] - ax_, 'B': box[3] - ay_}
        side = min(dist.items(), key=lambda t: t[1])[0]
        # ③ 贴边、且沿边收进离转角 ≥ INSET（13×13 组件半宽 6.5，14 才容得下整个组件）
        if side in ('T', 'B'):
            along, edge = ax_ - box[0], c['w']
        else:
            along, edge = ay_ - box[1], c['h']
        print('  %s 卡盒=%s 落点=(%.1f,%.1f) 贴边=%s 沿边位置=%.1f/%.1f 朝向角=%s'
              % (k, [round(v, 1) for v in box], ax_, ay_, side, along, edge, c['ang']))
        chk('%dpx %s 尾巴贴在朝数字人那一侧（期望 %s）' % (width, k, EXPECT_SIDE[k]),
            side == EXPECT_SIDE[k], side)
        chk('%dpx %s 尾巴不楔转角（沿边位置在 [%d, %.0f] 内）' % (width, k, INSET, edge - INSET),
            INSET - 0.5 <= along <= edge - INSET + 0.5, '沿边 %.1f' % along)
        # ④ 顶点朝向：组件基准态顶点朝上（−90°），旋转后 = ang − 90；
        #    与「最终落点 → 数字人」比对（落点收进过，必须从落点算，不能从卡片中心算）
        apex = c['ang'] - 90.0
        want = math.degrees(math.atan2(A['y'] - ay_, A['x'] - ax_))
        err = (apex - want + 180) % 360 - 180
        chk('%dpx %s 尾巴顶点指向数字人（误差 ≤ 0.5°）' % (width, k), abs(err) <= 0.5, '%.2f°' % err)


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
        await page.add_style_tag(content='.oa .r-bob,.oa .robot-img{animation:none !important}'
                                         '.oa .kpi-float{transition:none !important}')
        await page.wait_for_timeout(400)

        chk('前置：四张卡都内嵌了气泡尾巴组件',
            await page.evaluate("() => document.querySelectorAll('.oa .kpi-float svg.tail').length") == 4)

        for w, h in WIDTHS:
            await page.set_viewport_size({'width': w, 'height': h})
            await page.wait_for_timeout(450)      # resize 事件里 oaLayoutTails() 重新落位
            verify(w, await page.evaluate(MEASURE_JS))

        # 手机宽度整页 + 逐卡放大（含卡外 14px 余量）：「看得对」最终要人眼过一遍
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_timeout(450)
        await page.screenshot(path=os.path.join(OUT, 'check-home.png'))
        for k in ['k1', 'k2', 'k3', 'k4']:
            el = await page.query_selector('.oa .kpi-float.' + k)
            bb = await el.bounding_box()
            await page.screenshot(path=os.path.join(OUT, 'card-%s.png' % k),
                                  clip={'x': bb['x'] - 14, 'y': bb['y'] - 14,
                                        'width': bb['width'] + 28, 'height': bb['height'] + 28})
        # 桌面宽度整页：用户实际看到的形态
        await page.set_viewport_size({'width': 1280, 'height': 800})
        await page.wait_for_timeout(450)
        await page.screenshot(path=os.path.join(OUT, 'check-home-desktop.png'))

        # 数字人上浮到波峰时：卡片（含尾巴）必须仍渲染在机器人**之上** ——
        # 卡片是交互 UI、机器人是装饰插画，重叠时 UI 在上（z-index:2）。
        # 旧断言「位图与卡片零像素重叠」只在 844 高成立；360×740 等矮视口下
        # 机器人 bitmap 本就与卡片矩形相交，靠 z 序保证可读性才是正确不变量。
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_timeout(450)
        await page.add_style_tag(content='.oa .r-bob{animation:none !important;'
                                         'transform:translateY(-8px) !important}')
        await page.wait_for_timeout(350)
        above = await page.evaluate("""() => {
          const out = {};
          document.querySelectorAll('.oa .kpi-float').forEach((el, i) => {
            const r = el.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
            out['k' + (i + 1)] = !!(hit && el.contains(hit));
          });
          return out;
        }""")
        await page.screenshot(path=os.path.join(OUT, 'check-home-peak.png'))
        chk('波峰：四张卡渲染在机器人之上（elementFromPoint 命中卡片自身）',
            all(above.values()), above)

        chk('console 无 error / 无未捕获异常', not errs, errs[:2])
        await browser.close()

    print('\n失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
