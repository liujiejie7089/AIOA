# -*- coding: utf-8 -*-
"""配置拉取**失败**时的界面归因核对（`_` 前缀＝一次性诊断，与套件区分）。

它存在的理由是一次真实误报：2026-09-18 后端重启期间用户在「项目与仓库」页看到

    toast：无法获取仓库联动配置，模块可能未启用
    页头：项目与仓库（**Gitee** 联动）
    横幅：仓库联动模块未启用 —— 后端尚未配置 **aioa.gitee.*** …请联系系统管理员开启配置

三句全是**错的**：配置一切正常，只是服务当时不在。把「拿不到」说成「没配置」，
会把用户和运维一起引向一个不存在的配置问题；页头回落成 Gitee 则在 gitea 部署上谎报托管方。

**怎么在不起停服务的前提下重现**：用 Playwright 拦截 `/gitee/config` 这一个请求。
两种失败形态都要覆盖：
  · `abort()`  ⇒ axios「Network Error」（服务彻底不可达）
  · `fulfill(500)` ⇒ 「Request failed with status code 500」（Vite 代理在后端不在时就是这么回）

断言的是**文案与状态分流**，不是实现细节：失败必须走「服务未响应 + 可重试」，
且**不得**出现「尚未配置 / aioa.gitee / Gitee 联动」；配置恢复后点「重试」必须能自愈。

用法：python scripts/_check_gitea_cfg_failure_ui.py
"""
import json
import sys

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
TENANT = "某某市某某区大数据管理局"
CFG_GLOB = "**/gitee/config*"

C = httpx.Client(timeout=60, trust_env=False)

RES = []


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:300]) if detail else ""))
    return bool(cond)


def login(name):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": "User@123",
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"], d["data"].get("refreshToken", "")


def seed(ctx, tok, user, refresh):
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s);"
        "localStorage.setItem('aioa.refreshToken', %s);"
        "localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(refresh), json.dumps(json.dumps(user, ensure_ascii=False)))
    )


def text(page):
    return page.evaluate("() => document.body ? document.body.innerText : ''")


def check_failure_page(page, tag):
    """失败形态的公共断言：必须说「服务未响应」，且不得指向配置或某一家托管方。"""
    t = text(page)
    chk(f"{tag}.1 横幅标题为「无法获取仓库联动配置」", "无法获取仓库联动配置" in t, t[:200])
    chk(f"{tag}.2 **不得**说「尚未配置」——把不可达说成缺配置会把排查引偏",
        "尚未配置" not in t, [ln for ln in t.splitlines() if "尚未配置" in ln][:3])
    chk(f"{tag}.3 **不得**出现具体配置键 aioa.gitee/aioa.gitea",
        "aioa.gitee" not in t and "aioa.gitea" not in t,
        [ln for ln in t.splitlines() if "aioa." in ln][:3])
    chk(f"{tag}.4 页头不得自称托管方（不知道就不能说）",
        "Gitee 联动" not in t and "Gitea 联动" not in t,
        [ln for ln in t.splitlines() if "联动" in ln][:3])
    chk(f"{tag}.5 提供「重试」入口", "重试" in t)
    chk(f"{tag}.6 不渲染数据卡（绑定/组织/初始化三张卡都不该出现）",
        all(k not in t for k in ("我的 Gitea 账号", "我的 Gitee 账号",
                                 "本企业 Gitea 组织", "本企业 Gitee 组织",
                                 "企业 Gitea 初始化", "企业 Gitee 初始化")), t[:300])


def main():
    tok, user, ref = login("dsj_admin")

    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)
        try:
            for tag, mode in (("F-abort", "abort"), ("F-500", "http500")):
                ctx = br.new_context(viewport={"width": 1440, "height": 1000})
                seed(ctx, tok, user, ref)
                page = ctx.new_page()

                def handler(route, _mode=mode):
                    if _mode == "abort":
                        route.abort()
                    else:
                        route.fulfill(status=500, content_type="application/json",
                                      body=json.dumps({"code": 500, "message": "服务不可用"}))
                page.route(CFG_GLOB, handler)

                page.goto(SHELL + "/gitee/projects", wait_until="networkidle")
                page.wait_for_timeout(2000)
                check_failure_page(page, tag)

                # 恢复后点「重试」必须自愈（否则「给个重试按钮」只是装饰）
                page.unroute(CFG_GLOB)
                page.get_by_role("button", name="重试").first.click()
                page.wait_for_timeout(3000)
                t = text(page)
                chk(f"{tag}.7 点「重试」后自愈：页头恢复自称 Gitea",
                    "Gitea 联动" in t, t[:200])
                chk(f"{tag}.8 重试后错误横幅消失", "无法获取仓库联动配置" not in t)
                ctx.close()
        finally:
            br.close()

    n_pass = sum(1 for _, ok in RES if ok)
    print("\n汇总：PASS=%d / %d" % (n_pass, len(RES)))
    return 0 if n_pass == len(RES) else 1


if __name__ == "__main__":
    sys.exit(main())
