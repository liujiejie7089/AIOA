# -*- coding: utf-8 -*-
"""仓库配置页「Webhook 回调地址未配置」提示的**同源一致性**哨兵。

为什么值得单独一条：
    「仓库建出来了、项目却停在未就绪」在本地环境是 100% 命中（Gitee 无法回调 127.0.0.1），
    而根因只在后端一行配置里。后端 /gitee/config 已给出 `webhookBaseUrlConfigured`，
    前端若不消费它，管理员配完组织/令牌仍会一脸疑惑地收到一堆 FAILED 项目
    （2026-10-09 实测：租户 2 的 10 个项目全 FAILED，error_msg 全指向 webhook-base-url）。

判据（铁律 12，判据不得与被测对象同源）：
    断言的是「**界面提示** 与 **后端 flag** 一致」，而不是「界面上有这段字」。
    flag=false → 提示必须出现；flag=true → 提示必须不出现。两边各自取数，任一侧漂移即报红。
    这样它在本机（flag=false）与配好 Webhook 的环境（flag=true）**都**是有区分力的。

用法：python scripts/_verify_gitee_webhook_hint.py    （需后端 :8080 已起）
"""
import sys

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:8080/aioa/web"
REPO_CFG = SHELL + "/settings/repo-config"
TENANT = "某某市某某区大数据管理局"
ADMIN, PWD = "dsj_admin", "User@123"
HINT = "Webhook 回调地址未配置"

RES = []


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:300]) if detail else ""))
    return bool(cond)


def ui_login(page, user):
    page.goto(SHELL + "/login", wait_until="networkidle")
    page.fill('input[autocomplete="organization"]', TENANT)
    page.fill('input[autocomplete="username"]', user)
    page.fill('input[autocomplete="current-password"]', PWD)
    page.click(".login-btn")
    page.wait_for_url("**/home", timeout=20000)


def main():
    # ---- 事实源头：后端配置
    r = httpx.post(API + "/auth/login", timeout=30, trust_env=False,
                   json={"username": ADMIN, "password": PWD, "tenantName": TENANT}).json()
    if r.get("code") != 0:
        raise SystemExit("登录失败：%s" % r.get("message"))
    h = {"Authorization": "Bearer " + r["data"]["accessToken"]}
    cfg = httpx.get(API + "/gitee/config", headers=h, timeout=30, trust_env=False).json().get("data") or {}
    flag = cfg.get("webhookBaseUrlConfigured")
    chk("W1 后端 /gitee/config 给出 webhookBaseUrlConfigured（布尔）", isinstance(flag, bool), flag)
    if not isinstance(flag, bool):
        raise SystemExit("前提不成立，无法判定一致性")

    # ---- 界面
    errors = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        page = b.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        ui_login(page, ADMIN)
        page.goto(REPO_CFG, wait_until="networkidle")
        page.wait_for_timeout(1200)   # 等 /gitee/config 回填
        body = page.locator("body").inner_text()
        visible = HINT in body
        b.close()

    print("  [info] backend flag=%s / ui hint visible=%s" % (flag, visible))
    chk("W2 ★界面提示与后端 flag 一致（flag=false⇒出现；flag=true⇒不出现）",
        visible == (not flag), "flag=%s visible=%s" % (flag, visible))
    chk("W3 全程无前端 JS 异常", not errors, errors[:2])

    ok = sum(1 for _, v in RES if v)
    print("\n[SUMMARY] %d/%d 通过" % (ok, len(RES)))
    if ok != len(RES):
        sys.exit(1)


if __name__ == "__main__":
    main()
