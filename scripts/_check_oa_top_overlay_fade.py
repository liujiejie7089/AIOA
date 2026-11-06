"""哨兵：OA 聊天页「顶部遮罩层」第八轮改造的判据验收。

用户口径（2026-10-31）：
  「页面中图片周围有一个带边框的遮罩层，遮挡了图片内容。请修改该遮罩：
    在用户向上滑动时，遮罩层逐渐变为透明（滑动进度越靠上越透明），
    并在完全滑动到位后隐藏遮罩、不再阻挡内容交互，使聊天记录能正确显示在遮罩的位置；
    保持原有的边框与视觉样式在非透明状态下不变。」

拆成 5 组硬判据：
  A. 非透明态（--hd=0）**逐像素不变**：视觉类计算样式（边框/阴影/圆角/背景/颜色…）
     与版面（遮罩位置与高度、对话坞 top/高、列表 clientHeight/scrollHeight、
     首气泡 top、输入栏 top）都必须等于**改造前实测基线**（见 BASELINE）。
     基线是常量而非运行时取 git HEAD —— 提交后本哨兵依然能守住「非透明态不变」。
  B. 渐变连续：--hd 从 0 → 1，遮罩 opacity 必须是**线性插值**（1/0.75/0.5/0.25/0），
     不是 0/1 瞬跳。
  C. 完全到位后隐藏且不挡交互：--hd≥0.99 时 .assist/.stage 必须
     visibility:hidden + pointer-events:none；且 elementsFromPoint 落在遮罩位置时
     命中的是**聊天内容**而不是遮罩（证明不再阻挡）。
  D. 让位：--hd=1 时对话坞视口要顶进遮罩原来的位置（顶部空带被聊天记录占住）。
  E. 不跳位：让位不得把正在翻历史的人顶走 —— scrollTop 不被浏览器钳制；
     最后一条气泡仍贴住输入栏（底部锚点不漂）。

基线取自**改造前**版本（HEAD=2d4833a）的离线实测，viewport 390×844、聊天态、30 条气泡。

⚠️ 全部离线跑（file://），不依赖后端。

用法：
  python scripts/_check_oa_top_overlay_fade.py
退出码 0 = 全绿。
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / "user-client" / "index.html"

# ---------------------------------------------------------------- 改造前基线（实测常量）
BASELINE = {
    "assistTop": 66, "assistH": 37,
    "stageTop": 105, "stageH": 101,
    "dockTop": 206, "dockH": 485,
    "listClientH": 485, "listScrollH": 1636,
    "listMaxScroll": 1151,
    "firstTop": 214,
    "composerTop": 691,
}
BASELINE_VISUAL = {
    "assist": {"opacity": "1", "visibility": "visible", "pointerEvents": "auto",
               "backgroundColor": "rgba(0, 0, 0, 0)", "border": "0px none rgb(20, 26, 38)",
               "borderRadius": "0px", "boxShadow": "none", "color": "rgb(20, 26, 38)",
               "fontSize": "13px", "padding": "2px 6px 0px",
               "transform": "matrix(1, 0, 0, 1, 0, 0)"},
    "stage": {"opacity": "1", "visibility": "visible", "pointerEvents": "auto",
              "backgroundColor": "rgba(0, 0, 0, 0)", "border": "0px none rgb(20, 26, 38)",
              "borderRadius": "0px", "boxShadow": "none", "color": "rgb(20, 26, 38)",
              "fontSize": "13px", "padding": "0px",
              "transform": "matrix(1, 0, 0, 1, 0, 0)"},
}

results = []


def rec(name, status, expected, actual, detail=""):
    results.append({"name": name, "status": status, "expected": expected,
                    "actual": actual, "detail": detail})
    tag = {"PASS": "PASS", "FAIL": "FAIL", "NA": "NA"}.get(status, status)
    print("[%s] %s\n      expect=%s\n      actual=%s%s"
          % (tag, name, json.dumps(expected, ensure_ascii=False),
             json.dumps(actual, ensure_ascii=False),
             ("\n      note  =%s" % detail) if detail else ""))


# ---------------------------------------------------------------- 量测
SETUP = """() => {
  const phone = document.querySelector('.phone');
  if (phone) phone.classList.add('oa-mode');
  const home = document.getElementById('v-home');
  if (home) home.classList.add('chatting');
  const list = document.getElementById('oaDockList');
  if (list) {
    list.innerHTML = '';
    for (let i = 0; i < 30; i++) {
      const d = document.createElement('div');
      d.className = 'bub ' + (i % 2 ? 'me' : 'ai');
      d.textContent = '第' + i + '条历史消息，用来把对话坞撑出滚动条';
      list.appendChild(d);
    }
  }
}"""

PROBE = """() => {
  const home = document.getElementById('v-home');
  const assist = home.querySelector('.assist');
  const stage  = document.getElementById('oaStage');
  const dock   = document.getElementById('oaDock');
  const list   = document.getElementById('oaDockList');
  const composer = document.querySelector('.composer');
  const cs = el => el ? getComputedStyle(el) : null;
  const rect = el => el ? el.getBoundingClientRect() : null;
  const bubs = list ? [...list.querySelectorAll('.bub')] : [];
  const first = bubs.length ? bubs[0].getBoundingClientRect() : null;
  const last  = bubs.length ? bubs[bubs.length-1].getBoundingClientRect() : null;
  const ar = rect(assist), sr = rect(stage), dr = rect(dock), lr = rect(list);
  const cr = rect(composer);
  const visual = el => {
    if (!el) return null;
    const s = getComputedStyle(el);
    return {opacity: s.opacity, visibility: s.visibility, pointerEvents: s.pointerEvents,
            backgroundColor: s.backgroundColor, border: s.border,
            borderRadius: s.borderRadius, boxShadow: s.boxShadow, color: s.color,
            fontSize: s.fontSize, padding: s.padding, transform: s.transform};
  };
  /* 命中测试：遮罩带中心（.assist + .stage 的中点）在最上层命中了什么 */
  let hitTop = null;
  if (ar && sr) {
    const x = Math.round(ar.left + ar.width/2);
    const y = Math.round(ar.top + (sr.bottom - ar.top)/2);
    const els = document.elementsFromPoint(x, y);
    hitTop = els.length ? (els[0].className || els[0].tagName) : null;
  }
  return {
    hd: home.style.getPropertyValue('--hd') || '0',
    maskH: home.style.getPropertyValue('--mask-h') || null,
    dockScrolled: home.classList.contains('dock-scrolled'),
    assistOpacity: cs(assist) ? cs(assist).opacity : null,
    stageOpacity: cs(stage) ? cs(stage).opacity : null,
    assistVis: cs(assist) ? cs(assist).visibility : null,
    stageVis: cs(stage) ? cs(stage).visibility : null,
    assistPE: cs(assist) ? cs(assist).pointerEvents : null,
    stagePE: cs(stage) ? cs(stage).pointerEvents : null,
    assistVisual: visual(assist), stageVisual: visual(stage),
    assistTop: ar ? Math.round(ar.top) : null, assistH: assist ? assist.offsetHeight : null,
    stageTop: sr ? Math.round(sr.top) : null,  stageH: stage ? stage.offsetHeight : null,
    dockTop: dr ? Math.round(dr.top) : null,  dockH: dr ? Math.round(dr.height) : null,
    listClientH: list ? list.clientHeight : null,
    listScrollH: list ? list.scrollHeight : null,
    listMaxScroll: list ? list.scrollHeight - list.clientHeight : null,
    listScrollTop: list ? list.scrollTop : null,
    listTop: lr ? Math.round(lr.top) : null,
    composerTop: cr ? Math.round(cr.top) : null,
    firstTop: first ? Math.round(first.top) : null,
    lastBottom: last ? Math.round(last.bottom) : null,
    hitTop: hitTop
  };
}"""

SET_SCROLL = """(v) => {
  const l = document.getElementById('oaDockList');
  l.scrollTop = v;
  l.dispatchEvent(new Event('scroll'));
}"""


def measure(page, scroll_top):
    page.evaluate(SET_SCROLL, scroll_top)
    page.wait_for_timeout(320)          # 等 transition(120ms) 走完
    return page.evaluate(PROBE)


def open_page(browser, path):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(pathlib.Path(path).as_uri())
    page.wait_for_timeout(700)
    page.evaluate(SETUP)
    page.wait_for_timeout(600)
    return page


def before_version(tmpdir):
    """已弃用：基线改为固化常量（见 BASELINE），不再依赖运行时 git HEAD。"""
    raise NotImplementedError


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            # ---------------- 非透明态（--hd=0）----------------
            page = open_page(browser, HTML)
            a0 = measure(page, 0)
            a_max = measure(page, 999999)          # 贴底
            page.close()

            # ---------------- 若干滚动位置的连续量测 ----------------
            page = open_page(browser, HTML)
            samples = {}
            for st in (0, 30, 60, 90, 120, 300):
                samples[st] = measure(page, st)
            page.close()
        finally:
            browser.close()

    # ---------- A. 非透明态（--hd=0）逐像素不变 ----------
    for who in ("assist", "stage"):
        bv = BASELINE_VISUAL[who]
        av = a0["%sVisual" % who] or {}
        diff = {k: [bv.get(k), av.get(k)] for k in bv if bv.get(k) != av.get(k)}
        rec("A. 非透明态：%s 的视觉计算样式（边框/阴影/圆角/背景/颜色）与改造前基线逐项相同" % who,
            "PASS" if not diff else "FAIL", "无差异", diff or "无差异")

    layout_diff = {k: [BASELINE.get(k), a0.get(k)]
                   for k in BASELINE if BASELINE.get(k) != a0.get(k)}
    rec("A. 非透明态：版面逐像素不变（遮罩位置/高度、对话坞 top/高、"
        "列表 clientHeight/scrollHeight/maxScroll、首气泡 top、输入栏 top）",
        "PASS" if not layout_diff else "FAIL", "无差异", layout_diff or "无差异")

    # ---------- B/C/D/E ----------------
    # B. 连续插值
    interp = []
    for st in (0, 30, 60, 90, 120):
        s = samples[st]
        interp.append({"scrollTop": st, "hd": s["hd"],
                       "assistOpacity": s["assistOpacity"], "stageOpacity": s["stageOpacity"],
                       "dockTop": s["dockTop"]})
    expected_op = [1.0, 0.75, 0.5, 0.25, 0.0]
    ok = True
    for row, exp in zip(interp, expected_op):
        for key in ("assistOpacity", "stageOpacity"):
            v = float(row[key] or 0)
            if abs(v - exp) > 0.06:
                ok = False
    rec("B. 渐变是连续插值：--hd 0→1 时遮罩 opacity 线性递减（1/0.75/0.5/0.25/0）",
        "PASS" if ok else "FAIL", "1.0/0.75/0.5/0.25/0.0", interp)

    # C. 到位后隐藏 + 不挡交互
    at120 = samples[120]
    rec("C. 完全到位后遮罩隐藏（visibility:hidden）",
        "PASS" if at120["assistVis"] == "hidden" and at120["stageVis"] == "hidden" else "FAIL",
        "assist/stage visibility=hidden",
        {"assist": at120["assistVis"], "stage": at120["stageVis"]})
    rec("C. 完全到位后不再阻挡内容交互（pointer-events:none + 命中测试落在聊天内容上）",
        "PASS" if at120["assistPE"] == "none" and at120["stagePE"] == "none"
        and (at120["hitTop"] is None or "assist" not in str(at120["hitTop"])
             and "stage" not in str(at120["hitTop"])) else "FAIL",
        "pointer-events:none 且 elementsFromPoint 命中的不是遮罩",
        {"assistPE": at120["assistPE"], "stagePE": at120["stagePE"], "hitTop": at120["hitTop"]})

    # D. 让位：对话坞顶进遮罩原位置
    d0 = samples[0]
    moved = (d0["dockTop"] or 0) - (at120["dockTop"] or 0)
    rec("D. 让位：完全到位时对话坞视口顶进遮罩原来的位置",
        "PASS" if moved >= 100 else "FAIL",
        "对话坞上移 ≥100px（遮罩带高度量级）",
        {"dockTop@hd0": d0["dockTop"], "dockTop@hd1": at120["dockTop"], "上移px": moved,
         "maskH": at120["maskH"]})

    # E. 不跳位：scrollTop 不被钳制 + 底部锚点不漂
    e_ok = True
    e_detail = {}
    for st in (30, 60, 90, 120, 300):
        s = samples[st]
        want = min(st, s["listMaxScroll"])
        e_detail["scrollTop@%d" % st] = {"want": want, "actual": s["listScrollTop"]}
        if s["listScrollTop"] != want:
            e_ok = False
    rec("E. 让位不跳位：设定 scrollTop 后不被浏览器钳制（正在翻历史的人不被顶走）",
        "PASS" if e_ok else "FAIL", "设定值即实际值", e_detail)

    anchor_ok = (a_max["lastBottom"] is not None
                 and abs(a_max["lastBottom"] - BASELINE["composerTop"] + 10) <= 3)
    rec("E. 底部锚点不漂：贴底时最后一条气泡仍贴在输入栏上方（输入栏不被顶走）",
        "PASS" if anchor_ok else "FAIL",
        "lastBottom ≈ composerTop-10",
        {"lastBottom": a_max["lastBottom"], "composerTop": a_max["composerTop"],
         "baseline_composerTop": BASELINE["composerTop"]})

    print("\n" + "=" * 60)
    bad = [r for r in results if r["status"] != "PASS"]
    print("总计 %d 项，通过 %d 项，失败 %d 项" % (len(results), len(results) - len(bad), len(bad)))
    for r in bad:
        print("  FAIL: %s" % r["name"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
