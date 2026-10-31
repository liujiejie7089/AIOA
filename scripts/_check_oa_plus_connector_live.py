# -*- coding: utf-8 -*-
"""真实链路哨兵：「＋」浮层关闭连接器后再开启，不得重新认证（2026-10-31）

与 `_check_oa_plus_connector_no_reauth.py` 的分工：
  · 那个是**离线打桩**（file:// + 替换 API），验渲染与分支逻辑，秒级、不需要服务；
  · 这个是**真实链路**（:5181 真页面 + :8080 真后端 + 真实登录），
    用 `page.on("request")` 直接数**真实网络请求**，能抓到打桩掩盖不掉的差异
    （字段名不一致、缓存没刷、真实返回结构变化）。
两者互补，不是重复。

判据：
  L1 真实登录 zhangsan 成功（走 localStorage 会话恢复 + /v1/auth/me）
  L2 浮层渲染出 wecom_cli 且显示「已连接」（真实接口数据）
  L3 关掉开关（确认）→ 再打开开关
  L4 ★全程**没有任何** `GET /v1/connectors/{code}`（detail）请求 ——
     该请求是 openConnector 弹「填授权码 / 扫码」的前置；没有它就证明没走认证
  L5 页面上没有出现凭据输入行 .oa-ef-row
  L6 开关最终 aria-checked=true（恢复调用）
  L7 回库：connector_connection.status 仍是 CONNECTED（关闭/开启没有破坏授权）

用法：python scripts/_check_oa_plus_connector_live.py [--base http://127.0.0.1:5181]
前置：H5 :5181 与后端 :8080 都在跑；zhangsan 的 wecom_cli 已连接。
退出码 = 失败项数。
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

MYSQL = "D:/dev/mysql/mysql-8.4.10-winx64/bin/mysql.exe"
PASS, FAIL = [], []


def chromium_exe():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not root.exists():
        return None
    for pat in ("chromium-*/chrome-win64/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
        hits = sorted(root.glob(pat))
        if hits:
            return str(hits[-1])
    return None


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + str(detail)[:400]))


def api(base, path, method="GET", token=None, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def db_status(user_id=2, code="wecom_cli"):
    try:
        out = subprocess.run([MYSQL, "-uroot", "-N", "-B", "aios", "-e",
                              "SELECT status FROM connector_connection WHERE user_id=%d "
                              "AND connector_code='%s' AND deleted_at IS NULL" % (user_id, code)],
                             capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    return (out.stdout or "").strip() or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5181")
    ap.add_argument("--api-base", default="http://127.0.0.1:8080")
    args = ap.parse_args()

    # L1 先拿真实 token（H5 走 localStorage 会话恢复，格式 {token, user}）
    try:
        d = api(args.api_base, "/api/v1/auth/login", "POST",
                body={"username": "zhangsan", "password": "User@123"})
        token = (d.get("data") or {}).get("accessToken")
        me = api(args.api_base, "/api/v1/auth/me", token=token)["data"]
    except Exception as e:  # noqa: BLE001
        print("[FAIL] 登录失败，无法做真实链路验证：%s" % e)
        return 1
    session = {"token": token, "user": {"id": me.get("id"), "username": me.get("username"),
                                        "nickname": me.get("nickname") or me.get("username"),
                                        "roles": me.get("roles") or []}}
    chk("L1 真实登录 zhangsan 成功", bool(token), "token_len=%s" % len(token or ""))

    detail_hits = []

    with sync_playwright() as pw:
        exe = chromium_exe()
        browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        ctx = browser.new_context(viewport={"width": 420, "height": 900})
        ctx.add_init_script("try{localStorage.setItem('aios_session', %s);}catch(e){}"
                            % json.dumps(json.dumps(session, ensure_ascii=False)))
        page = ctx.new_page()
        # 真实网络监听：openConnector() 必先 GET /v1/connectors/{code} 取 detail
        page.on("request", lambda r: detail_hits.append(r.url)
                if r.method == "GET" and "/v1/connectors/" in r.url and r.url.rstrip("/").split("/")[-1] == "wecom_cli"
                else None)

        page.goto(args.base.rstrip("/") + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)          # 等 /auth/me 恢复会话 + 首屏
        authed = page.evaluate("() => document.body.classList.contains('auth')")
        chk("L1b 页面以已登录态进入（body.auth）", authed is True, "auth=%s" % authed)

        page.evaluate("() => { window.oaState.mode='oa'; if(window.oaBoot) window.oaBoot(); }")
        page.wait_for_timeout(600)

        # L2 打开「＋」浮层（真实点击）
        page.locator("#oaAttachBtn").click()
        page.wait_for_timeout(1500)
        SEL = '#oaPlusConns .pm-conn[data-code="wecom_cli"]'
        sw = page.locator(SEL + " .pm-sw").first
        if sw.count() == 0:
            chk("L2 浮层渲染出连接器", False,
                page.eval_on_selector("#oaPlusConns", "el => el.innerText") if page.locator("#oaPlusConns").count() else "无 oaPlusConns")
            browser.close()
            return len(FAIL)
        sub = page.eval_on_selector(SEL + " .pm-main span", "el => el.innerText")
        chk("L2 浮层显示「已连接」（真实接口数据）", "已连接" in sub, sub)

        # L3 关 → 确认 → 再开
        sw.click()
        page.wait_for_timeout(500)
        page.locator(".notif-mask [data-dlg-ok]").first.click()
        page.wait_for_timeout(800)
        page.locator("#oaAttachBtn").click()
        page.wait_for_timeout(1500)
        page.locator(SEL + " .pm-sw").first.click()
        page.wait_for_timeout(1200)

        cred_rows = page.locator(".oa-ef-row").count()
        chk("L4 ★真实请求里没有 GET /v1/connectors/wecom_cli（detail）⇒ 没走认证",
            len(detail_hits) == 0, "detail 请求=%s" % detail_hits[:3])
        chk("L5 页面没有出现凭据输入层 .oa-ef-row", cred_rows == 0, "count=%d" % cred_rows)

        # 再看一眼开关状态
        page.locator("#oaAttachBtn").click()
        page.wait_for_timeout(1500)
        aria = page.eval_on_selector(SEL + " .pm-sw", "el => el.getAttribute('aria-checked')")
        chk("L6 开关恢复为打开（aria-checked=true）", aria == "true", "aria=%s" % aria)

        browser.close()

    st = db_status()
    chk("L7 回库：连接器仍是 CONNECTED（开关没动授权）", st == "CONNECTED", "db.status=%s" % st)

    print("\n" + "=" * 56)
    print("合计 %d 项，通过 %d 项，失败 %d 项" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    return len(FAIL)


if __name__ == "__main__":
    sys.exit(main())
