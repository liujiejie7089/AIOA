# -*- coding: utf-8 -*-
"""项目管理（PM，docs/40 批次 1）的**接口级负向冒烟**。

为什么除了静态守卫还要跑接口：
    静态守卫只能证明「判定点存在且被调用」，不能证明「它在真的请求上真的拒绝」。
    本脚本用真实 HTTP 请求打三条业务规则的**负向分支**：
      · BR-01 业务项目不接受任何代码仓库配置（立项 / 绑仓库 / 建任务三条写入路径）；
      · BR-02 已绑仓库的开发项目不能改回业务项目（409）；
      · BR-10 任务状态机终态不可回退（DONE → DOING 必被拒）。
    正向只验「业务项目能建出来」—— 它只是负向断言的对照组，证明请求本身是通的
    （否则「被拒」可能只是路径写错了）。

★ 自净：临时项目全部软删（铁律 11 —— 造数据的脚本收尾必须让数据退出业务可见面）。
★ 用法：python scripts/_smoke_pm.py   （需要后端 8080 已起、V71 迁移已应用）
"""
import sys
import time

import httpx

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"

C = httpx.Client(timeout=60, trust_env=False)
RES = []


class Abort(Exception):
    """前置断言失败时提前退出用。

    刻意不用 `return`：main 的 finally 必须执行自净，否则套件一红，
    临时项目就永久留在列表里，下次跑的人会把它们当成基线（铁律 11 的教训）。
    """


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def login(name, pwd=PWD):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd,
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"]


def call(method, path, h, **kw):
    return getattr(C, method)(f"{API}{path}", headers=h, **kw).json()


def cleanup(h, created):
    """自净：软删本次造的所有临时项目（铁律 11：造数据的脚本收尾必须让数据退出业务可见面）。"""
    ok = True
    for p in created:
        rr = call("delete", f"/pm/projects/{p}", h)
        if rr.get("code") != 0:
            ok = False
            print("    清理失败 id=%s: %s" % (p, rr.get("message")))
    chk("M8 临时项目已全部软删（自净）", ok, created)


def body(h, created, stamp):
    # ---- M1 配置端点（前端两个下拉的取数来源）
    cfg = call("get", "/pm/config", h).get("data") or {}
    types = [t.get("value") for t in (cfg.get("projectTypes") or [])]
    chk("M1 /pm/config 返回 BUSINESS 与 DEV 两个项目类型",
        types == ["BUSINESS", "DEV"], cfg.get("projectTypes"))

    # ---- M2 BR-01 负向：业务项目携带仓库字段必须被拒
    r = call("post", "/pm/projects", h, json={
        "projectNo": "PM-NEG-" + stamp, "name": "冒烟-业务项目带仓库",
        "projectType": "BUSINESS", "bindRepoId": 1})
    msg = str(r.get("message") or "")
    chk("M2 业务项目提交 bindRepoId 被拒（BR-01）",
        r.get("code") not in (0, None) and "业务项目不支持代码仓库配置" in msg, r)

    # ---- M3 正向对照：业务项目正常建得出来（证明请求通路与鉴权没问题）
    r = call("post", "/pm/projects", h, json={
        "projectNo": "PM-OK-" + stamp, "name": "冒烟-业务项目 " + stamp,
        "projectType": "BUSINESS", "budgetAmount": 1000})
    pid = (r.get("data") or {}).get("id")
    if not chk("M3 业务项目创建成功（负向断言的对照组）", r.get("code") == 0 and bool(pid), r):
        raise Abort()
    created.append(pid)
    chk("M3b 详情页仓库字段为空（业务项目不回 boundRepos 内容）",
        not (r.get("data") or {}).get("boundRepos"), (r.get("data") or {}).get("boundRepos"))

    # ---- M4 BR-01 负向：业务项目绑仓库必须被拒
    r = call("post", f"/pm/projects/{pid}/repos", h, json={"repoId": 1})
    chk("M4 业务项目绑定仓库被拒（BR-01）",
        r.get("code") not in (0, None) and "业务项目不支持代码仓库配置" in str(r.get("message")),
        r)

    # ---- M5 BR-01 负向：业务项目建任务带仓库字段必须被拒
    r = call("post", f"/pm/projects/{pid}/tasks", h, json={
        "title": "冒烟-带仓库的任务", "repoId": 1, "repoIssueNo": "1"})
    chk("M5 业务项目任务携带仓库字段被拒（BR-01）",
        r.get("code") not in (0, None) and "业务项目不支持代码仓库配置" in str(r.get("message")),
        r)

    # ---- M6 BR-10 负向：DONE 为终态，不可回退
    r = call("post", f"/pm/projects/{pid}/tasks", h, json={"title": "冒烟-状态机任务"})
    tid = (r.get("data") or {}).get("id")
    if not chk("M6a 业务任务创建成功", r.get("code") == 0 and bool(tid), r):
        raise Abort()
    call("post", f"/pm/projects/{pid}/tasks/{tid}/status", h, json={"status": "DOING"})
    r = call("post", f"/pm/projects/{pid}/tasks/{tid}/status", h, json={"status": "DONE"})
    chk("M6b 任务可置为 DONE", r.get("code") == 0, r)
    r = call("post", f"/pm/projects/{pid}/tasks/{tid}/status", h, json={"status": "DOING"})
    chk("M6c DONE → DOING 被拒（BR-10 终态不可回退）",
        r.get("code") not in (0, None) and "不允许从 DONE 变更为 DOING" in str(r.get("message")), r)

    # ---- M7 BR-02 负向：已绑仓库的开发项目改回业务项目必须 409
    # 需要本租户存在「未归属任何项目的可用仓库」；没有则记 SKIP（不伪装成 PASS）
    bindable = call("get", "/pm/repos/bindable", h).get("data") or []
    if not bindable:
        print("  SKIP M7 无可用未归属仓库，BR-02 降级判据在本次环境下无法构造")
    else:
        repo_id = bindable[0].get("id")
        r = call("post", "/pm/projects", h, json={
            "projectNo": "PM-DEV-" + stamp, "name": "冒烟-开发项目 " + stamp,
            "projectType": "DEV", "bindRepoId": repo_id})
        dpid = (r.get("data") or {}).get("id")
        if not chk("M7a 开发项目 + 绑定既有仓库创建成功", r.get("code") == 0 and bool(dpid), r):
            pass
        else:
            created.append(dpid)
            r2 = call("put", f"/pm/projects/{dpid}", h, json={"projectType": "BUSINESS"})
            chk("M7b 已绑仓库的开发项目改回业务项目被拒（BR-02, 409）",
                r2.get("code") == 409, r2)

    # ---- M9 数据范围自查：机构管理员必须能看到**本机构直属**（department_id=0）的项目
    # 背景：首版 list 只按「可见部门集合」过滤，而机构直属项目的 department_id=0
    # 不在任何部门集合里 ⇒ 企业管理员建完项目，列表里看不到，但直接开详情又能开
    #（requireVisible 对 ORG_ADMIN 直接放行）—— 自相矛盾。
    # 修复后 list 与 requireVisible 共用 canSee()（按 institutionId 匹配，含 dept-0）。
    # 本组同时守住「不要为了修 M9c 而把范围放宽成所有机构管理员都能看」（M9e 反向守卫）。
    if call("get", "/pm/config", h).get("code") == 0:
        tok2 = login("fagai_admin")           # 企业管理员，机构 1（某某区发展和改革局）
        h2 = {"Authorization": f"Bearer {tok2}"}
        tok3 = login("shenpi_admin")          # 企业管理员，机构 2（某某区行政审批局）
        h3 = {"Authorization": f"Bearer {tok3}"}

        r = call("post", "/pm/projects", h2, json={
            "projectNo": "PM-SCOPE-" + stamp, "name": "冒烟-机构直属项目 " + stamp,
            "projectType": "BUSINESS"})
        spid = (r.get("data") or {}).get("id")
        if not chk("M9a 企业管理员建出项目", r.get("code") == 0 and bool(spid), r):
            raise Abort()
        created.append(spid)

        # M9b 是 M9c 的**前提**：必须确认走的是「机构直属」分支，否则 M9c 可能是在
        # 部门分支上过的，证明不了这次修的代码被走到（铁律 12 的数据侧用法）。
        d = call("get", f"/pm/projects/{spid}", h2).get("data") or {}
        chk("M9b ★前提：该项目确为机构直属（departmentId==0 且 institutionId==本机构）",
            int(d.get("departmentId") or 0) == 0 and int(d.get("institutionId") or 0) == 1,
            "dept=%s inst=%s" % (d.get("departmentId"), d.get("institutionId")))

        names = [x.get("name") for x in (call("get", "/pm/projects", h2).get("data") or [])]
        chk("M9c ★企业管理员的**列表**能看到本项目（首版缺陷：只见部门集合、漏掉机构直属）",
            ("冒烟-机构直属项目 " + stamp) in names, [n for n in names if n and "冒烟" in n])

        chk("M9d 列表与详情口径一致（不再出现「列表看不到、详情开得开」）",
            call("get", f"/pm/projects/{spid}", h2).get("code") == 0)

        names3 = [x.get("name") for x in (call("get", "/pm/projects", h3).get("data") or [])]
        chk("M9e ★反向守卫：另一机构的管理员**看不到**本项目（修复不得放宽成全员可见）",
            ("冒烟-机构直属项目 " + stamp) not in names3, [n for n in names3 if n and "冒烟" in n])

    # ---- M8 自净由 main 的 finally 调用 cleanup() 完成（失败路径同样保证清理）

def main():
    tok = login(USER)
    h = {"Authorization": f"Bearer {tok}"}
    stamp = str(int(time.time()))
    created = []
    try:
        body(h, created, stamp)
    except Abort:
        pass
    finally:
        cleanup(h, created)

    fails = [c for c in RES if not c[1]]
    print("\n=== PM 冒烟 %d/%d 通过 ===" % (len(RES) - len(fails), len(RES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
