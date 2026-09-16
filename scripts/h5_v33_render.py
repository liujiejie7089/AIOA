# -*- coding: utf-8 -*-
"""V33 用户端 H5 无头渲染校验：空卡片折叠 / 适用场景配置 / AI 解读真实生成。

用系统 Edge（channel="msedge"）免下载浏览器；用 add_init_script 注入 session 免登录。
"""
import json
import re
import sys
import time

import httpx
import pymysql
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5181"
API = "http://127.0.0.1:8080/api/v1"

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", autocommit=True)
# 二期/三期渲染夹具的 reason 前缀（用于自愈清理）
H5_PREFIX = "E2E-V43-H5"

results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def login(u, p):
    c = httpx.Client(timeout=30, trust_env=False)
    r = c.post(f"{API}/auth/login", json={"username": u, "password": p})
    d = r.json()
    return d["data"]["accessToken"], d["data"]


def ensure_self_worker(token):
    """前置夹具：普通成员自建的「仅我可见」数字员工是本套件的验证对象。

    该数据过去由 smoke_v33.py 创建、并在退出时清理，于是本套件**单独跑**时会因
    「zhangsan 名下没有 SELF 员工」而红——属测试夹具缺失，不是产品缺陷。
    这里改为自愈：没有就现造一个（后端会把越权传的 scope 强制降级为 SELF）。
    """
    c = httpx.Client(timeout=30, trust_env=False)
    h = {"Authorization": "Bearer " + token}
    ws = (c.get(f"{API}/workers", headers=h).json().get("data") or [])
    if any(w.get("visibleScope") == "SELF" for w in ws):
        return None
    d = c.post(f"{API}/workers", headers=h, json={
        "name": "H5渲染校验-自建助理", "icon": "bot",
        "description": "h5_v33_render 前置夹具：验证自建卡片带「仅我可见」标记",
        "runMode": "ON_DEMAND", "taskPrompt": "整理今日待办",
    }).json()
    wid = (d.get("data") or {}).get("id") if d.get("code") == 0 else None
    print(f"[fixture] 已创建自建数字员工 id={wid}（SELF，供「仅我可见」断言）")
    return wid


# --------------------------------------------------------------------------- 二期/三期夹具

def api_login(name, pwd="User@123"):
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": name, "password": pwd}).json()
    if d.get("code") != 0:
        raise SystemExit(f"[fixture] 登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"]


def h5_fixture_clean():
    """清理本套件二期/三期渲染夹具自建的单据，保证可重复运行。"""
    conn = pymysql.connect(**DB)
    oids = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM approval_order WHERE content LIKE %s OR title LIKE %s",
                        ("%" + H5_PREFIX + "%", "%" + H5_PREFIX + "%"))
            oids = sorted({int(r[0]) for r in cur.fetchall()})
            if oids:
                cur.execute("DELETE FROM approval_task WHERE order_id IN %s", (tuple(oids),))
                cur.execute("DELETE FROM notification WHERE ref_id IN %s", (tuple(oids),))
                cur.execute("DELETE FROM permission_grant WHERE order_id IN %s", (tuple(oids),))
                cur.execute("DELETE FROM approval_order WHERE id IN %s", (tuple(oids),))
            # 兜底：清掉历史遗留的夹具授权，避免「已持有权限」阻断重跑
            cur.execute("DELETE FROM permission_grant WHERE user_id=3144 AND reason LIKE %s",
                        (H5_PREFIX + "%",))
        conn.commit()
    finally:
        conn.close()
    return oids


def h5_fixture_prepare():
    """造两笔夹具：① 3144 的部门申请（A2-6 徽标）；② 3145 缺省申请 → 3143 收知会（A3-8）。"""
    h5_fixture_clean()
    t_ldr, me_ldr = api_login("znsfb_ldr")
    t_mem, me_mem = api_login("znsfb_m01")
    t_org, me_org = api_login("znkjyf_admin")
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/org/permissions/apply",
               headers={"Authorization": "Bearer " + t_ldr},
               json={"permissionCode": "expert:manage", "reason": H5_PREFIX + "-A26",
                     "applyAsDepartment": True, "departmentId": 101}).json()
    dept_oid = int(d["data"]["orderId"]) if d.get("code") == 0 else None
    d2 = c.post(f"{API}/org/permissions/apply",
                headers={"Authorization": "Bearer " + t_mem},
                json={"permissionCode": "worker:manage", "reason": H5_PREFIX + "-A38"}).json()
    cc_oid = int(d2["data"]["orderId"]) if d2.get("code") == 0 else None
    print(f"[fixture] 部门申请 orderId={dept_oid}（部门徽标）；缺省申请 orderId={cc_oid}（对应知会）")
    return {"ldr": (t_ldr, me_ldr), "mem": (t_mem, me_mem), "org": (t_org, me_org),
            "dept_oid": dept_oid, "cc_oid": cc_oid}


def check_v43_three_phase(br, fix):
    """二期 A2-6（部门申请徽标）+ 三期 A3-8（抄送未读/点开已读）渲染断言。"""
    print("\n--- 7. 二期/三期：部门申请徽标 + 抄送未读（A2-6 / A3-8） ---")

    def open_h5(tok, user):
        ctx = br.new_context(viewport={"width": 390, "height": 844})
        sess = json.dumps({"token": tok, "user": user.get("user", user)}, ensure_ascii=False)
        ctx.add_init_script(f"localStorage.setItem('aioa_session', {json.dumps(sess)})")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/index.html", wait_until="networkidle")
        pg.wait_for_timeout(3500)
        return ctx, pg, errs

    # ---- A2-6：部门申请徽标 + 部门名 ----
    ctx, page, errs = open_h5(*fix["ldr"])
    page.evaluate("() => go('page-perm')")
    page.wait_for_timeout(1500)
    lst = page.inner_text("#permApplyList") if page.query_selector("#permApplyList") else ""
    check("A2-6.3「我的申请」部门单显示「部门申请」徽标", "部门申请" in lst, f"text={lst[:120]!r}")
    check("A2-6.4 部门徽标带部门名「算法部」", "算法部" in lst, "")
    check("A2-6.5 部门徽标页无 JS 运行时异常", len(errs) == 0, "; ".join(errs[:3]))
    ctx.close()

    # ---- A3-8：抄送我的未读 → 点开置已读 → 已阅 ----
    ctx, page, errs = open_h5(*fix["org"])
    page.evaluate("() => { go('page-todo'); switchTodoTab('cc'); }")
    page.wait_for_timeout(1200)

    def badge_num():
        el = page.query_selector("#todoCcUnreadBadge")
        if not el or el.evaluate("e=>getComputedStyle(e).display") == "none":
            return 0
        m = re.search(r"(\d+)", el.inner_text())
        return int(m.group(1)) if m else 0

    n_before = badge_num()
    check("A3-8.1「抄送我的」显示未读角标（未读 N，N≥1）", n_before >= 1, f"未读={n_before}")
    cc0 = page.inner_text("#todoCc") if page.query_selector("#todoCc") else ""
    check("A3-8.2 初始该知会条目未显示「已阅」", "已阅" not in cc0, f"cc={cc0[:80]!r}")

    # 底部「待办」角标：CC 任务不计入「待我处理」（CC 不占待办）
    cc_in_todo = page.evaluate("() => (state.todoApprovals||[]).some(a=>a.id===%d)" % fix["cc_oid"])
    check("A3-8.3 CC 单不在「待我处理」列表（CC 不占待办）", cc_in_todo is False, "")

    # 口径依据：docs/25 §4.1「CC 不点亮待办角标」；裁决于 2026-09-16。
    # 期望值在 Python 侧由原始 state（ccApprovals 的 id 集 + notifItems 行）自行推导，
    # **不复刻** H5 的过滤实现（避免「同源同错」——测试与实现共用同一段逻辑即无法证伪）。
    tab_before = int(page.evaluate(
        "() => { const e=document.getElementById('tabCnt'); return e && e.textContent ? e.textContent : '0'; }") or 0)
    pending = int(page.evaluate(
        "() => (state.canApprove ? (state.todoApprovals||[]) : []).filter(a=>a.status==='PENDING').length") or 0)
    cc_ids = page.evaluate("() => (state.ccApprovals||[]).map(x=>String(x.id))")
    notif_rows = page.evaluate(
        "() => notifItems().map(n=>({refId: n.refId==null?null:String(n.refId), readAt: !!n.readAt}))")
    cc_set = set(cc_ids or [])
    unread_all = sum(1 for n in (notif_rows or []) if not n["readAt"])
    unread_cc = sum(1 for n in (notif_rows or []) if (not n["readAt"]) and (n["refId"] in cc_set))

    # 非空洞前置：本场景必须真的存在「未读且 refId ∈ 我的抄送单」的知会，否则 4b 公式退化为旧口径、无法证伪
    check("A3-8.4a 前置：存在「未读且 refId ∈ 我的抄送单」的知会（不成立即本条失去鉴别力）",
          unread_cc >= 1,
          f"unread_cc={unread_cc} cc_ids={sorted(cc_set)} notif_n={len(notif_rows or [])}")
    # 精确公式（口径依据：docs/25 §4.1「CC 不点亮待办角标」；裁决于 2026-09-16）
    check("A3-8.4b 底部「待办」角标 = 待审单数 + (未读通知数 − 未读抄送知会数)",
          tab_before == pending + (unread_all - unread_cc),
          f"tab={tab_before} pending={pending} unread_all={unread_all} unread_cc={unread_cc}")
    # 差分守卫：证明抄送知会**确实被剔除**（否则 4b 会与旧口径同时成立而失去鉴别力）
    check("A3-8.4c 差分守卫：抄送知会被真实剔除（tab < 待审单数 + 未读通知数）",
          tab_before < pending + unread_all, f"tab={tab_before} pending+unread_all={pending + unread_all}")

    # 点开详情 → 自动置已读
    row = page.query_selector("#todoCc .todo-item")
    if row:
        row.click()
        page.wait_for_timeout(1800)
    page.evaluate("() => { go('page-todo'); switchTodoTab('cc'); }")
    page.wait_for_timeout(1000)
    n_after = badge_num()
    tab_after = int(page.evaluate(
        "() => { const e=document.getElementById('tabCnt'); return e && e.textContent ? e.textContent : '0'; }") or 0)
    cc1 = page.inner_text("#todoCc") if page.query_selector("#todoCc") else ""
    # 反向守卫：该知会原本就不计入底部角标，读掉后角标必须**保持不变**（与 Tab 内未读 −1 形成对照，
    # 若实现把 CC 通知错误计入 tab，则此处 tab_after 会 −1 而被捕获）
    check("A3-8.4d 反向守卫：抄送知会读掉后底部角标保持不变（tab_after == tab_before）",
          tab_after == tab_before, f"tab {tab_before} → {tab_after}（应相等）；ccBadge {n_before} → {n_after}")
    check("A3-8.5 点开详情后未读计数减 1（角标消失或 -1）",
          n_after == max(0, n_before - 1), f"{n_before} → {n_after}")
    check("A3-8.6 已读条目显示「已阅」", "已阅" in cc1, f"cc={cc1[:80]!r}")
    check("A3-8.7 抄送页无 JS 运行时异常", len(errs) == 0, "; ".join(errs[:3]))
    ctx.close()


def main():
    token, me = login("zhangsan", "User@123")
    ensure_self_worker(token)
    session = json.dumps({"token": token, "user": me.get("user", me)}, ensure_ascii=False)
    fix = h5_fixture_prepare()   # 二期/三期渲染夹具（A2-6 / A3-8）

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844})
        ctx.add_init_script(f"localStorage.setItem('aioa_session', {json.dumps(session)})")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/index.html", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # ---------- 4. 空卡片自动折叠 ----------
        def disp(sel):
            return page.eval_on_selector(sel, "el => getComputedStyle(el).display") if page.query_selector(sel) else "MISSING"

        print("\n--- 4. 工作台空卡片折叠 ---")
        for sel, name in [("#cardKpi", "经营数据卡"), ("#cardToday", "今天要办的事"),
                          ("#secSkills", "快捷技能标题"), ("#skillGrid", "快捷技能格子"),
                          ("#secExperts", "推荐专家标题"), ("#homeExperts", "推荐专家卡")]:
            d = disp(sel)
            print(f"      {name}({sel}) display={d}")

        # 有数据的必须显示
        check("有数据的模块保持可见（#cardKpi 显示）", disp("#cardKpi") != "none",
              f"display={disp('#cardKpi')}")
        # 折叠兜底块：任一模块有数据时应隐藏
        he = disp("#homeEmpty")
        check("兜底空态在有数据时隐藏", he in ("none", "MISSING"), f"display={he}")

        # 构造「全空」：清空 state 后重渲染，验证四块全部折叠且兜底出现
        page.evaluate("""() => {
            state.kpi = {month:null, quarter:null};
            state.skills = []; state.experts = []; state.notifs = []; state.approvals = [];
            renderAll();
        }""")
        page.wait_for_timeout(600)
        collapsed = all(disp(s) == "none" for s in ["#cardKpi", "#cardToday", "#secSkills", "#secExperts"])
        check("全空时四块全部折叠", collapsed,
              " ".join(f"{s}={disp(s)}" for s in ["#cardKpi", "#cardToday", "#secSkills", "#secExperts"]))
        check("全空时兜底说明出现", disp("#homeEmpty") != "none", f"display={disp('#homeEmpty')}")

        # 恢复数据
        page.evaluate("() => location.reload()")
        page.wait_for_timeout(3500)

        # ---------- 6. AI 解读 ----------
        print("\n--- 6. AI 解读按钮 ---")
        if page.query_selector("#kpiInsightBtn"):
            before = page.inner_text("#kpiInsight")
            page.click("#kpiInsightBtn")
            page.wait_for_timeout(1000)
            # 等待按钮文案变化（生成中 → 重新解读），最多 90s
            try:
                page.wait_for_function(
                    "() => ['重新解读','AI 解读'].includes(document.getElementById('kpiInsightBtn').textContent.trim())"
                    " && !document.getElementById('kpiInsightBtn').disabled",
                    timeout=90000)
            except Exception:
                pass
            after = page.inner_text("#kpiInsight")
            btn = page.inner_text("#kpiInsightBtn").strip()
            check("点击后触发真实生成（按钮变为「重新解读」）", btn == "重新解读", f"btn={btn}")
            check("看板展示内容已更新", after != before and len(after) > 30,
                  f"长度 {len(before)}→{len(after)}")
            print(f"      解读摘要：{after[:100]}")
            src = page.inner_text("#kpiSource")
            check("来源标注为 AI 生成", "AI" in src, f"source={src}")
        else:
            check("存在 #kpiInsightBtn", False)

        # ---------- 5. 词元包适用场景 ----------
        print("\n--- 5. 词元包适用场景 ---")
        page.evaluate("() => go('page-buy')")
        page.wait_for_timeout(2500)
        scenes = page.inner_text("#pkgScenes") if page.query_selector("#pkgScenes") else ""
        check("适用场景已渲染", len(scenes.strip()) > 10, f"长度={len(scenes.strip())}")
        for kw in ["个人试用", "团队协作", "企业规模化"]:
            check(f"包含场景「{kw}」", kw in scenes)
        print(f"      场景文本片段：{scenes[:120]}".replace("\n", " / "))

        # ---------- 3. 数字员工自建入口 ----------
        print("\n--- 3. 数字员工自建/自改入口 ---")
        page.evaluate("() => go('page-agent')")
        page.wait_for_timeout(2000)
        act = disp("#agentActions")
        check("创建入口对普通用户可见", act != "none", f"display={act}")
        owned = page.evaluate(
            "() => (state.workers||[]).filter(w=>w.mine===true).length")
        check("本人创建的员工带 mine 标记", owned > 0, f"mine 数量={owned}")
        # 本人创建的卡片应出现「⋯」菜单（可编辑）
        has_menu = page.evaluate("""() => Array.from(document.querySelectorAll('#agentList .agent-card'))
            .some(c => c.querySelector('.agent-menu') && c.textContent.includes('仅我可见'))""")
        check("自建卡片出现「仅我可见」标记且有管理菜单", bool(has_menu))

        # ---------- 7. 二期/三期：部门申请徽标 + 抄送未读 ----------
        check_v43_three_phase(b, fix)

        check("无 JS 运行时异常", len(errors) == 0, "; ".join(errors[:3]))

        page.screenshot(path="scripts/_v33_home.png", full_page=False)
        b.close()

    cleaned = h5_fixture_clean()
    print(f"[fixture] 已清理二期/三期渲染夹具单据 {cleaned}")

    n = len(results)
    bad = [r for r in results if not r[1]]
    print(f"\n==== 结果：{n - len(bad)}/{n} 通过 ====")
    for t, _, d in bad:
        print(f"  FAIL {t} {d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
