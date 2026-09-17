# -*- coding: utf-8 -*-
"""V50 · 管理端「项目与仓库」渲染校验（无头 Edge）。

校验两件事，都是**只有真跑浏览器才能证明**的：

  1. **P0 回归**：租户管理员此前打开本页是**整页空白** ——
     `GiteeProjectsView` 的 `taskStats` 首帧为 null，模板 `(taskStats as GiteeTaskStats).PENDING`
     在渲染期解引用抛错，Vue 卸载整棵组件。类型断言把这个错误对 vue-tsc 藏住了，
     所以 typecheck 全绿也照样白屏。现在必须正常渲染出统计数字。

  2. **企业级 Gitee 组织卡片 + 角色门控**：
     「本企业 Gitee 组织」与「运维与校准」只对**租户管理员**可见，
     且非租户管理员**根本不应发起** `/gitee/tasks/stats` 与 `/gitee/tenant-config`
     请求 —— 这两个接口是 requireTenantAdmin，发出去就是 403，弹错即体验缺陷。
     所以这里断言的是「请求列表里没有它」，而不只是「卡片没渲染」。

  另收集控制台错误与 >=500 响应：必须为零。

前置：后端 :8080、Gitee 桩 :8090、管理端 shell :5173 均已启动。
"""
import json
import os

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
PATH = "/gitee/projects"
OUT = os.path.join(".workbuddy", "artifacts", "v50-ui")

C = httpx.Client(timeout=60, trust_env=False)
results = []


def chk(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(("  PASS " if cond else "  FAIL ") + tag + (f"  | {detail}" if detail else ""))


def login(name, pwd="User@123"):
    d = C.post(API + "/auth/login", json={"username": name, "password": pwd}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"].get("user") or {}


def open_shell(b, tok, user):
    """打开本页并旁听：控制台错误、>=500 响应、以及所有 /api/v1/gitee 请求。"""
    ctx = b.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s); localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(json.dumps(user, ensure_ascii=False)))
    )
    errs, bad, calls = [], [], []
    page = ctx.new_page()
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 500 else None)
    page.on("request", lambda r: calls.append(r.url) if "/api/v1/gitee" in r.url else None)
    page.goto(SHELL + PATH, wait_until="networkidle")
    page.wait_for_timeout(3500)
    return page, errs, bad, calls


def main():
    os.makedirs(OUT, exist_ok=True)
    ten = login("znkj_admin")          # 租户管理员（P0 的受害者）
    org = login("znkjyf_admin")        # 企业管理员
    dept = login("znsfb_ldr")          # 部门负责人

    cases = [
        ("租户管理员 znkj_admin", ten, True),
        ("企业管理员 znkjyf_admin", org, False),
        ("部门负责人 znsfb_ldr", dept, False),
    ]

    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)
        for label, (tok, user), is_tenant_admin in cases:
            print(f"\n[{label}] roles={user.get('roles')}")
            page, errs, bad, calls = open_shell(br, tok, user)

            # (1) 未被路由守卫重定向回 /home
            chk(f"{label} · 未被重定向回 /home", page.url.rstrip("/").endswith(PATH), page.url)

            # (2) 页面真的渲染了（P0：此前这里是全白）
            body = page.inner_text("body")
            has_list = "项目列表" in body
            chk(f"{label} · 页面非空白（项目列表已渲染）", has_list, f"body_len={len(body)}")
            chk(f"{label} · 账号卡片已渲染", "我的 Gitee 账号" in body)

            # (3) 企业级组织卡片 + 运维卡片：仅租户管理员
            has_org_card = "本企业 Gitee 组织" in body
            has_ops_card = "运维与校准" in body
            chk(f"{label} · 企业组织卡片与角色匹配", has_org_card == is_tenant_admin,
                f"has_org_card={has_org_card}")
            chk(f"{label} · 运维卡片与角色匹配", has_ops_card == is_tenant_admin,
                f"has_ops_card={has_ops_card}")

            # (4) 非租户管理员**不得发起**这两个 requireTenantAdmin 接口
            stats_calls = [u for u in calls if "/gitee/tasks/stats" in u]
            cfg_calls = [u for u in calls if "/gitee/tenant-config" in u]
            if is_tenant_admin:
                chk(f"{label} · 已发起 tasks/stats", len(stats_calls) >= 1, stats_calls[:1])
                chk(f"{label} · 已发起 tenant-config", len(cfg_calls) >= 1, cfg_calls[:1])
                # P0 的直接证据：统计数字渲染出来（而不是抛 null 异常整页卸载）
                chk(f"{label} · 运维统计数字已渲染（P0 回归）",
                    any(k in body for k in ("待处理（PENDING）", "已完成（DONE）")), "")
            else:
                chk(f"{label} · 未发起 tasks/stats（否则 403）", not stats_calls, stats_calls)
                chk(f"{label} · 未发起 tenant-config（否则 403）", not cfg_calls, cfg_calls)

            # (5) 无控制台错误、无 5xx
            chk(f"{label} · 无控制台错误", not errs, errs[:2])
            chk(f"{label} · 无 5xx 响应", not bad, bad[:2])

            shot = os.path.join(OUT, f"{label.split()[0]}-projects.png")
            page.screenshot(path=shot, full_page=True)
            print(f"    截图 {shot}")
            page.context.close()
        br.close()

    ok = sum(1 for _, c, _ in results if c)
    total = len(results)
    print("\n" + "=" * 74)
    print(f"PASS={ok}  FAIL={total - ok}  （共 {total}）")
    print("=" * 74)
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
