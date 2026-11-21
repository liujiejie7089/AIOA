# -*- coding: utf-8 -*-
"""历史对话格式一致性真机验收：当场回答 与 刷新后历史回放 必须同版式。

链路：H5 输入框真实提问（oaSend 真链路）→ 当场断言（表格+图表）
→ page.reload() → oaRestoreLastConv 自动恢复 → 断言历史回放同样走 formatAnswer。

产物：docs/screenshots/history-replay-2026-11-21/
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots", "history-replay-2026-11-21")
API = "http://127.0.0.1:8080/api/v1"
BASE = "http://127.0.0.1:5181"
QUESTION = "成都市非遗工坊电商平台销量柱状图"
TIMEOUT_MS = 300_000

results = []
def chk(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS" if cond else "FAIL") + " | " + name + ((" | " + str(detail)[:200]) if detail else ""))


SNAP_JS = """() => {
  const d = document.getElementById('oaDockList');
  const ans = d ? d.querySelectorAll('.bub.ai.ans') : [];
  const last = ans.length ? ans[ans.length-1] : null;
  const bolds = [];
  if (last) {
    last.innerText.split('\\n').forEach(function(ln){
      if (ln.includes('**') && bolds.length < 3) bolds.push(ln.trim().slice(0, 80));
    });
  }
  return {
    ansCount: ans.length,
    tables: last ? last.querySelectorAll('table').length : 0,
    charts: last ? last.querySelectorAll('.ans-chart svg').length : 0,
    rawPipe: last ? (last.innerText.includes('|---') || last.innerText.includes('| 维度层级')) : null,
    rawBold: last ? last.innerText.includes('**') : null,
    boldSamples: bolds,
    restored: d ? d.innerText.includes('已接上你上次的对话') : false,
    memo: localStorage.getItem('aios_oa_last_conv')
  };
}"""


def main():
    os.makedirs(OUT, exist_ok=True)
    s = httpx.Client(timeout=30, trust_env=False)
    login = s.post(API + "/auth/login", json={"username": "admin", "password": "Admin@123"}).json()
    tok = login["data"]["accessToken"]
    me = login["data"].get("user", login["data"])
    session = json.dumps({"token": tok, "user": me}, ensure_ascii=False)

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 480, "height": 960}, device_scale_factor=2)
        ctx.add_init_script(f"localStorage.setItem('aios_session', {json.dumps(session)})")
        pg = ctx.new_page()
        pg.goto(BASE + "/index.html", wait_until="networkidle")
        pg.wait_for_timeout(1500)

        # 真实提问（H5 输入框 → oaSend 真链路）
        pg.fill("#oaInput", QUESTION)
        pg.press("#oaInput", "Enter")
        print("[sent]", QUESTION)

        dock_tbl = ".bub.ai.ans table"
        # 图表模式下原表格折叠在 <details> 里（不可见），等 attached 即可
        pg.wait_for_selector(dock_tbl, timeout=TIMEOUT_MS, state="attached")
        prev = -1
        for _ in range(10):
            cnt = pg.locator("#oaDockList .bub").count()
            if cnt == prev:
                break
            prev = cnt
            pg.wait_for_timeout(1500)

        live = pg.evaluate(SNAP_JS)
        live.pop("memo", None)
        print("[live]", live)
        chk("L1 当场回答渲染出表格", live["tables"] >= 1, {k: live[k] for k in ("tables", "charts")})
        chk("L2 当场回答渲染出图表", live["charts"] >= 1, {k: live[k] for k in ("tables", "charts")})
        chk("L3 当场无裸 Markdown 表格符号", live["rawPipe"] is False, live["rawPipe"])
        if live["rawBold"]:
            print("[info] 当场回答含 ** 的行（formatAnswer 原生行为，历史须与其一致）:", live["boldSamples"])
        pg.screenshot(path=os.path.join(OUT, "01-live.png"), full_page=True)

        # 刷新 → oaRestoreLastConv 自动恢复历史（轮询 45s，输出诊断时间线）
        memo_before = pg.evaluate("() => localStorage.getItem('aios_oa_last_conv')")
        print("[memo before reload]", (memo_before or "NULL")[:160])
        pg.reload(wait_until="networkidle")
        hist = None
        for i in range(9):
            pg.wait_for_timeout(5000)
            snap = pg.evaluate(SNAP_JS)
            print(f"[t+{(i+1)*5}s] ansCount={snap['ansCount']} tables={snap['tables']} "
                  f"charts={snap['charts']} restored={snap['restored']} "
                  f"memo={'yes' if snap['memo'] else 'NULL'}")
            if snap["tables"] >= 1:
                hist = snap
                break
        if hist is None:
            hist = pg.evaluate(SNAP_JS)

        chk("H0 会话记忆已写入（刷新前 memo 存在）", bool(memo_before), (memo_before or "NULL")[:120])
        chk("H1 刷新后自动恢复上次会话（历史气泡出现）", hist["ansCount"] >= 1,
            f"ansCount={hist['ansCount']} restoredHint={hist['restored']}")
        chk("H2 历史回放渲染出表格（与当场同版式）", hist["tables"] >= 1, hist["tables"])
        chk("H3 历史回放渲染出图表（与当场同版式）", hist["charts"] >= 1, hist["charts"])
        chk("H4 历史回放无裸 Markdown 表格符号", hist["rawPipe"] is False, hist["rawPipe"])
        chk("H5 历史粗体渲染与当场一致", hist["rawBold"] == live["rawBold"],
            f"live={live['rawBold']} hist={hist['rawBold']}")
        if hist["rawBold"]:
            print("[info] 历史回放含 ** 的行:", hist["boldSamples"])
        pg.screenshot(path=os.path.join(OUT, "02-history-replay.png"), full_page=True)

        ctx.close(); b.close()

    n = sum(results)
    print(f"\n[SUMMARY] {n}/{len(results)} PASS")
    print("[STATUS] " + ("PASS" if n == len(results) else "FAIL"))
    sys.exit(0 if n == len(results) else 1)


if __name__ == "__main__":
    main()
