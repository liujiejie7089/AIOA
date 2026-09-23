# -*- coding: utf-8 -*-
"""管理端「知识库」页真实呈现探针（逐角色单独进程运行）。

用法：python scripts/_probe_kb_console.py <username> [password]

打印：知识库页是否 403 提示、两个 tab 各自的行数、表格空态文案、控制台报错。
"""
import json
import sys

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
CONSOLE = "http://127.0.0.1:8080/aioa/web/kb"
USER = sys.argv[1] if len(sys.argv) > 1 else "dsj_admin"
PWD = sys.argv[2] if len(sys.argv) > 2 else "User@123"

c = httpx.Client(timeout=30, trust_env=False)
d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
assert d.get("code") == 0, d
tok, user = d["data"]["accessToken"], d["data"].get("user") or {}
print(f"登录 {USER} tenant={user.get('tenantId')} roles={user.get('roles')}")

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s);"
        "localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(json.dumps(user)))
    )
    page = ctx.new_page()
    errs, kb_reqs = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("response", lambda r: kb_reqs.append((r.status, r.url))
            if "/kb/" in r.url else None)
    page.goto(CONSOLE, wait_until="networkidle")
    page.wait_for_timeout(3000)
    print(f"URL = {page.url}")

    def txt(sel, limit=400):
        el = page.query_selector(sel)
        return el.inner_text()[:limit] if el else "(未找到 %s)" % sel

    print(f"页面主标题 = {txt('.card-header, h2, .page-title', 120)!r}")
    alert = page.query_selector(".el-alert")
    print(f"顶部提示 = {alert.inner_text() if alert else '(无)'}")
    print(f"tab 名称 = {page.eval_on_selector_all('.el-tabs__item', 'els=>els.map(e=>e.innerText)')}"
          if page.query_selector('.el-tabs__item') else "tab 名称 = (无)")
    active = page.eval_on_selector_all(
        ".el-tabs__item.is-active", "els=>els.map(e=>e.innerText)") \
        if page.query_selector(".el-tabs__item") else []
    print(f"当前选中 tab = {active}")
    print(f"表格行数 = {len(page.query_selector_all('.el-table__body tbody tr'))}")
    print(f"页面可见文本(前 600 字) =\n{txt('body', 600)}")
    print(f"kb 请求 = {kb_reqs}")
    print(f"JS 异常 = {errs}")
    b.close()
