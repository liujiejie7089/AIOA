#!/usr/bin/env python3
"""首页四张浮动指标卡（.kpi-float）的三角必须指向数字人 —— 几何 + 像素自检。

为什么需要这个脚本
    数字人四周那四张卡（待我审批 / 我发起的 / 知会未读 / 我的会话）是首页的固定构图。
    卡片位置可以写死，但**三角的落点与朝向必须是算出来的**：数字人随视口宽度居中、
    卡片贴两端，二者的相对角度逐宽度都不同，写死的角度换个宽度就不指向数字人了。
    三角的演进（三次教训，详见 pitfalls #105）：
      ① 四组写死的静态 CSS 三角 —— k1/k2 朝上、k3/k4 朝下，**四张全背对数字人**；
      ② 「转 45° 的方块压卡片边切角」—— rotate 偏角后切出**斜方块**（用户报「出错了」）；
      ③ 现为**真·SVG 三角形**：两条 path 的 d 由 oaLayoutTails() 按几何直接算出
         （底边沿卡片边、中点内收 1.5px；顶点 12px 指向数字人），元素不旋转。

⚠ 判据独立于页面内的算法：直接量 path 里的三个顶点坐标（底边两点 + 顶点），
   自己按「宿主中心 → 数字人中心」重算方向角再比对，避免自证。
   path 的 d 就是渲染的几何本体（无变换参与），读它 = 读「渲染出来的事实」。
⚠ 一并在三个视口宽度上验：写死的角度在 390 上可能恰好对，换个宽度就偏了；
   多宽度同时证明「角度是算的」与「resize 后重新落位」两条。
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
WIDTHS = [360, 390, 430]

fails = []
errs = []

# 每张卡「朝数字人那一侧」的边：上两张贴下边、下两张贴上边
EXPECT_SIDE = {'k1': 'B', 'k2': 'B', 'k3': 'T', 'k4': 'T'}

MEASURE_JS = """() => {
  const rr = document.querySelector('#oaRobot').getBoundingClientRect();
  const out = {robot: [rr.left, rr.top, rr.right, rr.bottom],
               A: {x: rr.left + rr.width/2, y: rr.top + rr.height/2}, cards: {}};
  ['k1','k2','k3','k4'].forEach(k => {
    const el = document.querySelector('.oa .kpi-float.' + k);
    const r = el.getBoundingClientRect();
    const t = el.querySelector('.ktail');
    const cs = getComputedStyle(t);
    const d = t.querySelector('.ktf').getAttribute('d') || '';
    // ktf 的 d = M b0 L b1 L apex Z → 6 个数；局部坐标系 = 原点在贴边点、与屏幕 1:1（元素不旋转）
    const nums = (d.match(/-?\\d+\\.?\\d*/g) || []).map(Number);
    out.cards[k] = {
      box: [r.left, r.top, r.right, r.bottom],
      cx: r.left + r.width/2, cy: r.top + r.height/2,
      // 落点：.ktail 的 left/top 相对 padding box，补回 1px 边框
      bx: r.left + 1 + parseFloat(cs.left), by: r.top + 1 + parseFloat(cs.top),
      pts: nums
    };
  });
  return out;
}"""


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


def verify(width, d):
    """按宽度逐卡核对：贴边正确 + 顶点指向数字人 + 是真三角形且底边贴在卡片边上。"""
    A = d['A']
    NU_VEC = {'T': (0, -1), 'B': (0, 1), 'L': (-1, 0), 'R': (1, 0)}
    print('— 视口 %dpx：数字人盒 %s 中心 (%.1f, %.1f)'
          % (width, [round(v, 1) for v in d['robot']], A['x'], A['y']))
    for k in ['k1', 'k2', 'k3', 'k4']:
        c = d['cards'][k]
        box = c['box']
        chk('%dpx %s 三角 path 有 3 个顶点（ktf 的 d 含 6 个数）' % (width, k),
            len(c['pts']) == 6, c['pts'])
        if len(c['pts']) != 6:
            continue
        b0x, b0y, b1x, b1y, ax, ay = c['pts']
        # ② 顶点朝向：直接量 path 里的顶点向量 —— 不换算任何页面公式，判据与实现不同源
        apex = math.degrees(math.atan2(ay, ax))
        want = math.degrees(math.atan2(A['y'] - c['cy'], A['x'] - c['cx']))
        err = (apex - want + 180) % 360 - 180
        dist = {'L': c['bx'] - box[0], 'T': c['by'] - box[1],
                'R': box[2] - c['bx'], 'B': box[3] - c['by']}
        side = min(dist.items(), key=lambda t: t[1])[0]
        nx, ny = NU_VEC[side]
        # ③ 形状不变量（直接量三个顶点，不再依赖变换矩阵）：
        #    · 底边与卡片边平行 ⇔ 底边垂直于外法线（两底点沿法线方向的投影相等）；
        #    · 底边中点内收 1~2.5px（盖住卡片描边，尾巴才像从卡片上长出来的）；
        #    · 顶点在卡外 10px 以上；面积 ≥ 60px²（非退化）。
        base_n0 = b0x * nx + b0y * ny
        base_n1 = b1x * nx + b1y * ny
        base_mid_n = (base_n0 + base_n1) / 2
        apex_n = ax * nx + ay * ny
        area = abs((b1x - b0x) * (ay - b0y) - (b1y - b0y) * (ax - b0x)) / 2
        print('  %s 卡盒=%s 落点=(%.1f,%.1f) 贴边=%s 顶点=%.1f° 目标=%.1f° 误差=%.2f° 面积=%.1f'
              % (k, [round(v, 1) for v in box], c['bx'], c['by'], side, apex, want, err, area))
        chk('%dpx %s 三角贴在朝数字人那一侧（期望 %s）' % (width, k, EXPECT_SIDE[k]),
            side == EXPECT_SIDE[k], side)
        chk('%dpx %s 三角顶点指向数字人（误差 ≤ 0.5°）' % (width, k), abs(err) <= 0.5, '%.2f°' % err)
        chk('%dpx %s 底边与卡片边平行（两底点法向投影差 ≤ 0.3）' % (width, k),
            abs(base_n0 - base_n1) <= 0.3, '差 %.3f' % abs(base_n0 - base_n1))
        chk('%dpx %s 底边中点内收 1~2.5px（盖住卡片描边）' % (width, k),
            -2.5 <= base_mid_n <= -1.0, '内收 %.2f' % -base_mid_n)
        chk('%dpx %s 顶点探出卡外 ≥ 10px 且面积 ≥ 60px²（真三角形）' % (width, k),
            apex_n >= 10 and area >= 60, '探出 %.1f 面积 %.1f' % (apex_n, area))


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

        chk('前置：四张浮动卡已渲染',
            await page.evaluate("() => document.querySelectorAll('.oa .kpi-float').length") == 4)
        # 三角是否被脚本落位过（ktf 的 d 为空 ⇒ 停在初始状态，等于没指向数字人）
        placed = await page.evaluate("""() => [...document.querySelectorAll('.oa .kpi-float .ktf')]
            .map(p => (p.getAttribute('d') || '').trim())""")
        chk('前置：四张卡的三角都已被脚本画出（ktf 的 d 非空）',
            len(placed) == 4 and all(placed), placed)

        for w in WIDTHS:
            await page.set_viewport_size({'width': w, 'height': 844})
            await page.wait_for_timeout(450)      # resize 事件里 oaLayoutTails() 重新落位
            verify(w, await page.evaluate(MEASURE_JS))

        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_timeout(450)
        await page.screenshot(path=os.path.join(OUT, 'check-home.png'))
        # 逐卡放大（含卡外 14px 余量）：三角朝向是否「看得对」最终还是要人眼过一遍
        for k in ['k1', 'k2', 'k3', 'k4']:
            el = await page.query_selector('.oa .kpi-float.' + k)
            bb = await el.bounding_box()
            await page.screenshot(path=os.path.join(OUT, 'card-%s.png' % k),
                                  clip={'x': bb['x'] - 14, 'y': bb['y'] - 14,
                                        'width': bb['width'] + 28, 'height': bb['height'] + 28})

        # 数字人上浮到波峰时，卡片不得压到它的像素上（z 序上机器人后绘制，会盖住卡片）
        await page.add_style_tag(content='.oa .r-bob{animation:none !important;'
                                         'transform:translateY(-8px) !important}')
        await page.wait_for_timeout(350)
        overlap = await page.evaluate("""() => {
          const img = document.querySelector('.oa .robot-img');
          const c = document.createElement('canvas');
          c.width = img.naturalWidth; c.height = img.naturalHeight;
          const g = c.getContext('2d'); g.drawImage(img, 0, 0);
          const d = g.getImageData(0, 0, c.width, c.height).data;
          const ir = img.getBoundingClientRect();      // 含 transform，即波峰位置
          const sx = c.width / ir.width, sy = c.height / ir.height;
          const out = {};
          document.querySelectorAll('.oa .kpi-float').forEach((el, i) => {
            const r = el.getBoundingClientRect();
            const x0 = Math.max(0, Math.floor((r.left - ir.left) * sx));
            const x1 = Math.min(c.width - 1, Math.ceil((r.right - ir.left) * sx));
            const y0 = Math.max(0, Math.floor((r.top - ir.top) * sy));
            const y1 = Math.min(c.height - 1, Math.ceil((r.bottom - ir.top) * sy));
            let hit = 0;
            for (let y = y0; y <= y1; y++) {
              for (let x = x0; x <= x1; x++) if (d[(y * c.width + x) * 4 + 3] > 12) hit++;
            }
            out['k' + (i + 1)] = hit;
          });
          return out;
        }""")
        await page.screenshot(path=os.path.join(OUT, 'check-home-peak.png'))
        chk('波峰：数字人上浮 8px 时与四张卡零像素重叠',
            all(v == 0 for v in overlap.values()), overlap)

        chk('console 无 error / 无未捕获异常', not errs, errs[:2])
        await browser.close()

    print('\n失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
