"""渲染取证：把第八轮改造的三个关键状态截图存盘，供人工核对视觉效果。

  0. 非透明态（scrollTop=0）：遮罩完整可见，版面与改造前一致
  1. 渐变中途（scrollTop=60）：遮罩半透明，对话坞同步上移让位
  2. 完全到位（scrollTop=120+）：遮罩彻底隐藏，聊天记录占住原来的遮罩位置

输出：logs/proof/oa_overlay_fade_*.png
"""

import sys

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "user-client" / "index.html"
OUT = ROOT / "logs" / "proof"
OUT.mkdir(parents=True, exist_ok=True)

SETUP = """() => {
  const phone = document.querySelector('.phone');
  if (phone) phone.classList.add('oa-mode');
  const home = document.getElementById('v-home');
  if (home) home.classList.add('chatting');
  const list = document.getElementById('oaDockList');
  if (list) { list.innerHTML='';
    for (let i=0;i<30;i++){ const d=document.createElement('div');
      d.className='bub '+(i%2?'me':'ai');
      d.textContent = i===0 ? '我这边手头的项目资料，麻烦你帮我梳理一下要点。'
        : (i===1 ? '好的，我先看一下项目背景，稍后给你一份结构化摘要。'
        : '第' + i + '条历史消息，用来把对话坞撑出滚动条');
      list.appendChild(d);} }
}"""


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(HTML.as_uri())
        page.wait_for_timeout(700)
        page.evaluate(SETUP)
        page.wait_for_timeout(600)
        for tag, st in (("0_opaque", 0), ("1_mid", 60), ("2_hidden", 120)):
            page.evaluate("""(v) => { const l=document.getElementById('oaDockList');
                                      l.scrollTop=v; l.dispatchEvent(new Event('scroll')); }""", st)
            page.wait_for_timeout(400)
            path = OUT / ("oa_overlay_fade_%s.png" % tag)
            page.screenshot(path=str(path))
            print("saved", path)
        browser.close()


if __name__ == "__main__":
    run()
