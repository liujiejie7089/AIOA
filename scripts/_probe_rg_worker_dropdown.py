"""真机探针：管理端「资源授权 → 新增机构授权」里，资源类型选「数字员工」后资源下拉是否为空。

为什么必须有：`/tenant/grants/catalog` 实测返回 4 个数字员工、在线分包里
`CAT_KEY` 映射也正确（WORKER→workers），静态层面全都「应该没问题」——
只有真浏览器才知道用户看到的到底是什么。本探针把三件事同时抓下来：
① 该次 `catalog` 请求的状态码与 `workers` 条数（判「后端有没有给」）；
② 下拉里实际渲染出的选项文本 / 空态（判「前端有没有渲染」）；
③ console 报错与失败请求（判「有没有静默异常」）。

用法：python scripts/_probe_rg_worker_dropdown.py
"""
import json
import os
import sys

import httpx
from playwright.sync_api import sync_playwright

# 入口可用环境变量覆盖，便于同时核对「单端口产物」与「:5173 dev」两条入口：
#   AIOA_PROBE_ENTRY=http://127.0.0.1:5173/    （dev，base='/'）
#   AIOA_PROBE_ENTRY=http://127.0.0.1:8080/aioa/web/   （默认，单端口产物）
BASE = "http://127.0.0.1:8080"
ENTRY = os.environ.get("AIOA_PROBE_ENTRY", BASE + "/aioa/web/").rstrip("/")
WEB = ENTRY
USER, PWD = "dsj_admin", "User@123"
print("入口 =", WEB)


def get_session():
    c = httpx.Client(base_url=BASE, trust_env=False, timeout=20)
    d = c.post("/api/v1/auth/login", json={"username": USER, "password": PWD}).json()["data"]
    return d


def main():
    d = get_session()
    token, refresh, user = d["accessToken"], d["refreshToken"], d["user"]
    print("登录 ok: %s tenantId=%s roles=%s" % (user["username"], user.get("tenantId"), user.get("roles")))

    catalog_seen = {}

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            "localStorage.setItem('aioa.token', %s);"
            "localStorage.setItem('aioa.refreshToken', %s);"
            "localStorage.setItem('aioa.user', %s);"
            % (json.dumps(token), json.dumps(refresh), json.dumps(json.dumps(user, ensure_ascii=False)))
        )
        page = ctx.new_page()
        errors, failures = [], []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        page.on("requestfailed", lambda r: failures.append(r.url + " :: " + str(r.failure)))

        def on_resp(r):
            if "/grants/catalog" in r.url:
                try:
                    js = r.json()
                except Exception:
                    catalog_seen["raw"] = "非 JSON"
                    return
                data = js.get("data") or {}
                catalog_seen["http"] = r.status
                catalog_seen["code"] = js.get("code")
                catalog_seen["workers"] = len(data.get("workers") or [])
                catalog_seen["resTypes"] = len(data.get("resTypes") or [])
                catalog_seen["workerNames"] = [w.get("name") for w in (data.get("workers") or [])]

        page.on("response", on_resp)

        page.goto(WEB + "/resource-grants", wait_until="networkidle")
        page.wait_for_timeout(1200)
        print("页面标题片段:", (page.title() or "")[:60])
        print("catalog 响应:", json.dumps(catalog_seen, ensure_ascii=False))

        # 「可授权资源目录」卡片里数字员工那一页签的数量，是独立于弹窗的旁证
        tabs = page.locator(".el-tabs__item").all_inner_texts()
        print("资源目录页签:", tabs)

        page.click("button:has-text('新增授权')")
        page.wait_for_timeout(600)
        dlg = page.locator(".el-dialog:visible")
        items = dlg.locator(".el-form-item")
        print("弹窗表单项数:", items.count())

        # 资源类型 = 数字员工
        items.nth(1).locator(".el-select").click()
        page.wait_for_timeout(400)
        page.locator(".el-select-dropdown:visible .el-select-dropdown__item", has_text="数字员工").first.click()
        page.wait_for_timeout(500)
        print("已选资源类型:", items.nth(1).locator("input").input_value())

        # 资源下拉：展开后看选项 / 空态
        items.nth(2).locator(".el-select").click()
        page.wait_for_timeout(800)
        opts = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").all_inner_texts()
        empty = page.locator(".el-select-dropdown:visible .el-select-dropdown__empty").all_inner_texts()
        print("资源下拉选项(%d):" % len(opts), opts)
        print("资源下拉空态:", empty)

        if errors:
            print("console 报错(%d):" % len(errors))
            for e in errors[:8]:
                print("   ", e[:200])
        else:
            print("console 报错: 无")
        if failures:
            print("失败请求(%d):" % len(failures))
            for f in failures[:8]:
                print("   ", f[:200])
        else:
            print("失败请求: 无")

        b.close()

    ok = bool(catalog_seen.get("workers")) and bool(opts)
    print("\n结论: 后端给了 %s 个数字员工；前端下拉渲染了 %d 个选项 ⇒ %s"
          % (catalog_seen.get("workers"), len(opts), "一致" if ok else "不一致（问题在前端）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
