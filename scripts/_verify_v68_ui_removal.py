# -*- coding: utf-8 -*-
"""真机（Edge headless）核验两件事（V68 去掉子租户后的 UI 侧证据）：

  1) 管理端**不再有**「子租户」入口（侧栏无该项、旧路由 /sub-tenants 不再渲染子租户页），
     且同一分组「租户与机构」下其它入口**仍在**（对照，避免「整块菜单被删」被当成通过）；
  2) 「租户管理 → 调整资源」弹窗**预填当前席位**（DSJ-DEMO 实测 12/18），不是硬写 0。

⚠️ 两条踩过的坑（改这个脚本前先读）：
  a) **必须点有资源池的那一行**。sys_tenant id=1「默认租户」在 tenant_resource_pool 里
     **没有行**，list 接口回吐 0/0/0 —— 那是**正确**的。上一版脚本 `btns.first.click()`
     点的就是第一行，于是把「0」误判成「预填失效」。要按租户编码定位目标行。
  b) **侧栏子菜单默认折叠**，Element Plus 把子项包在折叠过渡里，`inner_text()`（等价 innerText）
     **不返回不可见文本** ⇒ 对照检查会假红。必须先展开「租户与机构」再读，或读 textContent。

用法：python scripts/_verify_v68_ui_removal.py
输出证据截图到 logs/proof/。
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

SHELL = "http://127.0.0.1:8080/aioa/web"
# 目标租户：DSJ-DEMO（sys_tenant.id=2），演示库里唯一有「非零席位」且状态可用的租户之一
TARGET_CODE = "DSJ-DEMO"
EXP_TOKEN = "20000000"
EXP_EXPERT = "12"
EXP_SKILL = "18"
PROOF = Path(__file__).resolve().parent.parent / "logs" / "proof"
PROOF.mkdir(parents=True, exist_ok=True)

res = []


def chk(tag, cond, detail=""):
    res.append((tag, bool(cond)))
    print(("[OK]   " if cond else "[FAIL] ") + tag + (("  " + str(detail)) if detail and not cond else ""))


with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge", headless=True)
    page = b.new_context(viewport={"width": 1600, "height": 950}).new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))

    page.goto(SHELL + "/login", wait_until="networkidle")
    page.fill('input[autocomplete="organization"]', "默认租户")
    page.fill('input[autocomplete="username"]', "admin")
    page.fill('input[autocomplete="current-password"]', "Admin@123")
    page.click("button:has-text('登')")
    page.wait_for_timeout(4000)
    chk("真机登录进入工作台", "/login" not in page.url, page.url)

    # ---- 展开「租户与机构」分组（默认折叠，不展开读不到子项文案）
    grp = page.locator('.el-sub-menu__title:has-text("租户与机构")')
    chk("对照：侧栏「租户与机构」分组仍在", grp.count() > 0, grp.count())
    if grp.count() > 0:
        grp.first.click()
        page.wait_for_timeout(700)

    sidebar = page.locator(".el-menu").first
    body = page.inner_text("body")
    sb_text = sidebar.text_content() or "" if sidebar.count() > 0 else body

    chk("★ 侧栏/页面已无「子租户」字样", "子租户" not in body and "子租户" not in sb_text,
        [ln for ln in body.splitlines() if "子租户" in ln][:3])
    # 对照：同组其它入口必须仍在（证明不是整块菜单被删/页面没渲染出来）
    for label in ("租户管理", "机构管理", "入驻进度", "资源授权", "费用分摊"):
        chk("对照：菜单「%s」仍在" % label, label in sb_text,
            [ln for ln in sb_text.splitlines()][:12])
    page.screenshot(path=str(PROOF / "v68-1-menu-no-subtenant.png"), full_page=True)

    # ---- 旧路由 /sub-tenants 不再渲染子租户页（路由级证据，不只靠文案）
    page.goto(SHELL + "/sub-tenants", wait_until="networkidle")
    page.wait_for_timeout(1500)
    old_body = page.inner_text("body")
    chk("★ 旧路由 /sub-tenants 不再渲染子租户页", "子租户" not in old_body,
        [ln for ln in old_body.splitlines() if "子租户" in ln][:3])
    chk("对照：/sub-tenants 落到了工作台（不是白屏/报错）",
        "/sub-tenants" not in page.url or "工作台" in old_body or "首页" in old_body, page.url)

    # ---- 租户管理 → 调整资源弹窗（点有资源池的那一行）
    page.goto(SHELL + "/tenants", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(PROOF / "v68-2-tenant-list.png"), full_page=True)
    tbody = page.inner_text("body")
    chk("租户列表渲染出演示租户", TARGET_CODE in tbody or "大数据管理局" in tbody)
    chk("列表显示登录域名列（⑥ 能力仍在）", "dsj.aioa.local" in tbody,
        [ln for ln in tbody.splitlines() if "aioa.local" in ln][:3])

    row = page.locator("tr", has_text=TARGET_CODE).first
    chk("定位到 %s 行" % TARGET_CODE, row.count() > 0, row.count())
    btn = row.locator("button:has-text('调整资源')")
    chk("该行「调整资源」按钮存在", btn.count() > 0, btn.count())
    if btn.count() > 0:
        btn.first.click()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(PROOF / "v68-3-quota-dialog.png"), full_page=True)

        def dlg_val(label):
            item = page.locator(
                '.el-dialog .el-form-item:has(.el-form-item__label:text-is("%s"))' % label)
            if item.count() == 0:
                return None
            return item.first.locator("input").first.input_value()

        vals = {lb: dlg_val(lb) for lb in ("统计期", "词元上限", "专家席位", "技能席位")}
        print("      弹窗实测值=%s" % vals)
        chk("★★ 弹窗预填专家席位=%s（不再是硬写 0）" % EXP_EXPERT,
            vals.get("专家席位") == EXP_EXPERT, vals)
        chk("★★ 弹窗预填技能席位=%s（不再是硬写 0）" % EXP_SKILL,
            vals.get("技能席位") == EXP_SKILL, vals)
        chk("弹窗预填词元上限=%s（非 0）" % EXP_TOKEN,
            vals.get("词元上限") == EXP_TOKEN, vals)

    chk("真机无 JS 运行时异常", not errs, errs[:2])
    b.close()

bad = [t for t, ok in res if not ok]
print("\n=== 真机 %d/%d 通过 ===" % (len(res) - len(bad), len(res)))
raise SystemExit(1 if bad else 0)
