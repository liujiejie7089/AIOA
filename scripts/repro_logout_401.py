"""复现：管理端在「业务工具」页点击退出登录时的 401 报错。

观察点：
  1) 点击退出登录后弹出的 ElMessage 文案（期望：只有「已退出登录」，不应有「加载工具失败…401」）
  2) 网络请求序列（尤其是 token 清除后是否还有 /api/v1/... 请求发出）
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
USER = "admin"
PWD = "Admin@123"


def main() -> int:
    reqs: list[tuple[str, str]] = []
    msgs: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        def on_req(r):
            if "/api/" in r.url:
                reqs.append((r.method, r.url.replace(BASE, "")))

        def on_resp(r):
            if "/api/" in r.url and r.status >= 400:
                msgs.append(f"[HTTP {r.status}] {r.request.method} {r.url.replace(BASE, '')}")

        page.on("request", on_req)
        page.on("response", on_resp)

        # 登录
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill("input[placeholder='admin']", USER)
        page.fill("input[type=password]", PWD)
        page.click(".login-btn")
        page.wait_for_url("**/home", timeout=15000)

        # 进入「业务工具」
        page.goto(f"{BASE}/tools", wait_until="networkidle")
        page.wait_for_timeout(1200)
        print("=== 进入 /tools 后：")
        print("  表格行数:", page.locator(".el-table__row").count())
        reqs.clear()

        # 记录 toast 文案
        def grab_toasts():
            out = []
            for sel in [".el-message", ".el-message__content"]:
                for el in page.query_selector_all(sel):
                    t = (el.inner_text() or "").strip()
                    if t:
                        out.append(t)
            return out

        # 点击右上角用户下拉 → 退出登录
        page.click(".user")
        page.wait_for_timeout(400)
        page.click("text=退出登录")

        # 轮询 3.5s 抓取所有出现过的 toast
        seen: list[str] = []
        for _ in range(35):
            for t in grab_toasts():
                if t not in seen:
                    seen.append(t)
            page.wait_for_timeout(100)

        print("\n=== 点击退出登录后：")
        print("  当前 URL:", page.url)
        print("  出现的提示:", json.dumps(seen, ensure_ascii=False, indent=2))
        print("  token 是否已清:", page.evaluate("!localStorage.getItem('aioa.token')"))
        print("  退出后的请求序列:")
        for m, u in reqs:
            print(f"    {m} {u}")
        print("  4xx/5xx 响应:", json.dumps(msgs, ensure_ascii=False, indent=2))

        ok = not any("加载工具失败" in s for s in seen) and not any("401" in s for s in seen)
        print("\n复现结果:", "PASS(无 401 报错)" if ok else "FAIL(复现到 401 报错)")
        b.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
