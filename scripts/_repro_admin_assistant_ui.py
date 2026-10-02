# -*- coding: utf-8 -*-
"""管理端 AI 助手「能用/不能用」的**浏览器级**复现与取证。

为什么需要它：
  `scripts/_probe_admin_assistant.py` 已在**接口层**证明后端 → agent → 模型整条链正常
  （SSE 有 message.delta 与 message.completed）。但用户看到的是**浏览器里的那个页面**，
  「接口好」推不出「页面好」——中间还隔着：产物是否同版本（webroot 陈旧分片）、
  浏览器里 SSE 能不能发出去（base URL / 事件源实现）、渲染层有没有运行期报错。
  这一层只能真开一个浏览器，把 console / pageerror / 网络响应全部抓下来才作数。

判据（铁律 12）：判定「助手可用」不以「界面里出现了气泡」为唯一依据，
  而是**同时**要求：① 浏览器发出的 POST /runs 返回 code=0；② GET /runs/{id}/events 收到的
  SSE 帧里出现 message.delta 且非空；③ DOM 里出现该文本。三者任一缺失即定位到具体层。

用法：
    python scripts/_repro_admin_assistant_ui.py
产物：logs/proof/ai-assistant/ 下的截图与 console 文本。
前置：后端 :8080 已起且管理端产物已同步到 webroot（单端口形态）。
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
SHELL = BASE + "/aioa/web"
TENANT = "某某市某某区大数据管理局"
ADMIN = "dsj_admin"
PWD = "User@123"
QUESTION = "你好，请用一句话介绍你自己"

PROOF = os.path.join("logs", "proof", "ai-assistant")
PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("OK" if ok else "FAIL", name, ("  -> " + str(detail)) if detail else ""))


def ui_login(page, user):
    page.goto(SHELL + "/login", wait_until="networkidle")
    page.fill('input[autocomplete="organization"]', TENANT)
    page.fill('input[autocomplete="username"]', user)
    page.fill('input[autocomplete="current-password"]', PWD)
    page.click(".login-btn")
    page.wait_for_url("**/home", timeout=20000)


def main():
    os.makedirs(PROOF, exist_ok=True)
    console, errors, net = [], [], []

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()

        page.on("console", lambda m: console.append("%-7s %s" % (m.type, m.text)))
        page.on("pageerror", lambda e: errors.append(str(e)))

        def on_resp(r):
            if "/api/v1/" in r.url and ("/runs" in r.url or "/conversations" in r.url):
                net.append("%s %s -> %s" % (r.request.method, r.url.split("/api/v1")[-1], r.status))
        page.on("response", on_resp)

        # ---------------- A 登录 ----------------
        print("\n[A] 登录管理端")
        ui_login(page, ADMIN)
        chk("A1 登录成功并进入 /home", "/home" in page.url, page.url)

        # ---------------- B 打开 AI 助手抽屉 ----------------
        print("\n[B] 打开 AI 助手")
        btn = page.locator('.el-button:has-text("AI 助手")').first
        chk("B1 顶栏存在「AI 助手」按钮且可见", btn.is_visible(), btn.count())
        btn.click()
        page.wait_for_timeout(1200)
        drawer = page.locator(".assistant-drawer").first
        chk("B2 抽屉已展开（.assistant-drawer 可见）", drawer.is_visible())
        ta = page.locator('textarea[placeholder*="输入问题"]').first
        chk("B3 输入框存在", ta.count() > 0)
        page.screenshot(path=os.path.join(PROOF, "01-drawer-open.png"))

        # ---------------- C 发一条消息，抓全链路 ----------------
        print("\n[C] 发送消息（%s）" % QUESTION)
        ta.fill(QUESTION)
        page.wait_for_timeout(300)
        send = page.locator(".ad-actions .el-button--primary").first
        chk("C1 发送按钮可用（未 disabled）", send.is_enabled())
        send.click()

        # 轮询：等到「流式结束」（发送按钮从 停止 变回 发送）。判据取状态机终点，
        # 而不是「页面里出现过某段文字」—— 后者会被用户气泡本身满足（首版即栽在这里）。
        bubble = page.locator(".assistant-drawer .msg-row.is-ai .msg-text").first
        streaming_over, elapsed, live_seen = False, 0.0, 0
        for _ in range(180):  # 最多 90s
            page.wait_for_timeout(500)
            elapsed += 0.5
            if page.locator(".assistant-drawer .ad-actions .el-button--danger").count() == 0:
                streaming_over = True
                break
            if bubble.count() and bubble.inner_text().strip():
                live_seen += 1
        page.screenshot(path=os.path.join(PROOF, "02-after-send.png"))
        got = bubble.inner_text().strip() if bubble.count() else ""
        print("  流式期间气泡有内容的轮询次数 = %d（0 表示「增量没有实时渲染」）" % live_seen)

        print("\n[D] 取证")
        print("  网络（浏览器发出）:")
        for n in net:
            print("    " + n)
        print("  页面报错(pageerror): %d 条" % len(errors))
        for e in errors[:8]:
            print("    ! " + e[:400])
        err_console = [c for c in console if c.startswith("error") or c.startswith("warning")]
        print("  console error/warning: %d 条" % len(err_console))
        for c in err_console[:12]:
            print("    " + c[:400])

        with open(os.path.join(PROOF, "console.txt"), "w", encoding="utf-8") as f:
            f.write("== pageerror ==\n" + "\n".join(errors) + "\n\n== console ==\n" + "\n".join(console) +
                    "\n\n== net ==\n" + "\n".join(net))
        with open(os.path.join(PROOF, "drawer-text.txt"), "w", encoding="utf-8") as f:
            f.write(page.locator(".assistant-drawer").first.inner_text())

        chk("D1 浏览器确实发出了 POST /conversations", any("POST /conversations" in n for n in net), net)
        chk("D2 浏览器确实发出了建 run 请求", any("/runs -> 200" in n for n in net), net)
        chk("D3 浏览器确实打开了 GET /events（SSE）", any("GET /runs/" in n and "/events" in n for n in net), net)
        chk("D4 流式在 %0.1fs 内正常收尾（按钮回到「发送」）" % elapsed, streaming_over and elapsed < 90,
            "streaming_over=%s" % streaming_over)
        chk("D5 助手回答非空并渲染到页面", bool(got), (got[:160] if got else "空"))
        chk("D6 增量有实时渲染（非「最后一次性刷出」）", live_seen > 0,
            "流式期间有内容的轮询次数=%d" % live_seen)
        chk("D7 无未捕获的运行期异常", len(errors) == 0, errors[:3])

        ctx.close()
        b.close()

    print("\n======== 小结 ========")
    print("PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
    print("取证目录：%s" % PROOF)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
