# -*- coding: utf-8 -*-
"""oa-demo.html 视觉自检：390x844 视口截图 + console 错误/横向溢出检查。
产出 scripts/_shot_oa/<name>.png（_* 不入库）。"""
import pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / "user-client" / "oa-demo.html").resolve().as_uri()
OUT = ROOT / "scripts" / "_shot_oa"
OUT.mkdir(exist_ok=True)

errors, shots = [], []

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
    pg.goto(HTML)
    pg.wait_for_timeout(700)

    def snap(name):
        p = OUT / f"{name}.png"
        pg.screenshot(path=str(p))
        shots.append(str(p.relative_to(ROOT)))

    def tab(v):                      # 底部菜单切页
        pg.click(f".tabbar.on .tab[data-view='{v}']"); pg.wait_for_timeout(450)

    # 1) 首页 = 工作助手（图1）
    snap("01-home-assistant")

    # 1b) 数字人断言：① 内联位图真的解码出来了 ② 确实在动（静态截图证明不了「在动」，量 computed transform）
    img_ok = pg.evaluate("() => {const i=document.querySelector('.robot-img');"
                         "return !!i && i.complete && i.naturalWidth > 0;}")
    def tf(sel):
        return pg.evaluate("s => getComputedStyle(document.querySelector(s)).transform", sel)
    b1, s1 = tf(".r-bob"), tf(".robot-img")
    pg.wait_for_timeout(520)
    b2, s2 = tf(".r-bob"), tf(".robot-img")
    motion = {"img-loaded": bool(img_ok), "bob": b1 != b2, "sway": s1 != s2}
    pg.wait_for_timeout(200)

    # 2) 点数字人 → 选择「专家 / 数字人」
    pg.click("#robotBtn"); pg.wait_for_timeout(500); snap("02-sheet-choose")
    # 选「数字人」
    pg.click(".sheet-opt[data-target='workers']"); pg.wait_for_timeout(500); snap("03-workers")

    # 3) 任务 = 办公协同（图2）+ 左导轨切换
    tab("collab"); snap("04-collab-tasks")
    for panel in ("projects", "approvals", "schedule"):
        pg.click(f"#rail .rail-item[data-panel='{panel}']"); pg.wait_for_timeout(400); snap(f"05-collab-{panel}")

    # 4) 知识库（图3）/ 部门（图4）/ 我的（图5）
    tab("kb"); snap("06-kb")
    tab("org"); snap("07-org")
    tab("me"); snap("08-me-switch")

    # 5) 我的 → 工作统计
    pg.click("#v-me .lrow:has-text('工作统计')"); pg.wait_for_timeout(500); snap("09-stats")

    # 6) 抽屉（首页 ≡）
    tab("home"); pg.click("#abLeft"); pg.wait_for_timeout(450); snap("10-drawer")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    # 7) 原页面（经典）
    tab("me"); pg.click("#seg button[data-mode='classic']"); pg.wait_for_timeout(700); snap("11-classic-home")

    # 切回新页面（经典模式下 #seg 只在「我的」里可见）
    pg.click("#tabClassic .tab[data-view='me']"); pg.wait_for_timeout(450)
    pg.click("#seg button[data-mode='new']"); pg.wait_for_timeout(600)

    # 溢出检查
    over = []
    for v in ("home", "collab", "kb", "org", "me"):
        tab(v)
        o = pg.evaluate("() => {const e=document.querySelector('.view.on'); "
                        "return {sw:e.scrollWidth, cw:e.clientWidth};}")
        if o["sw"] > o["cw"] + 1:
            over.append(f"{v}: scrollWidth {o['sw']} > clientWidth {o['cw']}")
    b.close()

print("shots:", len(shots))
for s in shots:
    print("  ", s)
print("console errors/warnings:", len(errors))
for e in errors[:20]:
    print("  ", e)
print("horizontal overflow:", over if over else "无")
print("robot motion:", motion)
bad = (errors or over) or not all(motion.values())
sys.exit(1 if bad else 0)
