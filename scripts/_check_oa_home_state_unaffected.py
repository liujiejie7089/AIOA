"""回归：首页态（非聊天态）不受第八轮遮罩改造影响。

为什么必须单独验：本轮 CSS 全部挂在 `.oa #v-home.chatting` 下（只作用于聊天态），
但新增了 `.assist{position:relative;z-index:2}` 与 JS 的 `--mask-h` 实测 ——
若作用域写错，首页（.stage 是整屏主体）会出现整屏上移/错位。

判据（首页态，viewport 390×844）：
  1. 首页无 chatting class ⇒ 本轮规则整体不生效
  2. .assist / .stage 的位置与高度 == 改造前基线
  3. .dock 仍 display:none（首页没有对话坞）
  4. 4 张 .kpi-float 指标卡仍在、仍是带边框白底（首页态的「带边框的层」不受影响）
  5. 数字人图片仍在页面里且水平居中
  6. --mask-h 在首页态为 0（dock display:none ⇒ 量不到高度 ⇒ 兜底 0，不产生错误位移）
"""

import sys

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "user-client" / "index.html"

# 改造前首页态基线（离线实测）
BASELINE_HOME = {
    "assistTop": 66, "assistH": 90,
    "stageTop": 166, "stageH": 486,
    "kpiCount": 4,
    "kpiBorder": "1px solid rgb(230, 234, 242)",
    "kpiBg": "rgb(255, 255, 255)",
    "robotCentered": True,
}

BOOT = """() => {
  const phone = document.querySelector('.phone');
  if (phone) phone.classList.add('oa-mode');
}"""

PROBE = """() => {
  const home = document.getElementById('v-home');
  const assist = home.querySelector('.assist');
  const stage = document.getElementById('oaStage');
  const dock = document.getElementById('oaDock');
  const kpis = [...document.querySelectorAll('.kpi-float')].filter(k => getComputedStyle(k).display !== 'none');
  const robot = document.querySelector('.robot-wrap');
  const rr = robot ? robot.getBoundingClientRect() : null;
  const cs = kpis.length ? getComputedStyle(kpis[0]) : null;
  return {
    chatting: home.classList.contains('chatting'),
    maskH: home.style.getPropertyValue('--mask-h') || null,
    assistTop: Math.round(assist.getBoundingClientRect().top), assistH: assist.offsetHeight,
    stageTop: Math.round(stage.getBoundingClientRect().top), stageH: stage.offsetHeight,
    dockDisplay: getComputedStyle(dock).display,
    dockTop: Math.round(dock.getBoundingClientRect().top),
    kpiCount: kpis.length,
    kpiBorder: cs ? cs.border : null,
    kpiBg: cs ? cs.backgroundColor : null,
    robotPresent: !!robot,
    robotCentered: rr ? Math.abs((rr.left + rr.width/2) - 195) <= 2 : false,
    robotTop: rr ? Math.round(rr.top) : null,
  };
}"""

results = []


def rec(name, ok, expected, actual):
    results.append((name, ok))
    print("[%s] %s\n      expect=%s\n      actual=%s"
          % ("PASS" if ok else "FAIL", name,
             json.dumps(expected, ensure_ascii=False), json.dumps(actual, ensure_ascii=False)))


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(HTML.as_uri())
        page.wait_for_timeout(800)
        page.evaluate(BOOT)
        page.wait_for_timeout(600)
        m = page.evaluate(PROBE)
        browser.close()

    rec("R1. 首页态未进入 chatting（本轮规则整体不生效）",
        m["chatting"] is False, {"chatting": False}, {"chatting": m["chatting"]})
    rec("R2. 首页态 .assist/.stage 位置与高度 == 改造前基线",
        m["assistTop"] == BASELINE_HOME["assistTop"] and m["assistH"] == BASELINE_HOME["assistH"]
        and m["stageTop"] == BASELINE_HOME["stageTop"] and m["stageH"] == BASELINE_HOME["stageH"],
        {"assistTop": BASELINE_HOME["assistTop"], "assistH": BASELINE_HOME["assistH"],
         "stageTop": BASELINE_HOME["stageTop"], "stageH": BASELINE_HOME["stageH"]},
        {"assistTop": m["assistTop"], "assistH": m["assistH"],
         "stageTop": m["stageTop"], "stageH": m["stageH"]})
    rec("R3. 首页态 .dock 仍 display:none（首页没有对话坞）",
        m["dockDisplay"] == "none" and m["dockTop"] == 0,
        {"display": "none", "top": 0},
        {"display": m["dockDisplay"], "top": m["dockTop"]})
    rec("R4. 首页态 4 张 .kpi-float 指标卡仍在且仍是带边框白底（首页的带边框层不受影响）",
        m["kpiCount"] == BASELINE_HOME["kpiCount"]
        and m["kpiBorder"] == BASELINE_HOME["kpiBorder"]
        and m["kpiBg"] == BASELINE_HOME["kpiBg"],
        {"count": BASELINE_HOME["kpiCount"], "border": BASELINE_HOME["kpiBorder"],
         "bg": BASELINE_HOME["kpiBg"]},
        {"count": m["kpiCount"], "border": m["kpiBorder"], "bg": m["kpiBg"]})
    rec("R5. 首页态数字人仍在且水平居中",
        m["robotPresent"] and m["robotCentered"], {"robotPresent": True, "centered": True},
        {"robotPresent": m["robotPresent"], "centered": m["robotCentered"],
         "robotTop": m["robotTop"]})
    rec("R6. 首页态 --mask-h 为 0（dock 隐藏 ⇒ 量不到高度 ⇒ 兜底 0，不产生错误位移）",
        m["maskH"] in ("0px", "0.0px", None), {"maskH": "0px"}, {"maskH": m["maskH"]})
    rec("R7. 全程无未捕获 JS 异常",
        not errors, {"pageerror": 0}, {"pageerror": errors})

    bad = [n for n, ok in results if not ok]
    print("\n合计 %d 项，通过 %d 项，失败 %d 项" % (len(results), len(results) - len(bad), len(bad)))
    for n in bad:
        print("  FAIL: %s" % n)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(run())
