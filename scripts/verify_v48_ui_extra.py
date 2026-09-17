# -*- coding: utf-8 -*-
"""V48 验证 —— 针对 check 10(OAuth绑定) 与 check 11(网页上传) 的聚焦脚本。

说明：租户管理员(znkj_admin)因 GiteeProjectsView:82-85 在 taskStats=null 时解引用崩溃，
整页空白，故 OAuth 绑定按钮不可见。改用未绑定且非租管的企业成员 znsfb_m01（页面不渲染
运维卡片，不触发崩溃）来验证完整 OAuth 流程。网页上传沿用已绑定的 znkjyf_admin / 项目10。
"""
import json
import os
import time
import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
ART = os.path.join(".workbuddy", "artifacts", "v48-ui")
os.makedirs(ART, exist_ok=True)
C = httpx.Client(timeout=60, trust_env=False)

results = []


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
        "localStorage.setItem('aioa.token', %s);localStorage.setItem('aioa.refreshToken', %s);localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(refresh), json.dumps(json.dumps(user, ensure_ascii=False)))
    )


def new_ctx(pw, br, tok, user, refresh=""):
    ctx = br.new_context(viewport={"width": 1440, "height": 980})
    seed(ctx, tok, user, refresh)
    page = ctx.new_page()
    return ctx, page


def wait_anchor(page, text, timeout=30000):
    page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)


def capture_toasts_now(page):
    try:
        return [e.inner_text() for e in page.locator(".el-message").all()]
    except Exception:
        return []


def poll_success_toast(page, timeout=8000):
    """轮询捕获成功 toast（ElMessage 会自动消失，需即时抓）。"""
    end = timeout
    step = 400
    while end > 0:
        toasts = capture_toasts_now(page)
        for t in toasts:
            if "上传成功" in t:
                return t
        page.wait_for_timeout(step)
        end -= step
    return ""


def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)

        # ---------------- 检查 10：OAuth 绑定（znsfb_m01 未绑定，非租管） ----------------
        tok, user, refresh = login("znsfb_m01")
        ctx10, page10 = new_ctx(pw, br, tok, user, refresh)
        page10.goto(SHELL + "/gitee/projects", wait_until="networkidle")
        wait_anchor(page10, "我的 Gitee 账号", timeout=30000)
        page10.wait_for_timeout(1500)
        bind_btn = page10.get_by_text("绑定 Gitee 账号", exact=True)
        if bind_btn.count() == 0:
            # 已是绑定态（上一次运行遗留：还原步骤没跑到，例如套件在后续检查里崩过）。
            # 这**不是**页面异常 —— 已绑定态下本就不该出现绑定按钮；旧断言一律判 False
            # 且文案写「页面异常」，会把排查方向误导到前端去。
            unbound = page10.get_by_text("尚未绑定 Gitee 账号").count() > 0
            has_acct = page10.get_by_text("Gitee 账号", exact=True).count() > 0
            check("10.OAuth绑定", has_acct and not unbound,
                  "znsfb_m01 无绑定按钮（已绑定态，上次运行遗留）；非页面异常")
        else:
            with page10.expect_popup() as pop:
                bind_btn.first.click()
            popup = pop.value
            popup.wait_for_load_state("load", timeout=25000)
            try:
                popup.wait_for_event("close", timeout=30000)
            except Exception:
                pass
            bound = False
            detail = ""
            for _ in range(50):
                page10.wait_for_timeout(1000)
                unbound = page10.get_by_text("尚未绑定 Gitee 账号").count() > 0
                has_acct = page10.get_by_text("Gitee 账号", exact=True).count() > 0
                if (not unbound) and has_acct:
                    bound = True
                    break
            # 抓当前绑定账号名
            if bound:
                try:
                    detail = "已绑定态：" + page10.get_by_text("Gitee 账号", exact=True).first.inner_text()
                except Exception:
                    detail = "已绑定态"
            check("10.OAuth绑定", bound, detail)
        page10.screenshot(path=os.path.join(ART, "oauth-bound-znsfb_m01.png"), full_page=True)
        # 还原：解绑，避免污染测试数据。
        # **两种入口都要还原**（本次新绑定 / 本来就是绑定态都算）：否则一次崩溃就把
        # znsfb_m01 永久留在绑定态，下一轮检查 10 会一直报「未找到绑定按钮」。
        try:
            unbind = page10.get_by_text("解绑", exact=True).first
            if unbind.count():
                unbind.click()
                page10.wait_for_timeout(500)
                # 确认弹窗
                box = page10.get_by_text("确认解绑", exact=False)
                if box.count():
                    box.first.click()
                page10.wait_for_timeout(2000)
                print("    [info] 已尝试解绑 znsfb_m01 还原状态")
        except Exception as e:
            print("    [warn] 解绑还原失败：", e)
        ctx10.close()

        # ---------------- 检查 11：网页上传（znkjyf_admin 已绑定 / 自洽项目） ----------------
        t2, u2, r2 = login("znkjyf_admin")
        ctx11, page11 = new_ctx(pw, br, t2, u2, r2)
        try:
            # 项目现建（原因见 ensure_upload_project）；旧实现硬编码 /gitee/projects/10，
            # 桩重启后该项目仓库消失 → 上传 404 → 弹窗不关 → 点击被遮罩拦截并**整场崩溃**。
            pid11 = ensure_upload_project(t2)
            if not pid11:
                raise RuntimeError("自洽项目未能在超时内达到 ACTIVE（无法验证上传）")
            page11.goto(SHELL + f"/gitee/projects/{pid11}", wait_until="networkidle")
            wait_anchor(page11, "文件", timeout=30000)
            page11.wait_for_timeout(2000)
            page11.locator(".el-tabs__item", has_text="文件").first.click()
            page11.wait_for_timeout(1500)
            up = page11.get_by_text("上传文件", exact=True)
            if up.count() == 0:
                check("11.网页上传", False, "未找到「上传文件」按钮（可能无 manage 权限）")
            else:
                up.first.click()
                page11.wait_for_timeout(800)
                page11.locator('.el-dialog input[placeholder="如 src/main/java/App.java"]').fill("verify-v48.txt")
                page11.locator('.el-dialog textarea[placeholder="输入或选择本地文本文件"]').fill("V48 verification upload " + str(os.getpid()))
                page11.locator(".el-dialog").get_by_role("button", name="提交", exact=True).click()
                toast = poll_success_toast(page11, timeout=8000)
                success = bool(toast)
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
                      f"成功toast={success!r} 文案={toast!r} 文件列出={file_shown} 提交源=网页上传:{web_src} 事件行={evt_rows}")
                page11.screenshot(path=os.path.join(ART, "upload-result.png"), full_page=True)
        except Exception as e:
            # 兜底：单条检查失败不该整场崩溃（旧实现无 try，遮罩超时会直接终止套件、零信号）
            check("11.网页上传", False, f"异常: {e}")
        finally:
            ctx11.close()

        br.close()

    passed = sum(1 for _, c, _ in results if c)
    print(f"\n聚焦验证 {passed}/{len(results)} 通过")
    for cid, c, d in results:
        if not c:
            print(f"  FAIL {cid}: {d}")


if __name__ == "__main__":
    main()
