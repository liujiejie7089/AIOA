# -*- coding: utf-8 -*-
"""真实链路端到端：用户问「成都市非遗工坊电商平台销量柱状图」→ agent 回答 → H5 渲染图表。

跑法：agent/.venv/Scripts/python.exe scripts/_verify_chart_live_e2e.py
产物：docs/screenshots/answer-chart-2026-11-21/05-live-e2e.png
      docs/screenshots/answer-chart-2026-11-21/live-answer.txt
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import os
import re

import httpx
import requests
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots", "answer-chart-2026-11-21")
API = "http://127.0.0.1:8080/api/v1"
BASE = "http://127.0.0.1:5181"
QUESTION = "成都市非遗工坊电商平台销量柱状图"
MODEL = "dashscope"  # deepseek 余额耗尽，用 qwen-plus（与既有验收口径一致）

results = []
def chk(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS" if cond else "FAIL") + " | " + name + " | " + str(detail)[:180])


def run_live():
    s = httpx.Client(timeout=30, trust_env=False)
    login = s.post(API + "/auth/login", json={"username": "admin", "password": "Admin@123"}).json()
    tok = login["data"]["accessToken"]
    h = {"Authorization": "Bearer " + tok}
    conv = s.post(API + "/conversations", headers=h,
                  json={"title": "图表渲染活体验收", "source": "aios-client"}).json()
    cid = conv["data"]["id"]
    body = {"text": QUESTION, "context": {}, "kb_on": True, "model_ref": MODEL}
    rr = s.post(API + "/conversations/%s/runs" % cid, headers=h, json=body, timeout=30)
    rid = (rr.json().get("data") or {}).get("runId") or (rr.json().get("data") or {}).get("id")
    print("[run]", rid)
    rs = requests.Session()
    rs.trust_env = False
    with rs.get(API + "/runs/%s/events" % rid, headers=h, stream=True,
                timeout=(15, 300)) as resp:
        raw = resp.content.decode("utf-8", "replace")
    cur = None
    completed = None
    for line in re.split(r"\r?\n", raw):
        if line.startswith("event:"):
            cur = line[6:].strip()
        elif line.startswith("data:") and cur == "message.completed":
            completed = json.loads(line[5:].strip())
    content = (completed or {}).get("content") or ""
    return tok, login["data"].get("user", login["data"]), content


def main():
    os.makedirs(OUT, exist_ok=True)
    tok, me, answer = run_live()
    with open(os.path.join(OUT, "live-answer.txt"), "w", encoding="utf-8") as f:
        f.write("问题：" + QUESTION + "\n\n" + answer)
    print("[answer len]", len(answer))

    chk("L1 真实回答非空", len(answer) > 30, f"len={len(answer)}")
    # 回答里是否出现「分类 + 数量」统计表（agent 规则 5 的三列表）
    has_table = bool(re.search(r"\|\s*[^\|]+\|\s*\d+\s*\|", answer))
    chk("L2 回答含统计表（分类列 + 数值列）", has_table, answer[:200])
    has_intent = "柱状图" in answer or "柱形" in answer
    chk("L3 回答含明确图表意图词", has_intent, [w for w in ["柱状图", "柱形"] if w in answer])

    # 把真实回答送进 H5 formatAnswer，检查图表是否被渲染
    session = json.dumps({"token": tok, "user": me}, ensure_ascii=False)
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 900, "height": 1100}, device_scale_factor=2)
        ctx.add_init_script(f"localStorage.setItem('aios_session', {json.dumps(session)})")
        pg = ctx.new_page()
        pg.goto(BASE + "/index.html", wait_until="networkidle")
        pg.wait_for_timeout(1000)
        mode = pg.evaluate("() => document.querySelector('.phone.oa-mode') ? 'oa' : 'classic'")
        result = pg.evaluate("""(a) => {
            const html = formatAnswer(a);
            const list = document.getElementById('oaDockList') || document.getElementById('msgs');
            if(!list) return {ok:false, why:'no container'};
            list.innerHTML='';
            const q=document.createElement('div'); q.className='bub me'; q.textContent='成都市非遗工坊电商平台销量柱状图';
            list.appendChild(q);
            const bubble=document.createElement('div'); bubble.className='bub ai ans'; bubble.innerHTML=html;
            list.appendChild(bubble);
            const home=document.getElementById('v-home'); if(home) home.classList.add('chatting');
            if(typeof go==='function' && document.getElementById('oaDockList')===null) go('page-chat');
            list.scrollTop=list.scrollHeight;
            return {ok:true, chart: list.querySelectorAll('.ans-chart').length,
                    svg: list.querySelectorAll('.ans-chart svg').length,
                    label: list.querySelector('.ans-chart svg') ? list.querySelector('.ans-chart svg').getAttribute('aria-label') : ''};
        }""", answer)
        print("[render]", result, "mode=", mode)
        chk("L4 真实回答在 H5 渲染出图表", result.get("ok") and result.get("chart", 0) >= 1,
            result)
        pg.screenshot(path=os.path.join(OUT, "05-live-e2e.png"), full_page=True)
        print("[shot] live e2e -> 05-live-e2e.png")
        ctx.close(); b.close()

    print("\n[STATUS] " + ("PASS" if all(results) else "FAIL") + f" ({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
