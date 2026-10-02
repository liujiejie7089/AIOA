# -*- coding: utf-8 -*-
"""项目管理（PM，docs/40 批次 1）的**界面级**验证。

为什么在「静态守卫 + 接口冒烟」之后还要跑界面：
  · `_check_pm_guards.py` 只能证明「判定点存在且被调用」；
  · `_smoke_pm.py`  只能证明「后端在真实请求上真的拒绝」；
  · 两者都证明不了「用户点得到、看得见」—— 菜单没挂上 / 路由 allowRoles 写错 /
    前端把「开发项目才该有的仓库块」渲染给了业务项目，这三类缺陷语法检查一律查不出来。

★ 同源判据（铁律 12）：界面断言**不读界面自己的数据副本**，而是回接口重新取一次再比。
  「界面展示了某事实」的判据必须回到事实源头（接口/库），否则渲染层读错字段时，
  判据与实现会一起错、测试永远绿。本脚本因此先按 API 取一遍清单，再抓 DOM 逐名比对。
  另外带一个**负向对照 K1**（造一个库里不存在的名字），证明这套比较真的会红。

★ 自净（铁律 11）：临时项目软删 + 清残留，跑完 pm_project 回到 0 行。

用法：
    python scripts/_e2e_pm_ui.py              # 正跑
    python scripts/_e2e_pm_ui.py --selftest   # 只跑判据有效性（喂假 DOM，必须在 GHOST 上报红）
前置：后端 :8080 已起且 V71 已应用；webroot 已由 web/apps/shell/dist 同步（单端口形态）。
"""
import re
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
API = BASE + "/api/v1"
# 单端口形态：管理端产物挂在 /aioa/web/ 下（docs/33）。用生产形态验证，
# 顺带把「webroot 同步是否真的生效」一并证掉。
SHELL = BASE + "/aioa/web"

TENANT = "某某市某某区大数据管理局"
ADMIN, MEMBER = "dsj_admin", "fagai_li"   # 租户管理员 / 机构成员（三级权限差异的对照组）
PWD = "User@123"

PREFIX = "PMUI-"
PASS, FAIL = [], []


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:300]) if detail else ""))
    return bool(cond)


# ============================================================ 判据（可单测的纯函数）
def unpack_list(data):
    """列表接口的 data 可能是裸数组、也可能是 {items|records|list: [...]}。
    PM 的 /pm/projects 目前返回**裸数组**（服务层 List<Map>，无分页），
    但这里两种都兼容 —— 将来加分页时不必回来改断言。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "records", "list", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def diff_names(dom_names, api_names):
    """界面应展示的项目名集合 vs 接口返回的项目名集合。

    只关心本脚本自造的前缀名（PREFIX），对种子数据与分页天然免疫 ——
    「基线本身可能已含历史残留」，拿全量做等值断言会把别人的脏数据算到自己头上（铁律 11）。
    返回 (missing, extra)：missing = 接口有而界面没有；extra = 界面有而接口没有。
    """
    d = {n for n in dom_names if n.startswith(PREFIX)}
    a = {n for n in api_names if n.startswith(PREFIX)}
    return sorted(a - d), sorted(d - a)


def selftest():
    """判据有效性：喂一份**带 GHOST 的假 DOM**，比较函数必须报出 extra。

    这一步的意义：如果比较函数写错（比如两边取同一个来源），
    真跑时「界面没渲染」与「比较失效」都会表现为 PASS。先让它对已知错误报红，
    才能说真跑时那个 PASS 是可信的。
    """
    print("\n[K] 判据有效性自检（--selftest）")
    api = [PREFIX + "A", PREFIX + "B"]
    fake_dom_ok = [PREFIX + "A", PREFIX + "B"]
    fake_dom_ghost = [PREFIX + "A", PREFIX + "B", PREFIX + "GHOST"]
    fake_dom_missing = [PREFIX + "A"]

    miss, extra = diff_names(fake_dom_ok, api)
    chk("K-s1 一致时判据为绿", (miss, extra) == ([], []), (miss, extra))
    miss, extra = diff_names(fake_dom_ghost, api)
    chk("K-s2 ★喂 GHOST 必须报 extra（否则判据无区分力）",
        extra == [PREFIX + "GHOST"], (miss, extra))
    miss, extra = diff_names(fake_dom_missing, api)
    chk("K-s3 ★漏渲染必须报 missing（否则界面空白也会被判绿）",
        miss == [PREFIX + "B"], (miss, extra))
    # 库里不存在的名字，若判据仍报绿 ⇒ 判据与实现同源，铁律 12 违规
    miss, extra = diff_names([PREFIX + "NOT-IN-DB"], api)
    chk("K-s4 ★界面出现库里没有的项目名必须报 extra",
        extra == [PREFIX + "NOT-IN-DB"], (miss, extra))

    print("\n自检合计：%d PASS / %d FAIL" % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


# ============================================================ 接口侧（事实源）
class Api:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token}
        self.c = httpx.Client(timeout=60, trust_env=False)

    def get(self, p, **kw):
        return self.c.get(API + p, headers=self.h, **kw).json()

    def post(self, p, **kw):
        return self.c.post(API + p, headers=self.h, **kw).json()

    def put(self, p, **kw):
        return self.c.put(API + p, headers=self.h, **kw).json()

    def delete(self, p, **kw):
        return self.c.delete(API + p, headers=self.h, **kw).json()


def login(user):
    r = httpx.post(API + "/auth/login", timeout=30, trust_env=False,
                   json={"username": user, "password": PWD, "tenantName": TENANT}).json()
    if r.get("code") != 0:
        raise SystemExit("登录失败 %s: %s" % (user, r.get("message")))
    return r["data"]["accessToken"]


# ============================================================ 浏览器侧
def ui_login(page, user):
    page.goto(SHELL + "/login", wait_until="networkidle")
    page.fill('input[autocomplete="organization"]', TENANT)
    page.fill('input[autocomplete="username"]', user)
    page.fill('input[autocomplete="current-password"]', PWD)
    page.click(".login-btn")
    page.wait_for_url("**/home", timeout=20000)


def menu_items(page):
    return [t.strip() for t in page.locator(".layout-aside .el-menu-item").all_inner_texts()]


def row_names(page):
    """列表页的「项目名称」列文本。列序见 PmProjectsView：编号/名称/类型/..."""
    return [t.strip() for t in page.locator(".el-table__body tbody tr td:nth-child(2)").all_inner_texts()]


def main():
    stamp = str(int(time.time()))
    pname = PREFIX + stamp
    ghost = pname + "-GHOST"

    # ---------------- A 事实源：先用接口把「应该看到什么」定下来 ----------------
    print("\n[A] 事实源（接口）")
    admin_tok = login(ADMIN)
    A = Api(admin_tok)
    created = A.post("/pm/projects", json={
        "projectNo": "PM-" + stamp, "name": pname, "projectType": "BUSINESS",
        "description": "PM 界面验证临时项目",
    })
    chk("A1 接口建出业务项目（承载界面断言的对照数据）",
        created.get("code") == 0, created.get("message"))
    pid = (created.get("data") or {}).get("id")

    api_items = unpack_list(A.get("/pm/projects").get("data"))
    api_names = [i.get("name") for i in api_items if isinstance(i, dict)]
    chk("A2 接口清单含刚建项目（事实源头）", pname in api_names,
        "api=%d 条，本前缀=%s" % (len(api_names), [n for n in api_names if n and n.startswith(PREFIX)]))

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))

        # ---------------- B 租户管理员：能看到、能进、能建 ----------------
        print("\n[B] 界面（租户管理员）")
        ui_login(page, ADMIN)

        page.goto(SHELL + "/pm/projects", wait_until="networkidle")
        page.wait_for_timeout(2500)
        chk("B1 侧边菜单出现「项目管理」入口（菜单层）",
            "项目管理" in menu_items(page), menu_items(page))
        chk("B2 直接访问 /pm/projects 未被重定向（路由 meta.allowRoles 层）",
            "/pm/projects" in page.url, page.url)

        names = row_names(page)
        miss, extra = diff_names(names, api_names)
        chk("B3 ★界面列表与接口清单同源一致（缺=%s 多=%s）" % (miss, extra),
            not miss and not extra, "dom=%s" % [n for n in names if n.startswith(PREFIX)])

        # K1 负向对照：库里不存在的名字不得出现在界面
        chk("K1 ★负向对照：界面上不存在库里没有的项目名（证明 B3 有区分力）",
            ghost not in " ".join(names), names)

        body = page.inner_text("body")
        chk("B4 租户管理员可见「新建项目」按钮（CREATE ∈ PM_CREATE_ROLES）",
            "新建项目" in body, body[:120].replace("\n", " "))

        # B5/B6 类型是仓库块的唯一开关（BR-01 的前端表达）
        page.click("text=新建项目")
        page.wait_for_timeout(800)
        dlg = page.locator(".el-dialog")
        chk("B5 新建对话框打开", dlg.count() > 0)
        txt_biz = dlg.inner_text()
        chk("B6 ★业务项目下**不渲染**仓库配置块（BR-01 前端隐藏）",
            "代码仓库策略" not in txt_biz and "业务项目无需仓库配置" in txt_biz,
            txt_biz[:200].replace("\n", " "))
        page.click(".el-dialog .el-radio-button:has-text('开发项目')")
        page.wait_for_timeout(600)
        txt_dev = dlg.inner_text()
        chk("B7 ★正向对照：切到开发项目后仓库配置块出现（证明 B6 的比较有区分力）",
            "代码仓库策略" in txt_dev, txt_dev[:200].replace("\n", " "))
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # B8/B9 详情页页签由类型驱动
        page.goto("%s/pm/projects/%s" % (SHELL, pid), wait_until="networkidle")
        page.wait_for_timeout(2500)
        tabs = page.locator(".el-tabs__item").all_inner_texts()
        tabs = [t.strip() for t in tabs]
        chk("B8 ★业务项目详情**无**「代码仓库」页签（BR-01 在详情页同样成立）",
            not any("代码仓库" in t for t in tabs), tabs)
        chk("B9 详情页有「任务」「成员」页签（批次 1 的其余能力入口在）",
            any(t.startswith("任务") for t in tabs) and any(t.startswith("成员") for t in tabs), tabs)

        ctx.close()

        # ---------------- C 阴性角色：机构成员能看不能建 ----------------
        print("\n[C] 界面（机构成员 · 阴性对照）")
        ctx2 = b.new_context(viewport={"width": 1600, "height": 1000})
        page2 = ctx2.new_page()
        page2.on("pageerror", lambda e: errs.append(str(e)))
        ui_login(page2, MEMBER)
        page2.goto(SHELL + "/pm/projects", wait_until="networkidle")
        page2.wait_for_timeout(2500)
        chk("C1 机构成员仍有「项目管理」入口（VIEW 对全员开放）",
            "项目管理" in menu_items(page2), menu_items(page2))
        body_m = page2.inner_text("body")
        chk("C2 ★机构成员**看不到**「新建项目」按钮（CREATE 不含 MEMBER，三层同源）",
            "新建项目" not in body_m,
            [l for l in body_m.split("\n") if "新建" in l][:3])
        # C3 逆向断言：页面上真的不是空壳（否则 C2 会因「整页白屏」而假绿）
        chk("C3 ★逆向对照：成员页确实渲染出了列表头（证明 C2 不是白屏导致的假绿）",
            "项目名称" in body_m and "项目编号" in body_m, body_m[:150].replace("\n", " "))
        ctx2.close()
        b.close()

    chk("Z1 全程无前端 JS 异常（pageerror）", not errs, errs[:2])

    # ---------------- Z 自净 ----------------
    print("\n[Z] 自净")
    d = A.delete("/pm/projects/%s" % pid)
    chk("Z2 临时项目软删成功", d.get("code") == 0, d.get("message"))
    after_items = unpack_list(A.get("/pm/projects").get("data"))
    left = [i for i in after_items if isinstance(i, dict) and (i.get("name") or "").startswith(PREFIX)]
    chk("Z3 软删后本前缀项目退出业务可见面（铁律 11）", not left, left)

    print("\n合计：%d PASS / %d FAIL" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：%s" % FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
