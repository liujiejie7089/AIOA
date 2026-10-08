# -*- coding: utf-8 -*-
"""核验用户端两处修复（2026-10-08）：

  1. 通讯录「联系人」排除自己 —— 登录者不该在自己的联系人列表里出现。
     判据：渲染出的联系人卡片里**没有**登录者昵称；同事在（对照，防「整页没渲染」假绿）；
     「共 N 人」计数与卡片数一致（排除自己时计数同步减一，否则口径漂移）。
  2. 项目面板接真 PM 模块 —— 管理员把成员加进项目后，成员在用户端能看到该项目。
     判据：成员账号（fagai_li，T1008 两项目的成员）的「任务 → 项目」面板出现
     T1008-业务 / T1008-开发 两张卡片，且开发项目的卡片带「仓库」计数；
     负向对照：同机构**非成员**账号（fagai_liu）的面板里**没有** T1008 项目
     （证明面板不是「人人看全量」的假绿）。

前置：
  · 后端 :8080 + 用户端 :5181（serve.py）都在跑；
  · 测试数据在位：T1008 前缀两项目，fagai_li 是两项目成员（造数脚本见
    .workbuddy/memory/2026-10-08.md §测试数据，或本文件末尾 main 的自备参数）。

用法：python scripts/_verify_h5_pm_contacts.py
输出证据截图到 logs/proof/。
"""
import json
import os
import re
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
ADMIN = "dsj_admin"
BASE = "http://127.0.0.1:5181/index.html"
PROOF = Path(__file__).resolve().parent.parent / "logs" / "proof"
PROOF.mkdir(parents=True, exist_ok=True)

MEMBER = ("fagai_li", "李思远", "刘敏")    # T1008 两项目的成员（对照同事 = 刘敏）
OUTSIDER = ("fagai_liu", "刘敏", "李思远")  # 同机构、非 T1008 成员（对照同事 = 李思远）
PWD = "User@123"

res = []


def preflight():
    """fixture 预检（铁律 15）：T1008 两项目必须都在、fagai_li 必须是成员、
    开发项目必须已绑 1 个仓库 —— 缺任何一样，后面的断言会落到未被设计覆盖的分支上。
    缺失时**大声退出**，不许静默跑成别的意思。"""
    with httpx.Client(timeout=30, trust_env=False) as c:
        d = c.post(API + "/auth/login", json={"username": ADMIN, "password": PWD,
                                              "tenantName": TENANT}).json()
        assert d.get("code") == 0, d.get("message")
        h = {"Authorization": "Bearer " + d["data"]["accessToken"]}
        rows = c.get(API + "/pm/projects", headers=h, params={"pageSize": 200}).json().get("data") or []
        biz = next((x for x in rows if str(x.get("name", "")).startswith("T1008-业务")), None)
        dev = next((x for x in rows if str(x.get("name", "")).startswith("T1008-开发")), None)
    missing = []
    if not biz:
        missing.append("T1008-业务项目")
    if not dev:
        missing.append("T1008-开发项目")
    if dev and not dev.get("repoCount"):
        missing.append("开发项目的绑定仓库")
    if missing:
        print("★ fixture 缺失：%s" % "、".join(missing))
        print("  请先按 .workbuddy/memory/2026-10-08.md §测试数据 的步骤重造再跑本脚本。")
        print("  （fixture 缺失时硬跑 = 断言落到未覆盖分支，本脚本拒绝这样做）")
        sys.exit(2)
    print("fixture 在位：业务 id=%s 开发 id=%s（开发 仓库数=%s）"
          % (biz["id"], dev["id"], dev.get("repoCount")))



def chk(tag, cond, detail=""):
    res.append((tag, bool(cond)))
    print(("[OK]   " if cond else "[FAIL] ") + tag + (("  " + str(detail)) if detail and not cond else ""))


def login(page, user):
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    page.fill("#lgUser", user)
    page.fill("#lgPass", PWD)
    page.click("#lgBtn")
    page.wait_for_selector("body.auth", timeout=15000)
    page.wait_for_timeout(2500)


def goto_tab(page, view):
    page.click('#oaTabs .tab[data-view="%s"]' % view)
    page.wait_for_timeout(2500)


def check_contacts(page, self_name, colleague, tag):
    goto_tab(page, "org")
    cards = page.locator("#oaOrgList .contact-card")
    names = cards.all_inner_texts()
    cnt = page.locator("#oaOrgCnt").inner_text()
    page.screenshot(path=str(PROOF / ("h5-contacts-%s.png" % tag)), full_page=True)
    chk("通讯录排除自己[%s]" % tag, not any(self_name in t for t in names),
        [t.splitlines()[0] for t in names][:6])
    chk("对照：同事仍在通讯录[%s]" % tag, any(colleague in t for t in names), names[:2])
    m = re.search(r"共\s*(\d+)\s*人", cnt)
    chk("「共 N 人」与卡片数一致[%s]" % tag, m and int(m.group(1)) == cards.count(),
        "cnt=%r cards=%d" % (cnt, cards.count()))


def check_projects(page, expect, tag):
    goto_tab(page, "collab")
    page.click('#oaRail .rail-item[data-panel="projects"]')
    page.wait_for_timeout(2500)   # 等 /v1/pm/projects 回来重绘
    body = page.locator("#p-projects").inner_text()
    page.screenshot(path=str(PROOF / ("h5-projects-%s.png" % tag)), full_page=True)
    has_biz = "T1008-业务" in body
    has_dev = "T1008-开发" in body
    if expect:
        chk("★ 成员在项目面板看到 T1008 业务+开发两项目[%s]" % tag, has_biz and has_dev,
            body[:200])
        chk("★ 开发项目卡片带仓库计数[%s]" % tag, has_dev and ("仓库 1" in body), body[:200])
        chk("★ 业务项目卡片自称「业务项目」、不带仓库计数[%s]" % tag,
            has_biz and ("业务项目" in body), body[:200])
    else:
        chk("★★ 负向对照：非成员看不到 T1008 项目[%s]" % tag,
            (not has_biz) and (not has_dev), body[:200])
    return body


preflight()

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="msedge", headless=True)
    errs = []
    ctx = br.new_context(viewport={"width": 390, "height": 844},
                         device_scale_factor=2, locale="zh-CN")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))

    login(page, MEMBER[0])
    check_contacts(page, MEMBER[1], MEMBER[2], "member")
    check_projects(page, True, "member")
    ctx.close()

    ctx = br.new_context(viewport={"width": 390, "height": 844},
                         device_scale_factor=2, locale="zh-CN")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    login(page, OUTSIDER[0])
    check_contacts(page, OUTSIDER[1], OUTSIDER[2], "outsider")
    check_projects(page, False, "outsider")
    ctx.close()

    chk("全程无前端 JS 运行时异常", not errs, errs[:2])
    br.close()

bad = [t for t, ok in res if not ok]
print("\n=== 真机 %d/%d 通过 ===" % (len(res) - len(bad), len(res)))
for t in bad:
    print("  FAIL " + t)
sys.exit(1 if bad else 0)
