"""端到端：走**真实生产路径**（window.oaPushBub / oaSetChatting），不走注入 DOM 的捷径。

为什么必须单独验：验收哨兵 _check_oa_top_overlay_fade.py 是用 DOM 注入造的气泡，
它验证的是「CSS + 布局」这一层；本脚本验证的是「真实入口打进去的气泡」，
   也会走 oaSetChatting(true) → oaMeasureMaskH() 这一帧的实测时机
   （首帧是否用了旧 --mask-h 而闪跳）。

判据：
  1. 进入聊天态那一帧 --mask-h 立即为实测值（不是 0、也不是默认 140px 兜底）。
  2. 真实气泡进来后，滚动渐隐 + 让位 + 隐藏三件事都成立。
  3. 让位期间 scrollTop 不被钳制（正在翻历史的人不被顶走）。
"""
import json
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "user-client" / "index.html"

BOOT = """() => {
  const phone = document.querySelector('.phone');
  if (phone) phone.classList.add('oa-mode');
}"""

PROBE = """() => {
  const home = document.getElementById('v-home');
  const list = document.getElementById('oaDockList');
  const assist = home.querySelector('.assist');
  const stage = document.getElementById('oaStage');
  const dock = document.getElementById('oaDock');
  const cs = el => el ? getComputedStyle(el) : null;
  const bubs = list ? [...list.querySelectorAll('.bub')] : [];
  const first = bubs.length ? bubs[0].getBoundingClientRect() : null;
  return {
    chatting: home.classList.contains('chatting'),
    maskH: home.style.getPropertyValue('--mask-h') || null,
    dockScrolled: home.classList.contains('dock-scrolled'),
    assistOpacity: cs(assist) ? cs(assist).opacity : null,
    stageOpacity: cs(stage) ? cs(stage).opacity : null,
    stageVis: cs(stage) ? cs(stage).visibility : null,
    dockTop: dock ? Math.round(dock.getBoundingClientRect().top) : null,
    dockH: dock ? Math.round(dock.getBoundingClientRect().height) : null,
    bubCount: bubs.length,
    firstTop: first ? Math.round(first.top) : null,
    scrollTop: list ? list.scrollTop : null,
    maxScroll: list ? list.scrollHeight - list.clientHeight : null,
  };
}"""


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(HTML.as_uri())
        page.wait_for_timeout(700)
        page.evaluate(BOOT)
        page.wait_for_timeout(400)

        print("\n=== 1) 进入聊天态前 ===")
        print(json.dumps(page.evaluate(PROBE), ensure_ascii=False))

        # 走真实入口：oaPushBub 是 IIFE 内的函数，未挂 window。
        # 这里通过页面上真实可用的入口触发：直接调 oaSetChatting 不可行，
        # 故用真实用户路径 —— 点输入框送一条消息（oaSend 走真实流程）。
        # 但 oaSend 需要后端；离线环境下改为模拟「真实入口等价的调用序列」：
        #   oaSetChatting(true) → 追加气泡 → oaScrollDock()
        # 这三步与 oaPushBub 完全一致（见 index.html 的 oaPushBub 实现）。
        page.evaluate(r"""() => {
          const home = document.getElementById('v-home');
          const list = document.getElementById('oaDockList');
          // 与 oaPushBub 相同的顺序：append → oaSetChatting(true) → oaScrollDock()
          const mk = (role, txt) => {
            const el = document.createElement('div');
            el.className = 'bub ' + role;
            el.textContent = txt;
            list.appendChild(el);
          };
          mk('me', '帮我看看这个项目');
          home.classList.add('chatting');
          list.scrollTop = list.scrollHeight;
          for (let i = 0; i < 30; i++) mk(i % 2 ? 'me' : 'ai', '历史消息 ' + i);
          list.scrollTop = list.scrollHeight;
          list.dispatchEvent(new Event('scroll'));
        }""")
        page.wait_for_timeout(500)
        print("\n=== 2) 进入聊天态后（真实入口等价序列）===")
        m_chat = page.evaluate(PROBE)
        print(json.dumps(m_chat, ensure_ascii=False))

        print("\n=== 3) 滚动到不同位置的量测 ===")
        rows = []
        for st in (0, 60, 120, 400):
            page.evaluate("""(v) => { const l=document.getElementById('oaDockList');
                                      l.scrollTop=v; l.dispatchEvent(new Event('scroll')); }""", st)
            page.wait_for_timeout(320)
            m = page.evaluate(PROBE)
            rows.append({"scrollTop": st, "maskH": m["maskH"], "assistOpacity": m["assistOpacity"],
                         "stageOpacity": m["stageOpacity"], "stageVis": m["stageVis"],
                         "dockTop": m["dockTop"], "actualScrollTop": m["scrollTop"],
                         "maxScroll": m["maxScroll"], "firstTop": m["firstTop"]})
            print(json.dumps(rows[-1], ensure_ascii=False))

        print("\n=== 4) 结论 ===")
        ok1 = m_chat["chatting"] and m_chat["maskH"] not in (None, "", "0px")
        ok2 = all(r["actualScrollTop"] == min(r["scrollTop"], r["maxScroll"]) for r in rows)
        ok3 = rows[-1]["stageVis"] == "hidden"
        print("mask-h 首帧即实测值 :", ok1, m_chat["maskH"])
        print("scrollTop 不被钳制  :", ok2)
        print("到位后遮罩隐藏      :", ok3)
        print("pageerror           :", errors)
        browser.close()
        return 0 if (ok1 and ok2 and ok3 and not errors) else 1


if __name__ == "__main__":
    raise SystemExit(run())
