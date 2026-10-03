# -*- coding: utf-8 -*-
"""核验「项目与仓库」不再是一级菜单、代码仓库收敛到【开发项目】（2026-10-03 信息架构调整）。

改动前实测的旧行为（本脚本的对照基线）：侧栏「成果与项目」组下有**两个**并列入口
——「项目管理」与「项目与仓库」，同一个仓库存在两处入口。

现在要求的三条口径：
  1. 侧栏「成果与项目」组**不再有**「项目与仓库」；同组的「成果沉淀」「项目管理」仍在
     （对照，避免「整组菜单被删」「页面没渲染」被当成通过）；
  2. 侧栏「系统配置」组**新增**「仓库配置」（租户级配置的落点）；同组「系统参数」仍在；
  3. 代码仓库只跟着**开发项目**出现：
     · 开发项目详情 → 有「代码仓库」页签，页签内渲染状态列与失败原因列，且有「重试建仓」/「仓库总览与配置」入口；
     · 业务项目详情 → **没有**该页签（BR-01 的界面侧对照）。
  4. 两个路由的形态分离：`/settings/repo-config` 只渲染配置卡（**不**渲染仓库列表），
     而 `/gitee/projects`（已不进菜单）仍渲染仓库列表 —— 既有深链与钉住本页的两个哨兵不受影响。

⚠️ 踩过的坑（改本脚本前先读）：
  a) **侧栏子菜单默认折叠**，Element Plus 把子项包在折叠过渡里，`inner_text()`（等价 innerText）
     **不返回不可见文本** ⇒ 必须**先展开**再读，且要用 `text_content()`。
  b) 判「菜单项不存在」**不能**只查整页 body —— 正文里也可能出现同一个词
     （历史上 GiteeProjectsView 的 desc 就写过「项目与仓库」；2026-10-03 页头/desc 已
     改名「仓库总览」，但**这个风险不随文案改动消失**——任何页面都可能被后续需求再写回
     这个词），会把「菜单项撤了」与「正文没这个词」混为一谈。所以本脚本只读**侧栏容器**
     `.layout-menu` 的 textContent。
  c) 代码仓库页签的断言要**先切页签**再读内容：详情页默认停在「概览」，
     不切页签就断言会得到一个「内容里没有仓库」的假红。

用法：python scripts/_verify_repo_menu_merge.py      （需后端 :8080 已起，且管理端产物已同步）
输出证据截图到 logs/proof/。
"""
import json
import os

import httpx

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"

from pathlib import Path

from playwright.sync_api import sync_playwright

SHELL = "http://127.0.0.1:8080/aioa/web"
PROOF = Path(__file__).resolve().parent.parent / "logs" / "proof"
PROOF.mkdir(parents=True, exist_ok=True)

REMOVED_ITEM = "项目与仓库"
NEW_ITEM = "仓库配置"

res = []


def chk(tag, cond, detail=""):
    res.append((tag, bool(cond)))
    print(("[OK]   " if cond else "[FAIL] ") + tag + (("  " + str(detail)) if detail and not cond else ""))


def pick_projects():
    """取一个开发项目、一个业务项目的 id —— 不硬编码 id（数据会变），按类型现取。

    取不到就抛错：**跳过等于没验**，不能让「没有开发项目」把第 3 条悄悄放过。
    """
    with httpx.Client(timeout=30, trust_env=False) as c:
        d = c.post(API + "/auth/login", json={"username": USER, "password": PWD,
                                              "tenantName": TENANT}).json()
        assert d.get("code") == 0, d
        h = {"Authorization": "Bearer " + d["data"]["accessToken"]}
        r = c.get(API + "/pm/projects", headers=h, params={"pageSize": 100}).json()
    rows = r.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    dev = next((x for x in rows if x.get("projectType") == "DEV"), None)
    biz = next((x for x in rows if x.get("projectType") == "BUSINESS"), None)
    return dev, biz


def text_of(page, selector):
    """读容器 textContent：折叠中的子项也算（inner_text 对不可见文本会静默返回空）。"""
    loc = page.locator(selector)
    if loc.count() == 0:
        return ""
    return loc.first.text_content() or ""


def expand(page, group):
    """展开指定子菜单分组；返回是否找到该分组。"""
    grp = page.locator(f'.el-sub-menu__title:has-text("{group}")')
    if grp.count() == 0:
        return False
    grp.first.click()
    page.wait_for_timeout(600)
    return True


dev, biz = pick_projects()
print("取样：开发项目=%s  业务项目=%s" % (dev and dev.get("name"), biz and biz.get("name")))

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge", headless=True)
    page = b.new_context(viewport={"width": 1600, "height": 950}).new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))

    page.goto(SHELL + "/login", wait_until="networkidle")
    page.fill('input[autocomplete="organization"]', TENANT)
    page.fill('input[autocomplete="username"]', USER)
    page.fill('input[autocomplete="current-password"]', PWD)
    page.click("button:has-text('登')")
    page.wait_for_timeout(4000)
    chk("真机登录进入工作台", "/login" not in page.url, page.url)

    # ---------------------------------------------------------------- 段 1：菜单
    ok_output = expand(page, "成果与项目")
    chk("对照：侧栏分组「成果与项目」仍在", ok_output)
    ok_syscfg = expand(page, "系统配置")
    chk("对照：侧栏分组「系统配置」仍在", ok_syscfg)
    page.wait_for_timeout(400)

    sidebar = text_of(page, ".layout-menu")
    page.screenshot(path=str(PROOF / "repo-merge-1-menu.png"), full_page=True)

    chk("★ 侧栏已无「%s」菜单项" % REMOVED_ITEM, REMOVED_ITEM not in sidebar,
        [ln for ln in sidebar.splitlines() if REMOVED_ITEM in ln][:3])
    for label in ("成果沉淀", "项目管理"):
        chk("对照：「成果与项目」下「%s」仍在" % label, label in sidebar,
            sidebar.splitlines()[:16])
    chk("★ 侧栏「系统配置」下出现「%s」" % NEW_ITEM, NEW_ITEM in sidebar,
        sidebar.splitlines()[:24])
    for label in ("系统参数",):
        chk("对照：「系统配置」下「%s」仍在" % label, label in sidebar,
            sidebar.splitlines()[:24])

    # ------------------------------------------- 段 2：仓库配置页只做配置（无仓库列表）
    page.goto(SHELL + "/settings/repo-config", wait_until="networkidle")
    page.wait_for_timeout(3500)
    page.screenshot(path=str(PROOF / "repo-merge-2-repo-config.png"), full_page=True)
    cfg_body = page.inner_text("body")
    chk("★ /settings/repo-config 页头自称「仓库配置」", NEW_ITEM in cfg_body,
        cfg_body[:200])
    chk("★ 配置页**不渲染**仓库列表卡", "项目列表" not in cfg_body,
        [ln for ln in cfg_body.splitlines() if "项目列表" in ln][:3])
    chk("对照：配置页仍渲染租户级配置卡（组织 / 初始化之一）",
        ("组织" in cfg_body) and ("初始化" in cfg_body), cfg_body[:200])

    # ------------------------------------------- 段 3：总览路由仍在（深链 + 两个哨兵依赖）
    page.goto(SHELL + "/gitee/projects", wait_until="networkidle")
    page.wait_for_timeout(3500)
    page.screenshot(path=str(PROOF / "repo-merge-3-repo-overview.png"), full_page=True)
    ov_body = page.inner_text("body")
    chk("对照：旧路径 /gitee/projects 仍渲染仓库列表（不进菜单但有入口）",
        "项目列表" in ov_body, ov_body[:200])
    chk("对照：总览页未被重定向走", "/gitee/projects" in page.url, page.url)

    # ------------------------------------------- 段 4：仓库只跟着开发项目出现
    if not (dev and biz):
        chk("★ 取到开发项目与业务项目各一（否则第 4 条无从验证）", False,
            "dev=%s biz=%s" % (dev, biz))
    else:
        # 4a 开发项目：有「代码仓库」页签，切过去能看到状态/失败原因列与入口
        page.goto("%s/pm/projects/%s" % (SHELL, dev["id"]), wait_until="networkidle")
        page.wait_for_timeout(3000)
        tabs = page.locator(".el-tabs__item").all_inner_texts()
        chk("★ 开发项目详情有「代码仓库」页签", any("代码仓库" in t for t in tabs), tabs)
        if any("代码仓库" in t for t in tabs):
            page.get_by_role("tab", name="代码仓库").click()
            page.wait_for_timeout(3000)
            pane = page.locator(".el-tab-pane").filter(has_text="仓库").first.inner_text()
            page.screenshot(path=str(PROOF / "repo-merge-4-dev-repo-tab.png"), full_page=True)
            chk("★ 页签内有「仓库总览与配置」入口（撤掉菜单后的替代入口）",
                "仓库总览与配置" in pane, pane[:260])
            hdr = page.locator(".el-tab-pane").filter(has_text="仓库").first.inner_text()
            chk("★ 页签表格给出「状态」与「失败原因」列（失败可见、可补救）",
                "状态" in hdr and "失败原因" in hdr, hdr[:260])

        # 4b 业务项目：不应有该页签（BR-01 的界面侧对照）
        page.goto("%s/pm/projects/%s" % (SHELL, biz["id"]), wait_until="networkidle")
        page.wait_for_timeout(3000)
        btabs = page.locator(".el-tabs__item").all_inner_texts()
        page.screenshot(path=str(PROOF / "repo-merge-5-biz-no-repo-tab.png"), full_page=True)
        chk("★★ 业务项目详情**没有**「代码仓库」页签（BR-01 对照）",
            not any("代码仓库" in t for t in btabs), btabs)
        chk("对照：业务项目详情确实渲染出了页签（不是白屏导致的假绿）",
            len(btabs) >= 3, btabs)

    chk("全程无前端 JS 运行时异常", not errs, errs[:2])
    b.close()

bad = [t for t, ok in res if not ok]
print("\n=== 真机 %d/%d 通过 ===" % (len(res) - len(bad), len(res)))
for t in bad:
    print("  FAIL " + t)
raise SystemExit(1 if bad else 0)
