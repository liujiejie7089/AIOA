# -*- coding: utf-8 -*-
"""V48 · Gitee 仓库联动 前端真实浏览器验证（独立验证，不修改任何被跟踪源码）。

驱动 Edge 无头浏览器，对三档角色（租户管理员 / 企业管理员 / 部门负责人）逐一验证：
菜单与路由、页面渲染、控制台/5xx、角色门控陷阱、详情五 Tab、深链、跨租户/不存在、
交互边界、错误文案贯通，以及伸长的 OAuth 绑定与网页上传提交。
"""
import json
import os
import sys
import time
import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
ART = os.path.join(".workbuddy", "artifacts", "v48-ui")
os.makedirs(ART, exist_ok=True)

C = httpx.Client(timeout=60, trust_env=False)

results = []
console_errors = []
server_5xx = []
resource_404 = []          # 非 /api 的 404 资源（用于定位那个控制台 404）
tasks_stats_calls = []

ROLES = [
    ("znkj_admin", "ROLE_TENANT_ADMIN"),
    ("znkjyf_admin", "ROLE_ORG_ADMIN"),
    ("znsfb_ldr", "ROLE_DEPT_LEADER+ROLE_MEMBER"),
]


def check(cid, ok, detail=""):
    results.append((cid, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {cid}: {detail}")


def login(name):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": "User@123"}).json()
    assert d.get("code") == 0, f"login {name} failed: {d.get('message')}"
    return d["data"]["accessToken"], d["data"]["user"], d["data"].get("refreshToken", "")


def ensure_upload_project(tok):
    """为「网页上传」检查准备一个**自洽**的 ACTIVE 项目，返回其 id（失败返回 None）。

    历史实现硬编码 /gitee/projects/10：该项目的仓库只活在桩的**内存态**里，桩一重启就没了 ——
    上传于是必然 404（Not Found），而外部症状是「上传弹窗不关闭、随后点『刷新目录』被弹窗
    遮罩拦截」，看起来像前端 bug，实为套件依赖了历史数据。改为现建一个，本检查只依赖本次运行。
    """
    h = {"Authorization": f"Bearer {tok}"}
    d = C.post(f"{API}/gitee/projects", headers=h,
               json={"name": "UI 上传验证 " + str(int(time.time())), "departmentId": 101,
                     "description": "UI 上传自洽验证", "visibility": "private"}).json()
    pid = (d.get("data") or {}).get("id")
    if not pid:
        return None
    for _ in range(45):
        time.sleep(2)
        data = (C.get(f"{API}/gitee/projects/{pid}", headers=h).json().get("data") or {})
        st = ((data.get("project") or {}).get("status")) or data.get("status")
        if st == "ACTIVE":
            return pid
        if st == "FAILED":
            return None
    return None


def seed(ctx, tok, user, refresh=""):
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s);"
        "localStorage.setItem('aioa.refreshToken', %s);"
        "localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(refresh), json.dumps(json.dumps(user, ensure_ascii=False)))
    )


def attach(page):
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    def on_resp(r):
        if r.status >= 500:
            server_5xx.append(f"{r.status} {r.request.method} {r.url}")
        elif r.status == 404 and "/api" not in r.url:
            resource_404.append(r.url)
    page.on("response", on_resp)
    page.on("request", lambda r: tasks_stats_calls.append(r.url)
            if "/gitee/tasks/stats" in r.url else None)


def new_ctx(pw, br, tok, user, refresh=""):
    ctx = br.new_context(viewport={"width": 1440, "height": 980})
    seed(ctx, tok, user, refresh)
    page = ctx.new_page()
    attach(page)
    return ctx, page


def wait_view(page, anchor, timeout=30000):
    """等视图的某个锚点文本出现再断言；超时则抛错由调用方捕获。"""
    page.get_by_text(anchor, exact=False).first.wait_for(state="visible", timeout=timeout)


def wait_for_anchor(page, text, timeout=30000):
    page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)


def open_projects(page, anchor="我的 Gitee 账号", wait=2000):
    page.goto(SHELL + "/gitee/projects", wait_until="networkidle")
    try:
        wait_for_anchor(page, anchor, timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(wait)


def capture_toasts(page, wait=900):
    page.wait_for_timeout(wait)
    try:
        return [e.inner_text() for e in page.locator(".el-message").all()]
    except Exception:
        return []


def poll_success_toast(page, timeout=8000, needle="上传成功"):
    """在时间窗内**轮询**捕获成功 toast。

    不能用「固定 sleep 后一次性读取」：ElMessage 默认 3000ms 自动关闭，而提交之后还要等
    目录/列表刷新，等完再去读，toast 早已消失 —— 旧写法 sleep 2500 + 1000 后读取，
    必然读到空数组，于是「上传成功」永远判 False，看着像功能坏了，其实是采样太晚。
    """
    deadline = time.time() + timeout / 1000.0
    seen = []
    while time.time() < deadline:
        try:
            seen = [e.inner_text() for e in page.locator(".el-message").all()]
        except Exception:
            seen = []
        if any(needle in t for t in seen):
            return seen
        page.wait_for_timeout(200)
    return seen


# ======================================================================
def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)
        creds = {n: login(n) for n, _ in ROLES}

        # ---------------- 检查 1 + 2 + 4 ----------------
        for name, role in ROLES:
            tok, user, refresh = creds[name]
            ctx, page = new_ctx(pw, br, tok, user, refresh)
            before = len(tasks_stats_calls)
            open_projects(page)

            menu = page.get_by_text("项目与仓库", exact=True)
            menu_visible = menu.count() > 0 and menu.first.is_visible()
            redirected = "/gitee/projects" not in page.url
            check(f"1.菜单+路由[{name}]", menu_visible and not redirected,
                  f"menu={menu_visible} url={page.url}")

            # 视图是否真的渲染出来（锚点：我的 Gitee 账号）
            view_ok = page.get_by_text("我的 Gitee 账号", exact=False).count() > 0
            intro = page.get_by_text("项目与仓库（Gitee 联动）").count() > 0
            bind_card = view_ok
            list_card = page.get_by_text("项目列表", exact=False).count() > 0
            rows = page.locator(".el-table__row").count()
            check(f"2.页面渲染[{name}]", intro and bind_card and list_card and rows > 0,
                  f"intro={intro} bind={bind_card} list={list_card} rows={rows}")
            page.screenshot(path=os.path.join(ART, f"{name}-projects.png"), full_page=True)

            ops = page.get_by_text("运维与校准").count() > 0
            if role == "ROLE_TENANT_ADMIN":
                check(f"4.运维卡片门控[{name}]", ops,
                      f"租户管理员: ops卡片出现={ops} (期望出现)")
            else:
                stats_called = len(tasks_stats_calls) > before
                toasts = capture_toasts(page)
                err_toast = [t for t in toasts if ("仅租户管理员" in t or "任务统计" in t)]
                check(f"4.运维卡片门控[{name}]",
                      (not ops) and (not stats_called) and (not err_toast),
                      f"{role}: ops卡片={ops}(期望不存在) tasks_stats_called={stats_called} 相关toast={err_toast}")
            ctx.close()

        # ---------------- 检查 5/6/7/8/9（租户管理员） ----------------
        tok, user, refresh = creds["znkj_admin"]

        # 检查 6：深链冷加载
        ctx6, page6 = new_ctx(pw, br, tok, user, refresh)
        page6.goto(SHELL + "/gitee/projects/5", wait_until="networkidle")
        try:
            wait_for_anchor(page6, "概览", timeout=30000)
        except Exception:
            pass
        page6.wait_for_timeout(2500)
        cold_name = page6.locator(".proj-name").inner_text() if page6.locator(".proj-name").count() else ""
        c6 = bool(cold_name.strip()) and "/gitee/projects/5" in page6.url and "home" not in page6.url
        check("6.深链冷加载", c6, f"proj_name={cold_name!r} url={page6.url}")
        page6.screenshot(path=os.path.join(ART, "detail-cold.png"), full_page=True)

        page = page6
        tab_names = ["概览", "成员", "文件", "提交记录", "事件流"]
        all_rendered = True
        for t in tab_names:
            try:
                page.locator(".el-tabs__item", has_text=t).first.click()
            except Exception as e:
                all_rendered = False
                check(f"5.tab[{t}]", False, f"无法点击: {e}")
                continue
            page.wait_for_timeout(1800)
            active = page.locator(".el-tab-pane").filter(visible=True)
            has_content = (
                active.locator(".el-table__row").count() > 0
                or active.locator(".el-descriptions").count() > 0
                or active.locator(".el-empty").count() > 0
                or active.get_by_text("仓库尚未就绪").count() > 0
                or active.get_by_text("暂无内容").count() > 0
                or active.get_by_text("项目正在创建中").count() > 0
            )
            if not has_content:
                all_rendered = False
            print(f"    tab {t}: rendered={has_content}")
            page.screenshot(path=os.path.join(ART, f"tab-{t}.png"), full_page=True)
        header_ok = page.locator(".proj-name").count() > 0 and bool(page.locator(".proj-name").inner_text().strip())
        check("5.详情五Tab+头部", all_rendered and header_ok,
              f"all_tabs_rendered={all_rendered} header_name={header_ok}")

        # 检查 8：事件流过滤（先选「合并请求」多为空 -> 空态；再选「全部事件」-> 有数据）
        page.locator(".el-tabs__item", has_text="事件流").first.click()
        page.wait_for_timeout(1500)
        try:
            sel = page.locator(".el-tab-pane").filter(visible=True).locator(".el-select").first
            sel.click()
            page.wait_for_timeout(600)
            page.get_by_text("合并请求", exact=True).first.click()
            page.wait_for_timeout(1600)
            act = page.locator(".el-tab-pane").filter(visible=True)
            empty_on_filter = act.locator(".el-empty").count() > 0 or act.locator(".el-table__row").count() == 0
            sel = page.locator(".el-tab-pane").filter(visible=True).locator(".el-select").first
            sel.click()
            page.wait_for_timeout(600)
            page.get_by_text("全部事件", exact=True).first.click()
            page.wait_for_timeout(1600)
            act = page.locator(".el-tab-pane").filter(visible=True)
            rows_all = act.locator(".el-table__row").count()
            check("8.事件流过滤", empty_on_filter and rows_all >= 1,
                  f"空过滤空态={empty_on_filter} 全部事件行数={rows_all}")
        except Exception as e:
            check("8.事件流过滤", False, f"异常: {e}")

        # 提交记录分页：断言活动面板的 .el-pagination 存在且含总数
        try:
            page.locator(".el-tabs__item", has_text="提交记录").first.click()
            page.wait_for_timeout(1600)
            act = page.locator(".el-tab-pane").filter(visible=True)
            pag = act.locator(".el-pagination")
            pag_present = pag.count() > 0
            total_txt = pag.first.inner_text() if pag_present else ""
            check("8.提交记录分页", pag_present and "3" in total_txt,
                  f"分页控件={pag_present} 分页文案={total_txt!r}")
        except Exception as e:
            check("8.提交记录分页", False, f"异常: {e}")

        # 检查 9：空仓库的「文件」页应是**空态引导**，而不是红字报错。
        # 旧断言要求出现「Gitee 接口调用失败」toast —— 那编码的是 GiteeContentService
        # 把 404 降级为空目录**之前**的行为。新建仓库必然没有任何提交，Gitee 对根目录
        # contents 一律返回 404，那是正常态而非故障，所以后端已刻意降级（见该 service 注释）。
        # 现在正确的验收是：没有红字 toast + 出现空态而不是一片空白。
        page.locator(".el-tabs__item", has_text="文件").first.click()
        page.wait_for_timeout(2200)
        toasts = capture_toasts(page)
        body9 = page.inner_text("body")
        no_err_toast = (not any("Gitee 接口调用失败" in t for t in toasts)
                        and not any(t.strip() == "操作失败" for t in toasts))
        empty_hint = ("仓库刚建好还没有提交" in body9 or "该目录暂无内容" in body9
                      or "目录为空" in body9)
        check("9.空仓库降级为空目录（不弹红字 + 空态引导）", no_err_toast and empty_hint,
              f"捕获toast={toasts} 空态文案={empty_hint}")
        page.screenshot(path=os.path.join(ART, "tab-files-error.png"), full_page=True)

        # 检查 7：不存在 / 跨租户 id
        ctx7, page7 = new_ctx(pw, br, tok, user, refresh)
        page7.goto(SHELL + "/gitee/projects/999999", wait_until="networkidle")
        try:
            wait_for_anchor(page7, "项目不存在", timeout=20000)
        except Exception:
            pass
        page7.wait_for_timeout(1500)
        alert_txt = page7.locator(".el-alert").first.inner_text() if page7.locator(".el-alert").count() else ""
        c7 = ("项目不存在或不属于当前租户" in alert_txt) and ("home" not in page7.url)
        check("7.不存在id空态", c7, f"alert={alert_txt!r} url={page7.url}")
        page7.screenshot(path=os.path.join(ART, "notfound-999999.png"), full_page=True)
        ctx7.close()

        # ---------------- 检查 10（伸长）：OAuth 绑定 ----------------
        try:
            ctx10, page10 = new_ctx(pw, br, tok, user, refresh)
            open_projects(page10, anchor="我的 Gitee 账号")
            bind_btn = page10.get_by_text("绑定 Gitee 账号", exact=True)
            if bind_btn.count() == 0:
                # 可能已绑定（上次运行遗留）：先看是否已是已绑定态
                already = page10.get_by_text("Gitee 账号", exact=True).count() > 0
                check("10.OAuth绑定", already, f"未找到绑定按钮; 已绑定态={already}")
            else:
                with page10.expect_popup() as pop:
                    bind_btn.first.click()
                popup = pop.value
                popup.wait_for_load_state("load", timeout=20000)
                try:
                    popup.wait_for_event("close", timeout=25000)
                except Exception:
                    pass
                bound = False
                for _ in range(40):
                    page10.wait_for_timeout(1000)
                    unbound = page10.get_by_text("尚未绑定 Gitee 账号").count() > 0
                    has_acct = page10.get_by_text("Gitee 账号", exact=True).count() > 0
                    if (not unbound) and has_acct:
                        bound = True
                        break
                check("10.OAuth绑定", bound, f"绑定卡片从未绑定转为已绑定={'是' if bound else '否'}")
                page10.screenshot(path=os.path.join(ART, "oauth-bound.png"), full_page=True)
            ctx10.close()
        except Exception as e:
            check("10.OAuth绑定", False, f"异常: {e}")

        # ---------------- 检查 11（伸长）：网页上传（znkjyf_admin 已绑定） ----------------
        try:
            t2, u2, r2 = creds["znkjyf_admin"]
            ctx11, page11 = new_ctx(pw, br, t2, u2, r2)
            # 项目必须**现建**：旧代码硬编码 /gitee/projects/10，而桩是内存态，桩一重启
            # 该项目仓库就消失，上传必然 404，症状却是「弹窗不关、刷新目录被遮罩挡住」。
            pid11 = ensure_upload_project(t2)
            if not pid11:
                # 抛给外层 except 统一记 FAIL（而不是 return：return 会跳过最后的汇总输出）
                raise RuntimeError("自洽项目未能在超时内达到 ACTIVE（无法验证上传）")
            page11.goto(SHELL + f"/gitee/projects/{pid11}", wait_until="networkidle")
            try:
                wait_for_anchor(page11, "文件", timeout=30000)
            except Exception:
                pass
            page11.wait_for_timeout(2500)
            page11.locator(".el-tabs__item", has_text="文件").first.click()
            page11.wait_for_timeout(1500)
            up = page11.get_by_text("上传文件", exact=True)
            if up.count() == 0:
                check("11.网页上传", False, "未找到「上传文件」按钮（可能无 manage 权限）")
            else:
                up.first.click()
                page11.wait_for_timeout(800)
                page11.locator('.el-dialog input[placeholder="如 src/main/java/App.java"]').fill("verify-v48.txt")
                page11.locator('.el-dialog textarea[placeholder="输入或选择本地文本文件"]').fill("V48 verification upload")
                page11.locator(".el-dialog").get_by_role("button", name="提交", exact=True).click()
                toasts11 = poll_success_toast(page11, timeout=8000)
                success = any("上传成功" in t for t in toasts11)
                page11.wait_for_timeout(1500)
                page11.get_by_text("刷新目录", exact=True).first.click()
                page11.wait_for_timeout(1500)
                file_shown = page11.get_by_text("verify-v48.txt", exact=False).count() > 0
                page11.locator(".el-tabs__item", has_text="提交记录").first.click()
                page11.wait_for_timeout(1500)
                web_src = page11.get_by_text("网页上传", exact=True).count() > 0
                page11.locator(".el-tabs__item", has_text="事件流").first.click()
                page11.wait_for_timeout(1500)
                evt_rows = page11.locator(".el-tab-pane").filter(visible=True).locator(".el-table__row").count()
                check("11.网页上传", success and file_shown and web_src,
                      f"成功toast={success} 文件列出={file_shown} 提交源=网页上传:{web_src} 事件行={evt_rows}")
                page11.screenshot(path=os.path.join(ART, "upload-result.png"), full_page=True)
            ctx11.close()
        except Exception as e:
            check("11.网页上传", False, f"异常: {e}")

        br.close()

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 70)
    print("控制台 error（逐条）：")
    print("  none observed" if not console_errors else "\n".join(f"  - {e}" for e in console_errors))
    print(">=500 响应（逐条）：")
    print("  none observed" if not server_5xx else "\n".join(f"  - {s}" for s in server_5xx))
    if resource_404:
        print("非API的404资源（疑似 favicon/源映射，非业务错误）：")
        for u in resource_404:
            print("  -", u)
    passed = sum(1 for _, c, _ in results if c)
    print(f"\n总计 {passed}/{len(results)} 通过")
    for cid, c, d in results:
        if not c:
            print(f"  FAIL {cid}: {d}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
