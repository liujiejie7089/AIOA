# -*- coding: utf-8 -*-
"""用户端 H5「我的知识库」可见性探针：读 state.kbDocs 与 #kbList 真实渲染。

用法：python scripts/_probe_kb_share.py [username] [password]
"""
import json
import sys

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
BASE = "http://127.0.0.1:5181"
USER = sys.argv[1] if len(sys.argv) > 1 else "fagai_admin"
PWD = sys.argv[2] if len(sys.argv) > 2 else "User@123"

c = httpx.Client(timeout=30, trust_env=False)
d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
assert d.get("code") == 0, d
tok, me = d["data"]["accessToken"], d["data"].get("user", {})
print(f"登录 {USER} tenant={me.get('tenantId')} inst={me.get('institutionId')} roles={me.get('roles')} uid={me.get('id')}")

h = {"Authorization": "Bearer " + tok}
api_docs = c.get(f"{API}/kb/documents", headers=h).json().get("data") or []
print(f"接口 /kb/documents 返回 {len(api_docs)} 条：")
for x in api_docs:
    print(f"   {x['name']!r} scope={x['scope']} owner={x['ownerUserId']} state={x['state']}")

session = json.dumps({"token": tok, "user": me}, ensure_ascii=False)
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(f"localStorage.setItem('aioa_session', {json.dumps(session)})")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    reqs = []
    page.on("response", lambda r: reqs.append((r.status, r.url)) if "kb/" in r.url else None)
    page.goto(BASE + "/index.html", wait_until="networkidle")
    page.wait_for_timeout(4000)

    docs = page.evaluate("() => (state.kbDocs||[]).map(d=>({name:d.name,scope:d.scope,owner:d.ownerUserId,state:d.state}))")
    print(f"\nstate.kbDocs = {json.dumps(docs, ensure_ascii=False, indent=2)}")
    cnt = page.eval_on_selector("#kbCount", "el=>el.innerText") if page.query_selector("#kbCount") else "(无)"
    txt = page.eval_on_selector("#kbList", "el=>el.innerText") if page.query_selector("#kbList") else "(无)"
    print(f"#kbCount = {cnt!r}")
    print(f"#kbList  渲染 = {txt!r}")
    print(f"kb 相关请求 = {reqs}")
    print(f"JS 异常 = {errs}")
    b.close()
