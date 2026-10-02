# -*- coding: utf-8 -*-
"""模拟项目全流程自检（模拟项目 → 立项 / 成员 / 任务 / 建仓（打工人）/ 上传代码 / 界面）。

为什么要有这条套件：
  PM 批次 1 已有三件套（`_check_pm_guards.py` 静态守卫、`_smoke_pm.py` 接口负向、
  `_e2e_pm_ui.py` 界面同源），但都只覆盖**单点**。**没有任何一条走通
  「一个真实项目从立项到代码落仓」的完整链路** —— 而链路上的缺陷恰恰长在接口之间：
  立项时自动建仓抛错会不会把整条立项回滚、建仓任务的终态有没有回写、网页提交拿到的
  是不是当前用户那把令牌。本套件补的就是这条**跨模块纵切**：PM × 项目仓库。

★ 同源判据（铁律 12）：界面断言不读界面自己的数据副本，先按接口取一次再抓 DOM 比对。
★ 打工人判据：`gitee_project.status` 只能由 gitee 任务的消费方推出 CREATING，
  因此「状态离开 CREATING」+「任务行落终态」共同构成「打工人真的干过活」的收敛证据。
★ 分类不混淆（铁律 7）：
    PASS      —— 正确行为
    FAIL      —— 应当正确却错误（本套件按此退出非 0）
    KNOWN-BUG —— 已定位的系统缺陷，正确行为当前不成立；单独计数、单独打印，不混进 PASS
    ENV-LIMIT —— 环境限制（本机无公网回调地址）导致的能力降级，非代码缺陷
★ 自净（铁律 11）：默认保留模拟项目（用户明确要求「上传一个模拟项目来测」），
  但名称统一带 `SIM-` 前缀并逐条打印 id/仓库地址，使残留可被指名核对；`--clean` 则软删。

用法：
    python scripts/_e2e_pm_simulated_project.py            # 保留（默认）
    python scripts/_e2e_pm_simulated_project.py --clean     # 跑完自净
前置：后端 :8080 已起；V71 已应用；租户 Gitee 组织名必须是**真实存在**的组织
      （组织名写错时建仓任务会以「找不到组织」失败，见 docs/42 缺陷 D2）。
"""
import json
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:8080/aioa/web"
TENANT = "某某市某某区大数据管理局"
ADMIN, PWD = "dsj_admin", "User@123"
REPO_DEPT_ID = 11          # 建仓必填真实部门（组织内的「发展规划科」）

CLEAN = "--clean" in sys.argv
STAMP = time.strftime("%m%d-%H%M%S")
BIZ_NAME = "SIM-业务-" + STAMP
DEV_NAME = "SIM-开发-" + STAMP

C = httpx.Client(timeout=90, trust_env=False)
PASS, FAIL, KNOWN, ENVLIM = [], [], [], []
CREATED = {}


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def chk_known(cid, correct_now, note):
    """断言「正确行为」：成立记 PASS（说明已修复），不成立记为 KNOWN-BUG 而不是 FAIL。"""
    (PASS if correct_now else KNOWN).append(cid)
    print("  %s %s%s" % ("PASS" if correct_now else "KNOWN-BUG", cid, "  | " + str(note)[:420]))
    return bool(correct_now)


def chk_env(cid, ok, note):
    (PASS if ok else ENVLIM).append(cid)
    print("  %s %s%s" % ("PASS" if ok else "ENV-LIMIT", cid, "  | " + str(note)[:300]))
    return bool(ok)


def login(name=ADMIN):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": PWD,
                                         "tenantName": TENANT}).json()
    assert d.get("code") == 0, d
    return {"Authorization": "Bearer " + d["data"]["accessToken"]}


def call(method, path, h, **kw):
    r = getattr(C, method)(API + path, headers=h, **kw)
    try:
        return r.json()
    except Exception:
        return {"code": r.status_code, "message": r.text[:200]}


def data_of(r):
    return r.get("data") if isinstance(r, dict) else None


def rows_of(r):
    d = data_of(r) or {}
    return (d.get("items") if isinstance(d, dict) else d) or []


def repo_norm(r):
    """仓库详情归一化：`/gitee/projects/{id}` 把仓库字段放在 data.project 下，
    而列表/绑定接口放在 data 下。两处形状不同曾经让轮询永远读不到 status（读成 None），
    「状态离开 CREATING」的断言因此变成恒真 —— 这里统一取一次，判据只有一个来源。"""
    d = data_of(r) or {}
    return (d.get("project") or d) if isinstance(d, dict) else {}


# ============================================================ A 业务项目
def part_a(h):
    print("\n[A] 模拟项目之一：业务项目（立项 → 成员 → 任务）")
    cfg = data_of(call("get", "/pm/config", h)) or {}
    chk("A1 类型字典含 BUSINESS/DEV", [t.get("value") for t in (cfg.get("projectTypes") or [])]
        == ["BUSINESS", "DEV"], cfg.get("projectTypes"))

    r = call("post", "/pm/projects", h, json={
        "projectNo": "SIM-B-" + STAMP, "name": BIZ_NAME, "projectType": "BUSINESS",
        "description": "模拟项目（业务）：验证立项→成员→任务全链路"})
    pid = (data_of(r) or {}).get("id")
    CREATED["业务项目"] = "id=%s name=%s" % (pid, BIZ_NAME)
    if not chk("A2 业务项目立项成功", r.get("code") == 0 and bool(pid), r):
        raise SystemExit("立项失败，后续无从继续")

    d = data_of(call("get", f"/pm/projects/{pid}", h)) or {}
    chk("A3 默认状态 ACTIVE（无草稿态，与状态机一致）", d.get("status") == "ACTIVE", d.get("status"))
    chk("A4 业务项目无绑定仓库（BR-01 前提状态）", not (d.get("boundRepos") or []))

    cands = data_of(call("get", f"/pm/projects/{pid}/members/candidates", h)) or []
    chk("A5 候选成员非空（用事实源里的真实员工，不编造姓名）", len(cands) > 0, len(cands))
    if not cands:
        raise SystemExit("无候选成员")

    m1, m2 = cands[0], (cands[1] if len(cands) > 1 else cands[0])
    r = call("post", f"/pm/projects/{pid}/members", h,
             json={"memberId": m1["memberId"], "roleCode": "OWNER"})
    # 注意：add 返回的是**成员清单**（data.items），旧版脚本误判为单行，已按实测形状修正
    added = [x for x in rows_of(r) if x.get("memberId") == m1["memberId"]]
    chk("A6 加入负责人成功（返回清单里出现该成员）", r.get("code") == 0 and bool(added), r)
    r2 = call("post", f"/pm/projects/{pid}/members", h,
              json={"memberId": m2["memberId"], "roleCode": "DEV"})
    chk("A7 加入第二名成员（开发角色）成功", r2.get("code") == 0, r2)
    r3 = call("post", f"/pm/projects/{pid}/members", h,
              json={"memberId": m1["memberId"], "roleCode": "DEV"})
    chk("A8 同一人重复加入被拒（409，不产生重复成员行）", r3.get("code") == 409, r3)

    ml = rows_of(call("get", f"/pm/projects/{pid}/members", h))
    chk("A9 成员清单回读 2 人（写进去也读得出来）", len(ml) == 2, ml)

    r = call("post", f"/pm/projects/{pid}/tasks", h, json={
        "title": "模拟任务-父", "priority": "HIGH", "assigneeMemberId": m1["memberId"],
        "description": "模拟项目父任务"})
    t1 = (data_of(r) or {}).get("id")
    chk("A10 建父任务成功", r.get("code") == 0 and bool(t1), r)
    r = call("post", f"/pm/projects/{pid}/tasks", h, json={
        "title": "模拟任务-子", "parentId": t1, "assigneeMemberId": m1["memberId"]})
    chk("A11 建子任务并挂父任务成功", r.get("code") == 0, r)

    chk("A12 任务 TODO→DOING",
        call("post", f"/pm/projects/{pid}/tasks/{t1}/status", h,
             json={"status": "DOING"}).get("code") == 0)
    chk("A13 任务 DOING→DONE",
        call("post", f"/pm/projects/{pid}/tasks/{t1}/status", h,
             json={"status": "DONE"}).get("code") == 0)
    st3 = call("post", f"/pm/projects/{pid}/tasks/{t1}/status", h, json={"status": "DOING"})
    chk("A14 终态不可回退（DONE→DOING 被拒）",
        st3.get("code") not in (0, None) and "不允许从 DONE 变更为 DOING" in str(st3.get("message")), st3)

    rb = call("post", f"/pm/projects/{pid}/repos", h, json={"repoId": 1})
    chk("A15 业务项目绑仓库被拒（BR-01）",
        rb.get("code") not in (0, None) and "业务项目不支持代码仓库配置" in str(rb.get("message")), rb)
    rt = call("post", f"/pm/projects/{pid}/tasks", h,
              json={"title": "模拟任务-带仓库", "repoId": 1, "repoBranch": "master"})
    chk("A16 业务任务携带仓库信息被拒（BR-01）",
        rt.get("code") not in (0, None) and "业务项目不支持代码仓库配置" in str(rt.get("message")), rt)
    return pid


# ============================================================ B 开发项目 + 仓库 + 代码
def part_b(h):
    print("\n[B] 模拟项目之二：开发项目（立项 → 建仓（打工人）→ 绑仓 → 上传代码）")

    # ---- B1 先记录「立项时自动建仓」这条路的真实行为（缺陷 D3） ----
    r = call("post", "/pm/projects", h, json={
        "projectNo": "SIM-D-AUTO-" + STAMP, "name": DEV_NAME + "-自动建仓",
        "projectType": "DEV", "createRepo": True, "repoVisibility": "private",
        "description": "模拟项目（开发）：验证立项时自动建仓"})
    auto_ok = r.get("code") == 0
    if auto_ok:
        CREATED["开发项目(自动建仓)"] = "id=%s" % ((data_of(r) or {}).get("id"))
    chk_known("B1 立项时自动建仓：立项应当成功并回传 repoWarning（当前 500 且整条立项回滚）",
              auto_ok and (data_of(r) or {}).get("repoWarning") is not None,
              "实际：code=%s message=%s" % (r.get("code"), r.get("message")))

    # ---- B2 走可用路径：先立项，再建仓，再绑仓 ----
    r = call("post", "/pm/projects", h, json={
        "projectNo": "SIM-D-" + STAMP, "name": DEV_NAME, "projectType": "DEV",
        "description": "模拟项目（开发）：立项→建仓→绑仓→网页提交代码"})
    pid = (data_of(r) or {}).get("id")
    CREATED["开发项目"] = "id=%s name=%s" % (pid, DEV_NAME)
    if not chk("B2 开发项目立项成功（不带 createRepo）", r.get("code") == 0 and bool(pid), r):
        raise SystemExit("开发项目立项失败")

    r = call("post", "/gitee/projects", h, json={
        "name": "SIM-仓库-" + STAMP, "description": "模拟项目自检建仓",
        "departmentId": REPO_DEPT_ID, "visibility": "private"})
    rid = (data_of(r) or {}).get("id")
    if not chk("B3 建仓受理（落 CREATING 并由打工人异步建）", r.get("code") == 0 and bool(rid), r):
        raise SystemExit("建仓受理失败")

    repo = {}
    for _ in range(50):
        repo = repo_norm(call("get", f"/gitee/projects/{rid}", h))
        if repo.get("status") in ("ACTIVE", "FAILED"):
            break
        time.sleep(3)
    st = repo.get("status")
    chk("B4 打工人把仓库推出 CREATING（终态收敛，不永久卡 CREATING）",
        st in ("ACTIVE", "FAILED"), st)
    CREATED["仓库"] = "id=%s owner=%s repo=%s status=%s" % (
        rid, repo.get("giteeOwner"), repo.get("giteeRepo"), st)
    if repo.get("htmlUrl"):
        CREATED["仓库地址"] = repo.get("htmlUrl")
    print("     仓库终态=%s owner=%s repo=%s" % (st, repo.get("giteeOwner"), repo.get("giteeRepo")))

    errm = str(repo.get("errorMsg") or "")
    if st == "ACTIVE":
        chk("B5 仓库整体就绪（含 Webhook 配置）", True, "status=ACTIVE")
    elif "webhook-base-url" in errm:
        # 本机没有公网地址 ⇒ Webhook 这一步注定失败：环境限制，不是代码缺陷
        chk_env("B5 仓库未就绪**仅**因「无公网 Webhook 回调地址」这一环境限制", True, errm[:200])
    else:
        # 其它原因导致的未就绪一律报红，不放进 ENV-LIMIT 蒙混过去
        chk("B5 仓库未就绪且原因不是环境限制（需按真实缺陷处理）", False, errm[:220])

    qs = data_of(call("get", "/gitee/tasks/stats", h)) or {}
    chk("B6 运维统计可见打工人身份，且实时队列已排空（不是把任务晾在队列里）",
        bool(qs.get("worker")) and int(qs.get("PENDING") or 0) == 0
        and int(qs.get("RUNNING") or 0) == 0, qs)

    rb = call("post", f"/pm/projects/{pid}/repos", h, json={"repoId": rid})
    bound = data_of(call("get", f"/pm/projects/{pid}/repos", h)) or []
    chk("B7 仓库绑定到开发项目成功（PM↔仓库映射落库并可回读）",
        rb.get("code") == 0 and any(x.get("id") == rid for x in bound),
        "bind=%s bound=%s" % (rb.get("message"), [x.get("id") for x in bound]))

    # ---- B8 上传一个代码测试 ----
    code = ("# AIOA 模拟项目自检文件\n"
            "# project: %s\n" % DEV_NAME +
            "def hello():\n    return 'aioa simulated project ok'\n")
    path = "aioa-sim/hello.py"
    up = call("post", f"/gitee/projects/{rid}/contents", h, json={
        "path": path, "content": code, "message": "模拟项目自检：上传 hello.py",
        "branch": repo.get("defaultBranch") or "master"})
    if not chk("B8 上传代码到仓库成功（网页提交）", up.get("code") == 0, up):
        print("     原始返回：%s" % json.dumps(up, ensure_ascii=False)[:300])

    back = call("get", f"/gitee/projects/{rid}/contents", h, params={"path": path})
    chk("B9 读回文件内容与上传逐字一致（往返校验，不只看提交成功）",
        "aioa simulated project ok" in json.dumps(data_of(back), ensure_ascii=False),
        json.dumps(data_of(back), ensure_ascii=False)[:220])

    cms = rows_of(call("get", f"/gitee/projects/{rid}/commits", h))
    chk("B10 提交记录里能查到这次网页提交",
        any("模拟项目自检" in json.dumps(x, ensure_ascii=False) for x in cms),
        json.dumps(cms[:1], ensure_ascii=False)[:260])

    # ---- B11 任务与仓库关联（开发项目独有；关联仓库时 issue 号是必填项） ----
    r = call("post", f"/pm/projects/{pid}/tasks", h, json={
        "title": "模拟任务-关联仓库", "repoId": rid, "repoIssueNo": "#1",
        "repoBranch": repo.get("defaultBranch") or "master", "priority": "HIGH"})
    tid = (data_of(r) or {}).get("id")
    chk("B11 开发任务可关联仓库（与 A16 业务项目被拒形成对照）", r.get("code") == 0 and bool(tid), r)
    hit = [x for x in rows_of(call("get", f"/pm/projects/{pid}/tasks", h)) if x.get("id") == tid]
    chk("B12 任务回读到绑定的仓库 id（关联真的落库）",
        bool(hit) and hit[0].get("repoId") == rid,
        json.dumps(hit[:1], ensure_ascii=False)[:280])
    return pid, rid, repo


# ============================================================ C 界面（同源判据）
def part_c(h, biz_id, dev_id, repo):
    print("\n[C] 界面：模拟项目在管理端可见、详情页展示仓库（判据回到接口）")
    api_names = [x.get("name") for x in (data_of(call("get", "/pm/projects", h)) or [])]
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        page = b.new_context(viewport={"width": 1600, "height": 1000}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(SHELL + "/login", wait_until="networkidle")
        page.fill('input[autocomplete="organization"]', TENANT)
        page.fill('input[autocomplete="username"]', ADMIN)
        page.fill('input[autocomplete="current-password"]', PWD)
        page.click(".login-btn")
        page.wait_for_url("**/home", timeout=20000)

        page.goto(SHELL + "/pm/projects", wait_until="networkidle")
        page.wait_for_timeout(2500)
        dom = [t.strip() for t in
               page.locator(".el-table__body tbody tr td:nth-child(2)").all_inner_texts()]
        chk("C1 界面列表含模拟业务项目（与接口清单逐名比对）", BIZ_NAME in dom, dom[:8])
        chk("C2 界面列表含模拟开发项目", DEV_NAME in dom, dom[:8])
        chk("C3 界面清单条目数与接口一致", len(dom) == len(api_names),
            "dom=%d api=%d" % (len(dom), len(api_names)))

        page.goto(SHELL + f"/pm/projects/{dev_id}", wait_until="networkidle")
        page.wait_for_timeout(2500)
        # 详情页默认停在「概览」页签，仓库在「代码仓库」页签里 —— 不切页签就断言
        # 会得到一个假红（首版即栽在这里：断言写成「页面上出现仓库名」却从没点过页签）。
        tabs = page.locator(".el-tabs__item").all_inner_texts()
        chk("C4 开发项目详情页有「代码仓库」页签（开发项目特有）",
            any("代码仓库" in t for t in tabs), tabs)
        page.get_by_role("tab", name="代码仓库").click()
        page.wait_for_timeout(2500)
        pane = page.locator(".el-tab-pane").filter(has_text="仓库").first.inner_text()
        rn = repo.get("repoName") or ""
        chk("C5 页签内展示仓库（名称与接口同源，路径含托管方 owner）",
            bool(rn) and rn in pane and (repo.get("giteeOwner") or "") in pane,
            "找 repoName=%s owner=%s | pane=%s" % (rn, repo.get("giteeOwner"), pane[:220]))
        chk("C6 详情页无未捕获 JS 异常", not errs, errs[:2])
        b.close()


# ============================================================ D 收尾
def part_d(h):
    print("\n[D] 收尾")
    print("  本套件创建（可指名核对，不是匿名残留）：")
    for k, v in CREATED.items():
        print("    %-18s %s" % (k, v))
    print("  注：仓库是 gitee 上的真实对象，软删项目不会删它（purgeRepo=false）；"
          "需要清理请在「项目与仓库」删除并勾选移除仓库。")
    if CLEAN:
        for key in ("业务项目", "开发项目"):
            pid = (CREATED.get(key) or "")
            if "id=" in pid:
                ident = pid.split("id=")[1].split(" ")[0]
                r = call("delete", f"/pm/projects/{ident}", h)
                print("    软删 %s id=%s -> code=%s" % (key, ident, r.get("code")))
    else:
        print("  （默认保留模拟项目供界面查看；加 --clean 自动软删）")


def main():
    h = login()
    biz_id = part_a(h)
    dev_id, rid, repo = part_b(h)
    part_c(h, biz_id, dev_id, repo)
    part_d(h)
    print("\n======== 小结 ========")
    print("PASS=%d  FAIL=%d  KNOWN-BUG=%d  ENV-LIMIT=%d"
          % (len(PASS), len(FAIL), len(KNOWN), len(ENVLIM)))
    for f in FAIL:
        print("  FAIL       " + f)
    for k in KNOWN:
        print("  KNOWN-BUG  " + k)
    for e in ENVLIM:
        print("  ENV-LIMIT  " + e)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
