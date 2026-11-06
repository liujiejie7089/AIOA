# -*- coding: utf-8 -*-
"""回归取证：补采 H5 的定时任务 / 连接器 / 键盘态 / 知识库四张截图（2026-11-06）。

只做截图，不做断言 —— 断言在 _verify_*.py 里，本脚本只负责留下肉眼可核的图。
"""
import importlib.util
import json
import pathlib
import sys

try:  # A3：GBK 控制台打印 emoji 会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("oa5", str(HERE / "_verify_h5_oa_5fix.py"))
oa5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oa5)

OUT = HERE.parent / "docs" / "assets" / "regression-2026-11-06"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    token, user = oa5.login()
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        ctx.add_init_script(
            "localStorage.setItem('aios_session', %s);localStorage.setItem('aios_mode','oa');"
            % json.dumps(json.dumps({"token": token, "user": user}, ensure_ascii=False)))
        pg = ctx.new_page()
        pg.goto(oa5.H5, wait_until="domcontentloaded")
        pg.wait_for_selector("#oaRoot", timeout=30000)
        pg.wait_for_timeout(2600)

        # ① 定时任务（抽屉 → odTimers）
        oa5.drawer_go(pg, "odTimers")
        pg.wait_for_timeout(1500)
        n_timers = pg.evaluate("() => document.querySelectorAll('#oaTimersList *').length")
        pg.screenshot(path=str(OUT / "08-timers.png"))
        print("timers view =", oa5.view_state(pg), "nodes=", n_timers)

        # ② 插件-技能-连接器 → 连接器段
        oa5.drawer_go(pg, "odSkills")
        pg.wait_for_timeout(900)
        pg.evaluate("""() => {
            const b = document.querySelector('#oaSkillsSeg button[data-seg="connectors"]');
            if (b) b.click();
        }""")
        pg.wait_for_timeout(1500)
        conns = pg.evaluate("""() => Array.from(document.querySelectorAll('#oaConnectorsList .conn-card, #oaConnectorsList [class*="conn"]'))
            .slice(0,6).map(e => (e.innerText||'').replace(/\\n+/g,' | ').slice(0,80))""")
        pg.screenshot(path=str(OUT / "09-connectors.png"))
        print("connectors =", conns)

        # ③ OA 模块分组（抽屉 → odModules）
        oa5.drawer_go(pg, "odModules")
        pg.wait_for_timeout(1500)
        groups = pg.evaluate("""() => Array.from(document.querySelectorAll('#oaModGrid .mod-ghead'))
            .map(e => (e.innerText||'').trim())""")
        pg.screenshot(path=str(OUT / "10-oa-modules.png"))
        print("module groups =", groups)

        # ④ 键盘态：底栏必须收起（P5 的视觉证据）
        oa5.tab(pg, "home")
        pg.wait_for_timeout(600)
        before = pg.evaluate("() => getComputedStyle(document.querySelector('#oaTabs')).display")
        pg.evaluate("() => document.body.classList.add('kb-on')")
        pg.wait_for_timeout(500)
        during = pg.evaluate("() => getComputedStyle(document.querySelector('#oaTabs')).display")
        pg.screenshot(path=str(OUT / "11-keyboard-tabbar-hidden.png"))
        pg.evaluate("() => document.body.classList.remove('kb-on')")
        pg.wait_for_timeout(400)
        after = pg.evaluate("() => getComputedStyle(document.querySelector('#oaTabs')).display")
        print("tabbar display before/during/after =", before, during, after)

        # ⑤ 我的（四统计）
        oa5.tab(pg, "me")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=str(OUT / "12-me-stats.png"))

        b.close()
    print("截图目录：", OUT)


if __name__ == "__main__":
    main()
