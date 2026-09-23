# -*- coding: utf-8 -*-
"""H5 版式截图（人工核对用，不是断言）。

跑法：python scripts/_shot_h5_layout.py
产出：.workbuddy/shots/h5-<场景>.png

为什么单独留一个截图脚本：布局类改动（满屏、安全区、阅读列宽）的「对不对」很多是目视判断，
套件只能守住可度量的那部分（尺寸、颜色一致、无描边）。两者一起用，缺一样都会漏。
"""
import json
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".workbuddy", "shots")
BASE = "http://127.0.0.1:5181"
API = "http://127.0.0.1:8080/api/v1"

import httpx  # noqa: E402


def login(u, p):
    d = httpx.Client(timeout=30, trust_env=False).post(
        f"{API}/auth/login", json={"username": u, "password": p}).json()
    return d["data"]["accessToken"], d["data"]


SCENES = [
    ("phone-portrait", 390, 844, 2, "iPhone 竖屏"),
    ("phone-landscape", 844, 390, 2, "横屏"),
    ("desktop-column", 1280, 800, 1, "桌面宽屏（应收窄为居中列、两侧无黑边）"),
    ("chat-answer", 390, 844, 2, "会话页：AI 回答的层级化版式"),
]

ANSWER = (
    "一、结论\n**可以续签**，但要提前 30 天通知。\n\n"
    "1. 发出续签意向书\n2. 双方协商条款\n3. 签订书面合同\n\n"
    "- 逾期未签视为自动续延\n- 连续两次固定期限后可要求无固定期限\n\n"
    "> 依据：《劳动合同法》第十四条\n\n"
    "注意：需在 30 个工作日内办结，逾期罚款 5000 元。"
)


def main():
    os.makedirs(OUT, exist_ok=True)
    tok, me = login("wjj_xu", "User@123")
    session = json.dumps({"token": tok, "user": me.get("user", me)}, ensure_ascii=False)

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        for name, w, h, scale, label in SCENES:
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale)
            ctx.add_init_script(f"localStorage.setItem('aioa_session', {json.dumps(session)})")
            pg = ctx.new_page()
            pg.goto(BASE + "/index.html", wait_until="networkidle")
            pg.wait_for_timeout(2500)
            if name == "chat-answer":
                pg.evaluate("() => { go('page-chat'); activateChatTab(); setTitle('page-chat'); }")
                pg.wait_for_timeout(400)
            # 造一条带层级的回答，专门核对 §回答美化：标题 / 有序 / 无序 / 引用 / 数字高亮
            pg.evaluate("""(ans) => {
              const m = document.getElementById('msgs');
              m.innerHTML = '<div class="msg me"><div class="avatar"></div>' +
                '<div class="bubble">劳动合同到期了，公司不想续签，我该注意什么？</div></div>' +
                '<div class="msg"><div class="avatar"></div><div class="bubble ans">' +
                formatAnswer(ans) + '</div></div>';
              m.scrollTop = 0;
            }""", ANSWER)
            pg.wait_for_timeout(300)
            path = os.path.join(OUT, f"h5-{name}.png")
            pg.screenshot(path=path)
            print(f"[shot] {label} {w}x{h} -> {path}")
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
