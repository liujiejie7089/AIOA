# -*- coding: utf-8 -*-
"""连接器接入页（按租户）UI 真机验收：真实登录 + 真实接口数据 + 按钮真实可点。

产物：docs/screenshots/connector-access-ui-2026-11-21/（整页截图）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8080/aios/web"
SHOT_DIR = Path(__file__).resolve().parents[1] / "docs/screenshots/connector-access-ui-2026-11-21"
TENANT = "某某市某某区大数据管理局"
USER = "dsj_admin"
PWD = "Admin@123"

results = []


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)[:180]) if detail else ""))


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    page.goto(BASE + "/", wait_until="domcontentloaded")

    # 登录（三个输入框：租户名 / 用户名 / 密码）
    page.wait_for_selector("input", timeout=20000)
    inputs = page.locator("input")
    inputs.nth(0).fill(TENANT)
    inputs.nth(1).fill(USER)
    inputs.nth(2).fill(PWD)
    page.locator("button.login-btn").click()
    page.wait_for_timeout(3000)

    # 进入连接器配置页
    page.goto(BASE + "/connector-configs", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    body = page.inner_text("body")

    check("T1 旧卡片已删除（无「连接器配置（租户级）」）", "连接器配置（租户级）" not in body)
    check("T2 新卡片存在「连接器接入（按租户）」", "连接器接入（按租户）" in body)
    check("T3 连接器显示真实中文名（四川非遗）", "四川非遗" in body)
    check("T4 状态真实展示（已启用）", "已启用" in body)
    hint = [ln.strip() for ln in body.splitlines() if "最近启用" in ln]
    check("T5 操作人不再是裸数字（旧格式「操作人 3240」已消失）",
          bool(hint) and "操作人 3240" not in hint[0], hint[0] if hint else "未找到最近启用行")

    # 机构白名单选择器：真实机构选项
    page.locator(".access-item .el-select").nth(0).click()
    page.wait_for_timeout(900)
    opts = page.locator(".el-select-dropdown:visible .el-select-dropdown__item")
    inst_n = opts.count()
    inst_first = opts.first.inner_text().strip() if inst_n else ""
    check("T6 机构白名单有真实机构选项（来自机构管理）", inst_n > 0, f"count={inst_n} first={inst_first}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # 允许调用用户选择器：真实账号选项
    page.locator(".access-item .el-select").nth(1).click()
    page.wait_for_timeout(900)
    opts2 = page.locator(".el-select-dropdown:visible .el-select-dropdown__item")
    user_n = opts2.count()
    user_first = opts2.first.inner_text().strip() if user_n else ""
    check("T7 允许调用用户有真实账号选项（来自组织成员账号）", user_n > 0, f"count={user_n} first={user_first}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # 保存按钮：真实点击走 PUT 流转（当前白名单本为空，保存空配置 = 无副作用）
    save_btn = page.get_by_role("button", name="保存配置").first
    check("T8 保存按钮可见且可点", save_btn.is_visible() and save_btn.is_enabled())
    save_btn.click()
    page.wait_for_timeout(1800)
    check("T9 保存后返回真实成功提示", "接入配置已保存" in page.inner_text("body"))

    # 启用开关：真实点击（停用 → 断言 → 立即启用恢复现场）
    sw = page.locator(".access-item .el-switch").first
    sw.click()
    page.wait_for_timeout(1800)
    b1 = page.inner_text("body")
    check("T10 停用开关真实生效（提示 + 状态 tag）",
          "已停用，工具立即从本租户清单移除" in b1 and "已停用" in b1)
    sw.click()
    page.wait_for_timeout(1800)
    b2 = page.inner_text("body")
    check("T11 重新启用真实恢复（提示 + 状态 tag）",
          "已启用，本租户用户立即可见" in b2 and "已启用" in b2)

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOT_DIR / "01-access-page.png"), full_page=True)
    browser.close()

fail = [n for n, ok in results if not ok]
print(f"[SUMMARY] {len(results) - len(fail)}/{len(results)} PASS")
print("[STATUS] " + ("PASS" if not fail else "FAIL " + "; ".join(fail)))
sys.exit(0 if not fail else 1)
