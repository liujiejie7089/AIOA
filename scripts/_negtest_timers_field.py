#!/usr/bin/env python3
"""负向测试：证明 F3a 断言「启停文案与接口 on 同源」不是恒真断言。

做法：在真实页面里把 state.workers 的 on 字段改名为 enabled（复现旧缺陷），
再调用 renderTimers() 重绘，然后用与 _e2e_oa.py F3a **同一套判据**评估，
预期必须变红。若仍为绿 ⇒ 该断言无效，必须重写。

不修改任何仓库文件、不落库；纯内存模拟。
"""
import asyncio

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'

# 与 _e2e_oa.py F3a 完全相同的判据（逐字等价才叫负向测试）：
# 拿「接口原始返回」独立比对渲染结果，不读 state.workers（否则与渲染器同源、缺陷一起漏过）
JUDGE = """async () => {
  const r = await API.workers();
  const api = Array.isArray(r) ? r : (r.items || r.data || []);
  const sch = api.filter(w => w.scheduleTime);
  const byName = {};
  sch.forEach(w => { byName[String(w.name)] = w; });
  const cards = [...document.querySelectorAll('#oaTimersList .task-card')];
  const rows = cards.map(c => {
    const nb = c.querySelector('.who b');
    const sp = c.querySelector('.who span');
    const ch = c.querySelector('.chip');
    const nm = nb ? nb.textContent.trim() : '';
    const w = byName[nm] || {};
    return { name: nm, on: w.on, matched: !!byName[nm],
             text: sp ? sp.textContent : '', chip: ch ? ch.textContent : '' };
  });
  const bad = rows.filter(x => !x.matched || x.on === null || x.on === undefined
      || !x.text.includes(x.on ? '已启用' : '已停用')
      || x.chip !== (x.on ? '运行中' : '已停用'));
  return { n: sch.length, cards: cards.length, rows: rows, bad: bad, pass: bad.length === 0 };
}"""


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, locale='zh-CN')
        page = await ctx.new_page()
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        await page.wait_for_selector('body.auth', timeout=15000)
        await page.wait_for_timeout(2500)

        # 走真实 UI 路径：写入记忆 → 刷新 → 抽屉 → 定时任务
        await page.evaluate("() => localStorage.setItem('aioa_mode','oa')")
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(2800)
        await page.click('#oaLeft')
        await page.wait_for_timeout(600)
        await page.click('#odTimers')
        await page.wait_for_timeout(1200)

        baseline = await page.evaluate(JUDGE)
        print('[基线·修复后] pass=%s rows=%s' % (baseline['pass'], baseline['rows']))

        # 模拟旧缺陷：把 on 改名 enabled（OA 读 w.enabled ⇒ 恒 undefined），
        # 再走 UI 重新进入「定时任务」触发 oaRender → renderTimers 重绘
        await page.evaluate("""() => {
          state.workers.forEach(w => { w.enabled = w.on; delete w.on; });
        }""")
        await page.click('#oaLeft')          # 子页 → 返回首页
        await page.wait_for_timeout(600)
        await page.click('#oaLeft')          # 首页 → 开抽屉
        await page.wait_for_timeout(500)
        await page.click('#odTimers')        # 重进定时任务（触发重绘，不重取数据）
        await page.wait_for_timeout(1100)
        broken = await page.evaluate(JUDGE)
        print('[复现·旧缺陷] pass=%s rows=%s' % (broken['pass'], broken['rows']))
        print('[复现·旧缺陷] 被判红的行数=%d' % len(broken['bad']))

        ok = baseline['pass'] is True and broken['pass'] is False
        print('\n%s 负向测试：断言对缺陷敏感（基线绿 / 复现红）' % ('[OK  ]' if ok else '[FAIL]'))
        await browser.close()
        return 0 if ok else 1


raise SystemExit(asyncio.run(main()))
