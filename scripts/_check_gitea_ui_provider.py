"""在 **Gitea 接线**下渲染「项目与仓库」两页，核对界面文案自报的是 Gitea 而不是 Gitee。

为什么需要它：后端 `/gitee/config` 回 `providerLabel` 只是「数据到了」，
真正的判据是**渲染出来的页面**不再谎报托管方。单测与接口测都到不了这一层。

只读 + 自净：临时建一个项目用于打开详情页，跑完连仓删除。

用法：python scripts/_check_gitea_ui_provider.py
"""
import json
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
DEPT = 11
TENANT = "某某市某某区大数据管理局"

C = httpx.Client(timeout=60, trust_env=False)

RES = []


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def login(name, pwd="User@123", tenant=TENANT):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd,
                                         "tenantName": tenant}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"], d["data"].get("refreshToken", "")


def seed(ctx, tok, user, refresh):
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s);"
        "localStorage.setItem('aioa.refreshToken', %s);"
        "localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(refresh), json.dumps(json.dumps(user, ensure_ascii=False)))
    )


def body_text(page):
    return page.evaluate("() => document.body ? document.body.innerText : ''")


def main():
    tok, user, ref = login("dsj_admin")
    h = {"Authorization": f"Bearer {tok}"}

    # 后端 config 的三个字段（渲染取数来源，先确认取到了）
    cfg = (C.get(f"{API}/gitee/config", headers=h).json().get("data") or {})
    chk("C1 /config.providerLabel == Gitea", cfg.get("providerLabel") == "Gitea", cfg)

    # 建一个临时项目，供详情页核对（跑完删除并连带删仓）
    name = "UI 文案核对 " + str(int(time.time()))
    d = C.post(f"{API}/gitee/projects", headers=h,
               json={"name": name, "departmentId": DEPT,
                     "description": "gitea 接线界面文案核对", "visibility": "private"}).json()
    pid = (d.get("data") or {}).get("id")
    if not chk("C2 临时项目创建成功", bool(pid), d.get("message") or d):
        return
    status = None
    for _ in range(45):
        time.sleep(2)
        dd = (C.get(f"{API}/gitee/projects/{pid}", headers=h).json().get("data") or {})
        status = (dd.get("project") or {}).get("status") or dd.get("status")
        if status in ("ACTIVE", "FAILED"):
            break
    chk("C3 临时项目终态 ACTIVE", status == "ACTIVE", status)

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="msedge", headless=True)
            ctx = br.new_context(viewport={"width": 1440, "height": 1000})
            seed(ctx, tok, user, ref)
            page = ctx.new_page()

            # ---------- 列表页 ----------
            page.goto(SHELL + "/gitee/projects", wait_until="networkidle")
            page.wait_for_timeout(2500)
            t = body_text(page)
            chk("L1 页头自报 Gitea（不再写「Gitee 联动」）", "Gitea 联动" in t, t[:200])
            chk("L2 绑定卡片标题为「我的 Gitea 账号」", "我的 Gitea 账号" in t)
            chk("L3 整页不出现「Gitee」字样", "Gitee" not in t,
                [ln for ln in t.splitlines() if "Gitee" in ln][:6])
            chk("L4 组织卡片标题为「本企业 Gitea 组织」", "本企业 Gitea 组织" in t)
            chk("L5 初始化卡片标题为「企业 Gitea 初始化」", "企业 Gitea 初始化" in t)
            chk("L6 项目列表渲染出临时项目", name in t, t[t.find("项目"):][:200])

            # ---------- 详情页 ----------
            page.goto(f"{SHELL}/gitee/projects/{pid}", wait_until="networkidle")
            page.wait_for_timeout(2500)
            dt = body_text(page)
            chk("D1 详情页概览页签不出现「Gitee」字样", "Gitee" not in dt,
                [ln for ln in dt.splitlines() if "Gitee" in ln][:6])
            chk("D2 跳转按钮自报 Gitea", "跳转 Gitea" in dt)
            chk("D3 仓库地址标签为「Gitea 网页」", "Gitea 网页" in dt, dt[:200])
            chk("D4 危险操作说「删除 Gitea 仓库」", "删除 Gitea 仓库" in dt)

            # 非活动页签是 display:none，innerText 取不到 —— 必须切过去再断言
            page.get_by_role("tab", name="成员").click()
            page.wait_for_timeout(1600)
            mt = body_text(page)
            chk("D5 成员表头为「Gitea 账号」", "Gitea 账号" in mt,
                [ln for ln in mt.splitlines() if "账号" in ln][:4])
            chk("D6 成员页签不出现「Gitee」字样", "Gitee" not in mt,
                [ln for ln in mt.splitlines() if "Gitee" in ln][:6])

            page.get_by_role("tab", name="事件流").click()
            page.wait_for_timeout(1600)
            et = body_text(page)
            chk("D7 事件表头为「Gitea 事件」", "Gitea 事件" in et,
                [ln for ln in et.splitlines() if "事件" in ln][:4])
            chk("D8 事件页签不出现「Gitee」字样", "Gitee" not in et,
                [ln for ln in et.splitlines() if "Gitee" in ln][:6])

            ctx.close()
            br.close()
    finally:
        # ---------- 自净：删项目 + 连带删仓（不留残仓在真机组织里） ----------
        r = C.delete(f"{API}/gitee/projects/{pid}?purgeRepo=true", headers=h).json()
        print("  清理：", r.get("code"), (r.get("data") or {}).get("note"))

    okn = sum(1 for _, v in RES if v)
    print("\n汇总：PASS=%d / %d" % (okn, len(RES)))
    return 0 if okn == len(RES) else 1


if __name__ == "__main__":
    sys.exit(main())
