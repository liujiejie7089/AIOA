# -*- coding: utf-8 -*-
"""确认卡观感留证：用真实 DOM 渲染三种状态，截图落 logs/proof/confirm_card.png。

注意这是**离线渲染**（file:// + 直接调用 confirmCardHtml），不是连真后端跑出来的
——它的作用是把 CSS 落成看得见的图，贴枪式的 UI 判据由 _check_confirm_card.py 断言。

跑法：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_shot_confirm_card.py
"""

import sys

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import os
import urllib.parse

from playwright.async_api import async_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, 'user-client', 'index.html')
OUT = os.path.join(REPO, 'logs', 'proof', 'confirm_card.png')


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        page = await (await browser.new_context(viewport={'width': 390, 'height': 720},
                                                device_scale_factor=2,
                                                locale='zh-CN')).new_page()
        await page.goto('file:///' + urllib.parse.quote(INDEX.replace('\\', '/'), safe='/'),
                        wait_until='domcontentloaded')
        await page.wait_for_timeout(400)
        # 三种状态：待决策（危险动作）、待决策（普通确认）、已确认
        await page.evaluate("""() => {
          document.body.innerHTML = '<div id="cfShot" style="padding:16px;display:flex;'
            + 'flex-direction:column;gap:14px;font-family:inherit"></div>';
          const wrap = document.getElementById('cfShot');
          function bubble(inner){
            const b = document.createElement('div');
            b.className = 'bub';
            b.style.cssText = 'max-width:340px;padding:10px 12px;border-radius:12px;'
              + 'background:var(--surface);border:1px solid var(--border)';
            const tx = document.createElement('div');
            tx.className = 'tx';
            tx.style.cssText = 'font-size:13px;line-height:1.6';
            tx.textContent = inner;
            b.appendChild(tx);
            wrap.appendChild(b);
            return b;
          }
          const b1 = bubble('邮件草稿已备好（草稿编号 3），收件人：张三。发送后不可撤回，请确认。');
          b1.appendChild(document.createRange().createContextualFragment(
            confirmCardHtml({title:'删除这 5 条历史操作记录', description:'删除后不可恢复，且操作记录审计留痕。',
                             confirm_label:'确认删除', cancel_label:'取消', danger:true})));
          const b2 = bubble('这封介绍公司业务的邮件已写好，收件人：张三。');
          b2.appendChild(document.createRange().createContextualFragment(
            confirmCardHtml({title:'向张三发送这封邮件', description:'收件人 1 人',
                             confirm_label:'确认发送', cancel_label:'暂不发送', danger:false})));
          const b3 = bubble('邮件草稿已备好（草稿编号 3），收件人：张三。');
          const frag = document.createRange().createContextualFragment(
            confirmCardHtml({title:'向张三发送这封邮件', confirm_label:'确认发送'}));
          b3.appendChild(frag);
          // 第三张改成「已完成」：禁键 + 已确认标注（走真实 freeze 结果的样子）
          const card3 = b3.querySelector('.confirm-card');
          card3.classList.add('done');
          const ok3 = card3.querySelector('[data-cf-ok]');
          const no3 = card3.querySelector('[data-cf-cancel]');
          ok3.textContent = '已发送'; ok3.disabled = true; no3.disabled = true;
          const note = document.createElement('div');
          note.className = 'cf-note ok';
          note.textContent = '已确认 · 确认发送';
          card3.appendChild(note);
        }""")
        await page.wait_for_timeout(200)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        await page.locator('#cfShot').screenshot(path=OUT)
        await browser.close()
    print('已生成', OUT)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
