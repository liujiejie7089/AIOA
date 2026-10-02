# -*- coding: utf-8 -*-
"""V71 对既有 `gitee_project` 的**零回归哨兵**。

背景（docs/40 §3 的决定）：PM 复用既有的 `gitee_project` 而不是新建映射表，
代价是给这张**老表**加了一列 `pm_project_id` + 一个索引。老表被 V48 的整套
Gitee 联动（建项目→建仓→Webhook→成员同步）读写，因此「加列是否伤到既有读写」
必须有一条常驻断言，而不是只在当次提交里口头说一句「零回归」。

三条断言各自防一种具体缺陷：
  R1 加列不得泄漏到既有接口 —— 若既有代码用 `SELECT *` + 通用 Map 映射，
     新列会混进响应体，前端拿到一个自己不认识、却可能被误用的字段。
  R2 加列不得打断既有 INSERT —— 若存在**不带列名**的位置式写入，
     新列会顶掉最后一列的取值，落库数据静默错位（最难查的一类）。
  R3 新列语义必须自洽 —— 既有 Gitee 建出来的行 `pm_project_id` 必须是 NULL，
     否则一建仓就「看起来已被某个项目绑定」，PM 侧的可绑清单会凭空少一条。

★ 为什么不用 `e2e_v48_gitee.py`：该套件的主操作人 fixture 是**租户 9
  （某某智能科技有限公司）的 `znkjyf_admin`**，而本环境的租户 9 已被移除
  （`sys_tenant` 现存 1/2/3），套件在登录步即中止。此处用租户 2 的账号重建
  最小必要的写入路径，不与 V48 的覆盖范围重复。

★ 前置：后端以 `source scripts/gitee-e2e-env.sh` 启动（Gitee 接口指向本地桩 :8090）。
  前置不满足时记为 SKIP 并返回非 0 —— **不伪装成 PASS**（铁律 7）。

★ 用无 Gitee 绑定的账号（fagai_admin）操作：他不持有真实令牌，
  绑定→建仓→解绑全程不触碰 dsj_admin 的既有真实绑定。

用法：python scripts/_check_gitee_repo_write.py
"""
import sys
import time

import httpx
import pymysql

API = "http://127.0.0.1:8080/api/v1"
STUB = "http://127.0.0.1:8090"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "fagai_admin", "User@123"   # 企业管理员，机构 1 / 部门 11，无 Gitee 绑定
STUB_MARK = "http://127.0.0.1:8090"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", autocommit=True)

C = httpx.Client(timeout=90, trust_env=False)
PASS, FAIL, SKIP = [], [], []


def q(sql, args=None):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.fetchall()
    finally:
        conn.close()


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:300]) if detail else ""))
    return bool(cond)


def skip(cid, why):
    SKIP.append(cid)
    print("  SKIP %s  | %s" % (cid, why))


def login():
    d = C.post(API + "/auth/login", json={"username": USER, "password": PWD,
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit("登录失败 %s: %s" % (USER, d.get("message")))
    return {"Authorization": "Bearer " + d["data"]["accessToken"]}


def main():
    print("=" * 74)
    print("V71 gitee_project 加列零回归哨兵")
    print("=" * 74)

    # ---------- 前置：后端是否可达 ----------
    try:
        C.post(API + "/auth/login", json={"username": USER, "password": PWD,
                                         "tenantName": TENANT}, timeout=5)
    except Exception as e:
        skip("前置", "后端 :8080 不可达：%s" % e)
        print("\nSKIP（无法验证）：%d 项" % len(SKIP))
        return 2

    h = login()
    print("\n[前置] 账号 %s 已登录" % USER)

    # 探针：拿一次 bind 状态，顺便判断当前是否真的接在桩上（错误文案里会带 invalid_grant 等）
    probe = C.post(API + "/gitee/projects", headers=h, json={
        "name": "__probe__" + str(int(time.time())), "visibility": "private"}).json()
    pmsg = str(probe.get("message") or "")
    if "Gitee 授权已失效" in pmsg:
        pass  # 未绑定属预期（本账号本就无绑定），继续走绑定流程
    elif probe.get("code") == 0:
        skip("前置", "探针项目竟然建成功了（账号已有可用绑定？）——请人工确认环境")
        return 2

    print("\n[R1] 既有接口不得因加列而改变字段集合")
    lst = C.get(API + "/gitee/projects", headers=h).json()
    if lst.get("code") != 0:
        skip("R1", "既有列表接口不可用：%s" % lst.get("message"))
        return 2
    data = lst.get("data")
    items = data if isinstance(data, list) else ((data or {}).get("items") or (data or {}).get("records") or [])
    if not items:
        skip("R1", "本租户无存活 gitee_project 行，无法比对字段集合")
    else:
        keys = set(items[0].keys())
        leaked = sorted(k for k in keys if "pmproject" in k.lower() or "pm_project" in k.lower())
        chk("R1.1 既有列表响应的字段集合不含新增的 PM 关联列", not leaked, leaked)
        # 负向对照：人为往 key 集合里塞一个新列名，同一判据必须报红
        fake = keys | {"pmProjectId"}
        fake_leak = sorted(k for k in fake if "pmproject" in k.lower() or "pm_project" in k.lower())
        chk("R1.2 ★判据有效性：把 pmProjectId 混进字段集合时判据必须报红",
            fake_leak == ["pmProjectId"], fake_leak)

    print("\n[R2] 既有 INSERT 路径在加列后仍能落库")
    # 走完整 OAuth 桩流程给本账号建一个绑定（他没绑定过，不破坏任何既有真实绑定）
    au = C.post(API + "/gitee/bind/authorize", headers=h).json()
    if au.get("code") != 0 or not (au.get("data") or {}).get("url"):
        skip("R2", "授权地址生成失败：%s" % au.get("message"))
        print("\nSKIP：%d 项（前置不满足）" % len(SKIP))
        return 2
    url = au["data"]["url"]
    if STUB_MARK not in url:
        skip("R2", "授权地址未指向本地桩（后端未 source gitee-e2e-env.sh），当前=%s" % url[:80])
        print("\nSKIP：%d 项（前置不满足，未伪装成 PASS）" % len(SKIP))
        return 2

    r = C.get(url + "&login=" + USER, follow_redirects=False)
    cb = r.headers.get("location")
    if not cb or "code=" not in cb:
        skip("R2", "桩未回跳带 code 的地址：%s" % r.status_code)
        return 2
    C.get(cb)
    bound = C.get(API + "/gitee/bind", headers=h).json()
    chk("R2.0 授权码绑定成功（后续写入路径的前提）",
        bound.get("code") == 0 and (bound.get("data") or {}).get("bound") is True, bound)

    stamp = str(int(time.time()))
    created = C.post(API + "/gitee/projects", headers=h, json={
        "name": "V71哨兵-既有写入路径 " + stamp,
        "description": "验证 gitee_project 加列后既有 INSERT 仍工作",
        "visibility": "private", "departmentId": 11}).json()
    pid = (created.get("data") or {}).get("id")
    ok_insert = chk("R2.1 ★既有建项目/建仓路径落库成功（加列未打断 INSERT）",
                    created.get("code") == 0 and bool(pid), created)
    if ok_insert:
        row = created["data"]
        chk("R2.2 既有创建响应结构未变（仍是 id/status/repoName/project 信封，且不含 PM 列）",
            isinstance(row.get("project"), dict) and "status" in row
            and not any("pmproject" in k.lower() or "pm_project" in k.lower() for k in row),
            sorted(row.keys()))
        # 「新列顶位」的**权威判据只能回库读**：接口回显字段再多也证明不了落库没串位。
        db = q("SELECT name, repo_name, gitee_owner, visibility, department_id, pm_project_id "
               "FROM gitee_project WHERE id=%s", (pid,))
        chk("R2.3 ★回库逐列核对：既有列取值与提交值一致（新列未顶位）",
            bool(db) and db[0][0] == "V71哨兵-既有写入路径 " + stamp and db[0][4] == 11
            and db[0][3] == "private", db)

        print("\n[R3] 新列语义自洽（既有建仓行不得被误认为已被 PM 项目绑定）")
        pm_col = q("SELECT pm_project_id FROM gitee_project WHERE id=%s", (pid,))
        chk("R3.1 ★回库核对：新建行的 pm_project_id 为 NULL（新列默认语义正确）",
            bool(pm_col) and pm_col[0][0] is None, pm_col)
        # 本行的 status 由异步建仓决定（AIOA_GITEE_SYNC_ENABLED=false 时停在 CREATING），
        # 因此**不得**出现在 PM 可绑清单里 —— PM 只收 ACTIVE 仓库。
        st = q("SELECT status FROM gitee_project WHERE id=%s", (pid,))[0][0]
        bindable = C.get(API + "/pm/repos/bindable", headers=h).json()
        b_ids = [x.get("id") for x in (bindable.get("data") or [])]
        if st == "ACTIVE":
            chk("R3.2 本行已 ACTIVE ⇒ 必须出现在 PM 可绑清单里", pid in b_ids, st)
        else:
            chk("R3.2 本行尚未 ACTIVE（%s，异步建仓未完成）⇒ 不得出现在 PM 可绑清单里" % st,
                pid not in b_ids, "status=%s 可绑=%d" % (st, len(b_ids)))
        # 同源交叉核对：清单条数必须等于库里「ACTIVE 且未归属」的行数 ——
        # 任一方向的过滤写错（多给一个已绑的 / 少给一个可绑的）都会在这里显形。
        db_cnt = q("SELECT COUNT(*) FROM gitee_project "
                   "WHERE tenant_id=%s AND status='ACTIVE' AND pm_project_id IS NULL "
                   "AND deleted_at IS NULL", (2,))[0][0]
        chk("R3.3 ★同源交叉：PM 可绑清单条数与库里「ACTIVE 且 pm_project_id IS NULL」行数一致",
            len(b_ids) == db_cnt, "api=%d db=%d" % (len(b_ids), db_cnt))

        # ---------- 自净 ----------
        print("\n[Z] 自净")
        d1 = C.delete(API + "/gitee/projects/%s" % pid, headers=h, params={"purgeRepo": "false"})
        chk("Z1 哨兵项目已软删", d1.json().get("code") == 0, d1.text[:160])
    else:
        skip("R3", "R2.1 未通过，新列语义无从验证")

    d2 = C.delete(API + "/gitee/bind", headers=h)
    chk("Z2 哨兵绑定已解绑（gitee_account 行退回软删，退出业务可见面）",
        d2.json().get("code") == 0, d2.text[:160])
    # 注：本脚本会在 gitee_task（异步 outbox，**追加型事件日志**）留下 2 条
    #     CREATE_REPO / FAILED 行 —— 与建项目必入队的设计一致。该表已有数千条历史行
    #     （DONE+FAILED），属正常留痕，**不清理**（清理追加型日志比留痕更危险）。

    print("\n=== gitee_project 加列零回归：%d PASS / %d FAIL / %d SKIP ==="
          % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败项：%s" % FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
