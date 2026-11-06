# -*- coding: utf-8 -*-
"""H5 · OA 层五项修复真机验收（2026-11-06）

覆盖用户报的 5 个问题，每条都在**真实浏览器里点到、量到**，不看源码推理。

  P1 新工作任务识别不了类型 → 点「新建任务」→ 输一句话 → 必须**直接落到某位数字员工**
     （首条 AI 气泡出现「已选择数字员工…」且视图回到首页），而不是弹「请手动选择」浮层。
     真调 POST /v1/workers/intent（不 mock 意图接口），只拦 POST .../runs 避免真的计费跑模型。
  P2 「我的」四个统计要能点 → 点完断言落到 collab/tasks、collab/approvals、recent、kb
  P3 时间填写要有日期时间选择组件 → 日程卡 #scStart/#scEnd 必须是 datetime-local，
     默认值合法、结束早于开始会被本地拦下（不静默提交）
  P4 OA 模块按功能归纳 → 断言分组渲染、模块卡片全覆盖、无空组
  P5 键盘不能把底栏顶上去 → .oa.kb-on 生效时底栏 display:none，撤销后恢复

前置：后端 :8080（H5 由 --aios.web.h5-dir 提供在 /aios/h5/）、agent :8000。
用法：python scripts/_verify_h5_oa_5fix.py
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import pathlib
import re
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
H5 = BASE + "/aios/h5/"
API = BASE + "/api/v1"
USER, PWD = "test", "test"
OUT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "_shot_oa5"
OUT.mkdir(exist_ok=True)

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def login():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"]


def view_state(pg):
    return pg.evaluate("""() => {
        const v = document.querySelector('#oaRoot .view.on');
        const p = document.querySelector('#v-collab .panel.on');
        const r = document.querySelector('#oaRail .rail-item.on');
        return {view: v && v.id, panel: p && p.id, rail: r && r.dataset.panel};
    }""")


def tab(pg, name):
    pg.evaluate("""(n) => {
        const t = document.querySelector("#oaTabs .tab[data-view='" + n + "']");
        if (t) t.click();
    }""", name)
    pg.wait_for_timeout(900)


def drawer_go(pg, item_id):
    pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if (l) l.click(); }")
    pg.wait_for_timeout(450)
    pg.evaluate("(id) => { const d = document.getElementById(id); if (d) d.click(); }", item_id)
    pg.wait_for_timeout(1200)


def main():
    token, user = login()
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        ctx.add_init_script(
            "localStorage.setItem('aios_session', %s);"
            "localStorage.setItem('aios_mode', 'oa');"
            % json.dumps(json.dumps({"token": token, "user": user}, ensure_ascii=False))
        )
        pg = ctx.new_page()
        errs = []
        # 白名单（有据可查的既有噪声，与本次 5 项改动无关）：
        #   · /v1/asr/status 401 —— 语音可用性探测在登录态就绪前发起过一次，设计上 fail-open
        #     （见 index.html 的 probeAsr 注释「登录后 token 才有效」），不是回归；
        #   · net::ERR_FAILED —— 本脚本自己 abort 掉的 POST .../runs。
        benign = ("/asr/status", "net::ERR_FAILED")
        bad_http = []
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
        pg.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
        pg.on("response", lambda r: bad_http.append(f"{r.status} {r.url}")
              if r.status >= 400 and not any(b in r.url for b in benign) else None)
        # 只拦「真正跑模型」的那一发，意图接口保持真实
        runs_blocked = []

        def _route(route):
            runs_blocked.append(route.request.url)
            route.abort()

        pg.route(re.compile(r".*/conversations/\d+/runs.*"), _route)

        pg.goto(H5, wait_until="domcontentloaded")
        pg.wait_for_selector("#oaRoot", timeout=30000)
        pg.wait_for_timeout(2600)
        pg.screenshot(path=str(OUT / "p0-home.png"))

        # ------------------------------------------------------------ P1
        tab(pg, "collab")
        pg.evaluate("() => { const t = document.querySelector('#oaNewTask'); if (t) t.click(); }")
        pg.wait_for_selector("#askDlgInput", timeout=8000)
        pg.fill("#askDlgInput", "我要请假三天")
        pg.screenshot(path=str(OUT / "p1-dialog.png"))
        pg.evaluate("() => { const b = document.querySelector('[data-dlg-ok]'); if (b) b.click(); }")
        pg.wait_for_timeout(3500)
        st = view_state(pg)
        bubbles = pg.evaluate("""() => Array.from(document.querySelectorAll('#v-home .bub, #v-home .bubble, #v-home [class*="bub"]'))
            .map(e => (e.innerText || '').trim())""")
        picked = [t for t in bubbles if "已选择数字员工" in t]
        sheet_open = pg.evaluate("() => document.querySelector('#oaRoot').classList.contains('sheet-open')")
        rec("P1 一句话直接落到具体数字员工（不再弹『请手动选择』）",
            st.get("view") == "v-home" and bool(picked) and not sheet_open,
            "视图 home + 出现「已选择数字员工」气泡 + 未弹选择浮层",
            {"view": st.get("view"), "picked": picked[:2], "sheet_open": sheet_open})
        pg.screenshot(path=str(OUT / "p1-picked.png"))

        # 反向：完全无信息的一句话应当仍让用户自己选（不能瞎猜）
        tab(pg, "collab")
        pg.evaluate("() => { const t = document.querySelector('#oaNewTask'); if (t) t.click(); }")
        pg.wait_for_selector("#askDlgInput", timeout=8000)
        pg.fill("#askDlgInput", "今天天气怎么样")
        pg.evaluate("() => { const b = document.querySelector('[data-dlg-ok]'); if (b) b.click(); }")
        pg.wait_for_timeout(2600)
        fallback = pg.evaluate("""() => ({
            sheet: document.querySelector('#oaRoot').classList.contains('sheet-open'),
            view: (document.querySelector('#oaRoot .view.on') || {}).id
        })""")
        rec("P1 无信息问句不瞎猜（保留人工选择入口）",
            fallback.get("sheet") is True or fallback.get("view") == "v-workers",
            "弹选择浮层 或 打开数字员工列表", fallback)
        pg.screenshot(path=str(OUT / "p1-fallback.png"))

        # 人工选完人之后，刚打的那句话要自动回到输入框（否则用户得把整句再打一遍）
        pg.evaluate("""() => {
            const o = document.querySelector("#oaSheet .sheet-opt[data-target='workers']");
            if (o) o.click();
        }""")
        pg.wait_for_timeout(1200)
        pg.evaluate("""() => {
            const w = document.querySelector('#oaWorkersList [data-worker]');
            if (w) w.click();
        }""")
        pg.wait_for_timeout(1200)
        refill = pg.evaluate("""() => ({
            view: (document.querySelector('#oaRoot .view.on') || {}).id,
            input: (document.querySelector('#oaInput') || {}).value
        })""")
        rec("P1 选完人后原句自动填回输入框",
            refill.get("view") == "v-home" and refill.get("input") == "今天天气怎么样",
            "v-home + input=「今天天气怎么样」", refill)
        pg.screenshot(path=str(OUT / "p1-refill.png"))

        # ------------------------------------------------------------ P2
        tab(pg, "me")
        nstat = pg.evaluate("() => document.querySelectorAll('#oaMeData .me-stat').length")
        rec("P2 「我的」四个统计是可点入口", nstat == 4, 4, nstat)
        pg.screenshot(path=str(OUT / "p2-me.png"))

        cases = [("待办", 0, "v-collab", "p-tasks"),
                 ("审批", 1, "v-collab", "p-approvals"),
                 ("会话", 2, "v-recent", None),
                 ("知识库", 3, "v-kb", None)]
        for label, idx, wview, wpanel in cases:
            tab(pg, "me")
            pg.evaluate("(i) => { const s = document.querySelectorAll('#oaMeData .me-stat'); if (s[i]) s[i].click(); }", idx)
            pg.wait_for_timeout(1100)
            got = view_state(pg)
            ok = got.get("view") == wview and (wpanel is None or got.get("panel") == wpanel)
            rec(f"P2 点「{label}」→ {wview}" + (f"/{wpanel}" if wpanel else ""), ok,
                f"{wview}" + (f"/{wpanel}" if wpanel else ""), got)
            pg.screenshot(path=str(OUT / f"p2-{label}.png"))

        # ------------------------------------------------------------ P3
        tab(pg, "collab")
        pg.evaluate("() => { const r = document.querySelector(\"#oaRail .rail-item[data-panel='schedule']\"); if (r) r.click(); }")
        pg.wait_for_timeout(900)
        t3 = pg.evaluate("""() => {
            const s = document.querySelector('#scStart'), e = document.querySelector('#scEnd');
            return {startType: s && s.type, endType: e && e.type,
                    startVal: s && s.value, endVal: e && e.value};
        }""")
        rec("P3 日程时间用原生日期时间控件",
            t3.get("startType") == "datetime-local" and t3.get("endType") == "datetime-local",
            "两个 datetime-local", t3)
        rec("P3 开始时间预填合法 yyyy-MM-ddTHH:mm",
            bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", t3.get("startVal") or "")),
            "yyyy-MM-ddTHH:mm", t3.get("startVal"))
        pg.screenshot(path=str(OUT / "p3-schedule.png"))

        guard = pg.evaluate("""() => {
            const s = document.querySelector('#scStart'), e = document.querySelector('#scEnd');
            const t = document.querySelector('#scTitle');
            if (!s || !e || !t) return {ok:false, why:'card missing'};
            t.value = '验收·时间倒挂';
            s.value = '2026-12-01T10:00';
            e.value = '2026-12-01T09:00';
            let called = false;
            const orig = API.portalScheduleCreate;
            API.portalScheduleCreate = (...a) => { called = true; return Promise.resolve({}); };
            document.querySelector('#scSave').click();
            return new Promise(r => setTimeout(() => {
                const err = document.querySelector('#scErr');
                const v = {called, errShown: !!(err && err.style.display !== 'none'),
                           errText: err ? err.textContent : '',
                           btn: (document.querySelector('#scSave') || {}).textContent};
                API.portalScheduleCreate = orig;
                r(v);
            }, 400));
        }""")
        rec("P3 结束早于开始被本地拦下且不发请求",
            guard and (not guard.get("called")) and guard.get("errShown"),
            "拦下 + 提示文案 + 未调接口", guard)

        # ------------------------------------------------------------ P4
        drawer_go(pg, "odModules")
        p4 = pg.evaluate("""() => {
            const groups = Array.from(document.querySelectorAll('#oaModGrid .mod-group'));
            const heads = groups.map(g => (g.querySelector('.mod-ghead b') || {}).textContent);
            return {groups: groups.length, heads,
                    cards: document.querySelectorAll('#oaModGrid [data-worker]').length,
                    att: document.querySelectorAll('#oaModGrid [data-attendance]').length,
                    empty: groups.filter(g => !g.querySelector('.mod-card')).length,
                    declared: (document.querySelector('#odModulesN') || {}).textContent};
        }""")
        ok4 = (p4.get("groups") >= 8 and p4.get("cards", 0) >= 40
               and p4.get("att") == 1 and p4.get("empty") == 0)
        rec("P4 OA 模块按功能分组、无空组、模块卡片不丢", ok4,
            "≥8 组 / ≥40 张模块卡 / 打卡 1 / 0 空组", p4)
        pg.screenshot(path=str(OUT / "p4-modules.png"), full_page=True)

        # ------------------------------------------------------------ P5
        p5 = pg.evaluate("""() => {
            const root = document.querySelector('#oaRoot');
            const tabs = document.querySelector('#oaTabs');
            const before = getComputedStyle(tabs).display;
            document.body.classList.add('kb-on');        // 判据挂在 body：经典/新版底栏共用
            const during = getComputedStyle(tabs).display;
            document.body.classList.remove('kb-on');
            const after = getComputedStyle(tabs).display;
            return {before, during, after, bound: root.dataset.kbBound === '1'};
        }""")
        rec("P5 键盘期间底栏收起、收起后恢复",
            p5 and p5["during"] == "none" and p5["after"] != "none",
            "kb-on ⇒ none；移除 ⇒ 恢复", p5)
        rec("P5 键盘适配已绑定（visualViewport 监听存在）", bool(p5 and p5.get("bound")), True, p5.get("bound"))

        # 「Failed to load resource」这条 console 文本不带 URL，判不了是谁；改由 response 钩子判定
        # （bad_http 已按白名单过滤），console 侧只保留真正的 JS 异常。
        real = [e for e in errs
                if not e.startswith("console: Failed to load resource")
                and not any(b in e for b in benign) and "favicon" not in e.lower()]
        rec("无 JS 运行时错误 / 无非预期失败请求", not real and not bad_http,
            "0 条 JS 错误 + 0 个 4xx/5xx", {"js": real[:5], "http": bad_http[:5]},
            f"已忽略既有噪声 {len(errs) - len(real)} 条（asr 探测 401 / 主动 abort 的 runs）")

        b.close()

    print("\n" + "=" * 70)
    bad = [r for r in results if not r[1]]
    for name, ok, _ in results:
        print(("  ✅ " if ok else "  ❌ ") + name)
    print(f"\n合计 {len(results)} 项，通过 {len(results) - len(bad)}，失败 {len(bad)}")
    print(f"截图目录：{OUT}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
