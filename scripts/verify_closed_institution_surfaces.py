# -*- coding: utf-8 -*-
"""「已注销机构退出运营面」端到端验收：机构管理 / 入驻进度 / 资源授权 / 人员归属 + 人员筛选。

用户报障原文（2026-09-29）：
  「我以企业管理员注销了机构，但人员管理，机构管理，入驻进度，资源授权都还能看到，
    注销后所有相关的都要删除；申请删除提示机构不存在或已注销 162；
    人员管理要提供筛选功能，不要全部排成一列；菜单中'组织与员工'的二级菜单不需要。」

落地口径（写清楚，后人别再走回头路）：
  · **注销（CLOSED）= 不可逆的法人档案终态**，它退出**全部运营面**，但档案行**不删除**。
    清理只有「删租户」的级联一条路（`_check_delete_guards.py` 的 D13/D15 已钉死）。
    所以本套件验的是「运营面默认看不见 + 档案显式可取」，**不是**「CLOSED 变可删/可达」。
  · 「申请删除已注销机构」必然 404 是**设计**（作用域解析对非 ACTIVE 机构一律 404），
    前端据此禁用入口；本套件把这条**设计不变量**也钉住（C11），免得后人「顺手修好它」。

★ 本套件最容易被写成恒真的两处 —— 都在这里用「构造探针」堵住了（铁律 #7/#12）：
  1) 资源授权 / 人员归属：**本库现有的 CLOSED 机构上恰好没有可观测的授权或存活成员**
     （实测：CLOSED 机构上的 56 条成员行其 user 全已不存在；唯一挂在 CLOSED 机构上的
      2 条授权属已软删的租户 30）。若只写「授权里没有 CLOSED 机构」——**改前改后都绿**。
     故 C7/C8 先往库里**构造**一条夹具，断言接口把它挡住，再从库里确认夹具**确实存在**
     （证明是「被过滤」而不是「本来就没有」），最后清理。夹具带唯一标记，收尾幂等。
  2) 机构清单 / 入驻进度：「运营面没有 CLOSED」只有在档案里**确实有 CLOSED** 时才有意义。
     故 C1 先断言档案非空，C3 再断言「默认 + 档案 = 全量」证明默认只是摘掉 CLOSED。

用法：python scripts/e2e_closed_institution_surfaces.py
"""
import os
import sys
import traceback

import httpx
import pymysql

BASE = os.environ.get("AIOA_BASE", "http://127.0.0.1:8080")
PWD_TENANT = "User@123"
PWD_PLATFORM = "Admin@123"
T2 = 2                       # DSJ-DEMO 租户：25 个 CLOSED + 6 个在册机构（CLOSED 面最厚）
TENANT_ADMIN = "dsj_admin"   # 该租户的租户管理员
MEMBER_PROBE_USER = 3        # dsj_admin 的 user_id：**当前没有任何 member 行**（可观测探针的首选）
GRANT_MARK = "E2E_CLOSED_PROBE"      # 夹具唯一标记（清理按标记，幂等）
MEMBER_MARK = "E2E已注销机构成员探针"

PASS, FAIL, SKIP = [], [], []
# 负向自检开关：开启后把「修前的响应形态」注入回来，验证核心断言**确实会报红**。
# 这不是「为了让它红而放宽」，恰恰相反 —— 它证明这些断言不是恒真断言（铁律 #7/#12）。
SELFTEST = False


def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  " + str(detail)) if (detail and not cond) else ""))


def skip(name, why):
    SKIP.append(name)
    print("  [skip] " + name + " —— " + why)


def call(method, path, token=None, body=None, params=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    try:
        r = httpx.request(method, BASE + path, headers=h, json=body, params=params, timeout=30)
    except Exception as e:  # noqa: BLE001
        return 0, {"_err": str(e)}
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, None


def code_of(js):
    return js.get("code") if isinstance(js, dict) else None


def data_of(js):
    return js.get("data") if isinstance(js, dict) else None


def msg_of(js):
    return (js or {}).get("message") if isinstance(js, dict) else None


def login(username, password):
    st, js = call("POST", "/api/v1/auth/login", body={"username": username, "password": password})
    if code_of(js) == 0:
        return (data_of(js) or {}).get("accessToken")
    return None


CONN = None


def conn():
    global CONN
    if CONN is None:
        CONN = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                               database="aioa", charset="utf8mb4", autocommit=True,
                               cursorclass=pymysql.cursors.DictCursor)
    return CONN


def db(sql, args=None):
    with conn().cursor() as cur:
        cur.execute(sql, args or ())
        if cur.description:
            return cur.fetchall()
        return []


def one(sql, args=None):
    rows = db(sql, args)
    return rows[0] if rows else None


def institutions(token, **params):
    if SELFTEST and not params:
        # 负向自检：模拟**修前**的默认口径（默认也把 CLOSED 一起返回）。
        params = {"includeClosed": "true"}
    st, js = call("GET", "/api/v1/tenant/institutions", token, params=params or None)
    return st, js, (data_of(js) if isinstance(data_of(js), list) else [])


def personnel(token, **params):
    if SELFTEST and "institutionId" in params:
        # 负向自检：模拟**服务端忽略机构筛选**（筛选形同虚设）。
        params.pop("institutionId")
    st, js = call("GET", "/api/v1/admin/personnel", token, params=params or None)
    return st, js, (data_of(js) or {})


def flat_members(pv):
    return [m for g in (pv.get("groups") or []) for m in (g.get("members") or [])]


def norm_inst(iid):
    """机构 id 归一化：`未归属机构` 在列表行里是 null/0，在下拉选项里是字符串 '0'
    （后端 `institutionId=0` 即此义）。不归一化就会出现「列表 None vs 选项 '0'」的假失败。"""
    return "0" if iid in (None, 0) else str(iid)


# ============================================================ C 组：运营面可见性（真实数据）
def group_surfaces(token):
    print("\n=== C 组：已注销机构退出运营面（真实数据，只读） ===")

    st, js, all_rows = institutions(token, includeClosed="true")
    closed = [r for r in all_rows if r.get("status") == "CLOSED"]
    closed_ids = {r.get("id") for r in closed}
    chk("C1 ★ 前提：档案视角（includeClosed=true）里确实有已注销机构（否则后面全是恒真）",
        code_of(js) == 0 and len(closed) >= 1,
        "http=%s code=%s 全量=%d CLOSED=%d msg=%s" % (st, code_of(js), len(all_rows),
                                                      len(closed), msg_of(js)))
    if not closed_ids:
        print("   !! 档案为空，后续可见性断言无法成立，提前结束 C 组")
        return closed_ids

    st, js, ops = institutions(token)
    ops_closed = [r for r in ops if r.get("status") == "CLOSED"]
    chk("C2 ★★ 机构管理：默认真实清单里**一行已注销都没有**，且与档案 id 集**无交集**",
        code_of(js) == 0 and not ops_closed
        and not ({r.get("id") for r in ops} & closed_ids),
        "http=%s code=%s 默认行数=%d CLOSED=%d 交集=%s"
        % (st, code_of(js), len(ops), len(ops_closed),
           sorted({r.get("id") for r in ops} & closed_ids)))

    chk("C3 ★ 口径自洽：默认行数 + 档案 CLOSED 行数 == 全量行数"
        "（证明默认只是「摘掉 CLOSED」，没顺手漏掉别的）",
        len(ops) + len(closed) == len(all_rows),
        "默认=%d + CLOSED=%d != 全量=%d" % (len(ops), len(closed), len(all_rows)))

    # 显式 status=CLOSED：档案必须取得到（数据没被删，只是默认不展示）
    st, js, by_status = institutions(token, status="CLOSED")
    chk("C5 ★ 显式 status=CLOSED 仍能取到档案（注销只是「退出运营面」，不是「数据消失」）",
        code_of(js) == 0 and len(by_status) == len(closed)
        and all(r.get("status") == "CLOSED" for r in by_status),
        "http=%s code=%s 行数=%d（档案 %d）msg=%s"
        % (st, code_of(js), len(by_status), len(closed), msg_of(js)))

    # 显式 includeClosed=false：默认口径不得被显式传参绕开
    st, js, ef = institutions(token, includeClosed="false")
    chk("C6 显式 includeClosed=false 与默认同口径（显式传 false 不会反把档案放出来）",
        code_of(js) == 0 and not [r for r in ef if r.get("status") == "CLOSED"],
        "http=%s code=%s CLOSED=%d"
        % (st, code_of(js), len([r for r in ef if r.get("status") == "CLOSED"])))

    # 入驻进度
    st, js = call("GET", "/api/v1/tenant/onboarding", token)
    d = data_of(js) or {}
    ob_insts = d.get("institutions") if isinstance(d, dict) else None
    ob_insts = ob_insts if isinstance(ob_insts, list) else []
    ob_closed = [r for r in ob_insts if r.get("status") == "CLOSED"]
    chk("C4 ★★ 入驻进度：已注销机构不计入总览，且机构数与机构管理默认口径一致",
        code_of(js) == 0 and not ob_closed and len(ob_insts) == len(ops),
        "http=%s code=%s 总览机构=%d CLOSED=%d（机构管理默认=%d）msg=%s"
        % (st, code_of(js), len(ob_insts), len(ob_closed), len(ops), msg_of(js)))

    # 资源授权（真实数据下可能为空 ⇒ 显式报出「本轮不可证」，由 C7 构造夹具补上）
    st, js = call("GET", "/api/v1/tenant/grants", token)
    grants = data_of(js) if isinstance(data_of(js), list) else []
    leak = [g for g in grants if g.get("institutionId") in closed_ids]
    chk("C9 资源授权：真实清单里没有归属已注销机构的授权",
        code_of(js) == 0 and not leak,
        "http=%s code=%s 授权=%d 归属CLOSED=%d" % (st, code_of(js), len(grants), len(leak)))
    if not any(g.get("institutionId") in closed_ids for g in grants):
        skip("C9 的「有效性」", "真实数据里本就没有归属 CLOSED 机构的授权 ⇒ 本断言偏弱；由 C7 构造夹具补")

    return closed_ids


# ============================================================ C7：授权面构造探针（A/B 对照）
def pick_live_inst():
    """挑一个「在本册且成员最少」的机构做 A/B 对照的 live 侧（尽量不打扰真实演示数据）。"""
    r = one("""SELECT i.id FROM org_institution i
               WHERE i.tenant_id=%s AND i.deleted_at IS NULL
                 AND (i.status IS NULL OR i.status<>'CLOSED')
               ORDER BY (SELECT COUNT(*) FROM org_member m
                          WHERE m.institution_id=i.id AND m.deleted_at IS NULL) ASC, i.id ASC
               LIMIT 1""", (T2,))
    return r["id"] if r else None


def insert_grant(inst, res_id, res_key):
    with conn().cursor() as cur:
        cur.execute(
            "INSERT INTO resource_grant (tenant_id, institution_id, res_type, res_id, res_key,"
            " res_name, enabled, granted_by, granted_at, created_at)"
            " VALUES (%s,%s,'MODEL',%s,%s,'已注销机构授权夹具',1,1,NOW(6),NOW(6))",
            (T2, inst, res_id, res_key))
        return cur.lastrowid


def group_grant_probe(token, closed_ids):
    """A/B 对照：**同一种夹具**分别挂在一个在册机构与一个已注销机构上。
    在册的那条必须出现在清单里（证明夹具格式/查询面是通的），已注销的那条必须消失
    —— 两者只差「机构是否已注销」，于是「消失」只能归因于运营面过滤（铁证，非恒真）。"""
    print("\n=== C7：资源授权面构造探针（A/B 对照：同夹具挂在册 vs 已注销） ===")
    live = pick_live_inst()
    if not closed_ids or live is None:
        skip("C7 授权构造探针", "缺在册机构（live=%s）或无 CLOSED 机构" % live)
        return
    inst_closed = sorted(closed_ids)[0]
    id_live = id_closed = None
    try:
        id_live = insert_grant(live, 999902, GRANT_MARK + "_LIVE")
        id_closed = insert_grant(inst_closed, 999901, GRANT_MARK + "_CLOSED")
        f_live = one("SELECT id, institution_id FROM resource_grant WHERE id=%s", (id_live,))
        f_closed = one("SELECT id, institution_id FROM resource_grant WHERE id=%s", (id_closed,))
        chk("C7a 两条夹具均已落库（在册 %s / 已注销 %s）—— 证明下面挡的是真数据，"
            "不是「本来就没有」" % (live, inst_closed),
            bool(f_live) and bool(f_closed) and f_live["institution_id"] == live
            and f_closed["institution_id"] == inst_closed,
            "live=%s closed=%s" % (f_live, f_closed))

        st, js = call("GET", "/api/v1/tenant/grants", token)
        grants = data_of(js) if isinstance(data_of(js), list) else []
        keys = {g.get("resKey") for g in grants}
        chk("C7b ★★ 对照：挂在**在册**机构上的夹具出现在清单里（证明查询面通、夹具格式正确）",
            code_of(js) == 0 and (GRANT_MARK + "_LIVE") in keys,
            "http=%s code=%s 未命中 live 夹具；清单 resKey=%s msg=%s"
            % (st, code_of(js), sorted(k for k in keys if k), msg_of(js)))

        chk("C7c ★★★ 挂在**已注销**机构上的同款夹具**完全消失**（唯二差异是机构状态 ⇒ 归因确定）",
            code_of(js) == 0 and (GRANT_MARK + "_CLOSED") not in keys
            and not [g for g in grants if g.get("institutionId") == inst_closed],
            "http=%s code=%s 命中 CLOSED 夹具=%s msg=%s"
            % (st, code_of(js), [g for g in grants if g.get("institutionId") == inst_closed],
               msg_of(js)))

        st, js = call("GET", "/api/v1/tenant/grants", token, params={"institutionId": inst_closed})
        g2 = data_of(js) if isinstance(data_of(js), list) else []
        chk("C7d ★ 显式按该已注销机构查授权也必须为空（不能靠「不传参」绕过）",
            code_of(js) == 0 and not g2,
            "http=%s code=%s 行数=%d msg=%s" % (st, code_of(js), len(g2), msg_of(js)))
    finally:
        try:
            for i in (id_live, id_closed):
                if i is not None:
                    db("DELETE FROM resource_grant WHERE id=%s", (i,))
            db("DELETE FROM resource_grant WHERE res_key LIKE %s", (GRANT_MARK + "%",))
            left = one("SELECT COUNT(*) AS c FROM resource_grant WHERE res_key LIKE %s",
                       (GRANT_MARK + "%",))
            chk("C7e 两条夹具均已清理（不残留进业务面）", (left or {}).get("c") == 0,
                "残留=%s" % left)
        except Exception as e:  # noqa: BLE001
            chk("C7e 两条夹具均已清理（不残留进业务面）", False, "清理异常：%s" % e)


# ============================================================ C8：人员归属构造探针（A/B 对照）
def insert_member(inst):
    with conn().cursor() as cur:
        cur.execute(
            "INSERT INTO org_member (tenant_id, institution_id, department_id, user_id, name,"
            " job_title, is_primary, is_org_admin, status, created_at)"
            " VALUES (%s,%s,0,%s,%s,'夹具',1,0,'ACTIVE',NOW(6))",
            (T2, inst, MEMBER_PROBE_USER, MEMBER_MARK))
        return cur.lastrowid


def group_member_probe(token, closed_ids):
    """A/B 对照：同一个「没有成员行」的账号，先挂到**在册**机构（应被归属），
    再改挂到**已注销**机构（应不被归属）。两次只差机构状态 ⇒ 归因确定。"""
    print("\n=== C8：人员归属构造探针（A/B 对照：同账号挂在册 vs 已注销） ===")
    live = pick_live_inst()
    if not closed_ids or live is None:
        skip("C8 人员构造探针", "缺在册机构（live=%s）或无 CLOSED 机构" % live)
        return
    inst_closed = sorted(closed_ids)[0]
    inst_name = (one("SELECT name FROM org_institution WHERE id=%s", (inst_closed,)) or {}).get("name") or ""
    pre = one("SELECT COUNT(*) AS c FROM org_member WHERE user_id=%s AND deleted_at IS NULL",
              (MEMBER_PROBE_USER,))
    if (pre or {}).get("c"):
        skip("C8 人员构造探针", "探测账号 %s 已有成员行，无法构造「只挂一个机构」的对照"
             % MEMBER_PROBE_USER)
        return

    mid = None
    try:
        # ---- 对照侧 A：挂在**在册**机构 ⇒ 必须出现在人员列表且被归属到它
        mid = insert_member(live)
        st, js, pv = personnel(token)
        me = [m for m in flat_members(pv) if m.get("id") == MEMBER_PROBE_USER]
        chk("C8a ★★ 对照：挂在**在册**机构上的夹具行**被归属**（证明这条链路是通的）",
            code_of(js) == 0 and me and me[0].get("institutionId") == live,
            "http=%s code=%s 该账号归属=%s（期望 %s）msg=%s"
            % (st, code_of(js), [m.get("institutionId") for m in me], live, msg_of(js)))
        db("DELETE FROM org_member WHERE id=%s", (mid,))
        mid = None

        # ---- 对照侧 B：改挂**已注销**机构 ⇒ 必须不被归属，且机构名不得出现
        mid = insert_member(inst_closed)
        fixture = one("SELECT id, institution_id, status FROM org_member WHERE id=%s", (mid,))
        chk("C8b 已注销侧夹具已落库（ACTIVE、挂在 CLOSED 机构上）—— 证明挡的是真数据",
            bool(fixture) and fixture["institution_id"] == inst_closed
            and fixture["status"] == "ACTIVE",
            "fixture=%s inst=%s" % (fixture, inst_closed))

        st, js, pv2 = personnel(token)
        members = flat_members(pv2)
        me2 = [m for m in members if m.get("id") == MEMBER_PROBE_USER]
        any_closed = [m for m in members if m.get("institutionId") in closed_ids]
        chk("C8c ★★★ 同一账号改挂**已注销**机构后**不再被归属**，且没有任何成员被挂到 CLOSED 机构",
            code_of(js) == 0 and not [m for m in me2 if m.get("institutionId") == inst_closed]
            and not any_closed,
            "http=%s code=%s 该账号归属=%s 任何归属CLOSED=%s msg=%s"
            % (st, code_of(js), [m.get("institutionId") for m in me2],
               [m.get("institutionId") for m in any_closed], msg_of(js)))

        names = {m.get("institutionName") for m in members}
        chk("C8d ★★ 列表里不出现该已注销机构的名称（渲染层也拿不到它）",
            inst_name not in names,
            "机构名「%s」出现在列表机构名集合里：%s" % (inst_name, sorted(x for x in names if x)))
    finally:
        try:
            if mid is not None:
                db("DELETE FROM org_member WHERE id=%s", (mid,))
            db("DELETE FROM org_member WHERE name=%s", (MEMBER_MARK,))
            left = one("SELECT COUNT(*) AS c FROM org_member WHERE name=%s", (MEMBER_MARK,))
            chk("C8e 夹具已清理（不残留进业务面）", (left or {}).get("c") == 0, "残留=%s" % left)
        except Exception as e:  # noqa: BLE001
            chk("C8e 夹具已清理（不残留进业务面）", False, "清理异常：%s" % e)


# ============================================================ C10：申请删除（设计不变量）
def group_delete_invariant(token, closed_ids):
    print("\n=== C10：已注销机构不可直删（作用域解析一律 404）—— 设计不变量，别「顺手修好」 ===")
    if not closed_ids:
        skip("C10 申请删除不变量", "无 CLOSED 机构可试")
        return
    inst = sorted(closed_ids)[0]
    st, js = call("POST", "/api/v1/org/institutions/%s/delete-request" % inst, token,
                  body={"reason": "套件探针"}, params={"institutionId": inst})
    row = one("SELECT id, status, deleted_at FROM org_institution WHERE id=%s", (inst,))
    chk("C10a ★ 对已注销机构发起「申请删除」必须失败（前端据此禁用入口），"
        "且机构行仍在（不得被误删）",
        code_of(js) != 0 and row is not None and row["status"] == "CLOSED",
        "http=%s code=%s msg=%s row=%s" % (st, code_of(js), msg_of(js), row))


# ============================================================ F 组：人员筛选
def group_filters(token):
    print("\n=== F 组：人员管理筛选（服务端生效，选项与列表同源） ===")
    st, js, base = personnel(token)
    t0 = base.get("total")
    chk("F0 人员列表可读，返回 filterOptions / filters（前端据此渲染筛选项）",
        code_of(js) == 0 and isinstance(base.get("filterOptions"), dict)
        and isinstance(base.get("filters"), dict),
        "http=%s code=%s keys=%s msg=%s"
        % (st, code_of(js), sorted(base.keys()) if isinstance(base, dict) else None, msg_of(js)))

    fo = base.get("filterOptions") or {}
    insts = fo.get("institutions") or []
    chk("F1 机构下拉选项**与列表同源**（列表里出现的每个机构都有对应选项，且选项非自建枚举）",
        len(insts) >= 1,
        "选项=%s" % insts)

    members = flat_members(base)
    listed_ids = {norm_inst(m.get("institutionId")) for m in members}
    opt_vals = {str(o.get("value")) for o in insts}
    chk("F2 ★ 下拉选项覆盖列表里出现的全部机构（含「未归属机构」= 选项值 0，否则筛选器会漏项）",
        listed_ids <= opt_vals,
        "列表机构=%s 下拉=%s 缺=%s" % (sorted(listed_ids), sorted(opt_vals),
                                       sorted(listed_ids - opt_vals)))

    # 按机构筛
    if insts:
        pick = insts[0]["value"]
        st, js, f = personnel(token, institutionId=pick)
        fm = flat_members(f)
        got = {norm_inst(m.get("institutionId")) for m in fm}
        chk("F3 ★★ 按机构筛选：结果只含该机构（服务端过滤真生效）",
            code_of(js) == 0 and fm and got <= {str(pick)},
            "institutionId=%s total=%s 命中机构=%s" % (pick, f.get("total"), sorted(got)))

        st, js, z = personnel(token, institutionId=0)
        zm = flat_members(z)
        chk("F4 「未归属机构」(institutionId=0) 只返回 institutionId 为空的行",
            code_of(js) == 0 and all(m.get("institutionId") in (None, 0) for m in zm),
            # 归一化后排序：混合 None/int 直接 sorted 会 TypeError（负向自检时踩到过）
            "total=%s 归属=%s" % (z.get("total"),
                                  sorted({norm_inst(m.get("institutionId")) for m in zm})))

    # 按档位筛
    classes = fo.get("classes") or []
    if classes:
        pick_c = classes[-1]["value"]     # 末位通常是 MEMBER
        st, js, f = personnel(token, scopeClass=pick_c)
        fm = flat_members(f)
        chk("F5 ★★ 按档位筛选：结果档位全部等于所选项，且与 classCounts 自洽",
            code_of(js) == 0 and all(m.get("scopeClass") == pick_c for m in fm)
            and (f.get("classCounts") or {}).get(pick_c) == len(fm),
            "scopeClass=%s 成员=%d classCounts=%s" % (pick_c, len(fm), f.get("classCounts")))

    # 按状态筛
    sts = fo.get("statuses") or []
    if sts:
        pick_s = sts[0]["value"]
        st, js, f = personnel(token, status=pick_s)
        fm = flat_members(f)
        chk("F6 ★ 按账号状态筛选：结果状态全部等于所选项",
            code_of(js) == 0 and all(m.get("status") == pick_s for m in fm),
            "status=%s 命中=%s" % (pick_s, sorted({m.get("status") for m in fm})))
    else:
        skip("F6 按状态筛选", "作用域内无状态选项（全部同状态）")

    # 筛选不扩大可见面：传越界机构 id
    st, js, out = personnel(token, institutionId=999999)
    chk("F7 ★ 传一个不在作用域内的机构 id：空表（筛选**不能**扩大可见面）",
        code_of(js) == 0 and (out.get("total") or 0) == 0,
        "total=%s msg=%s" % (out.get("total"), msg_of(js)))

    chk("F8 基线总数可复现（无筛选时不因筛选而改变）",
        (personnel(token)[2].get("total") == t0),
        "t0=%s now=%s" % (t0, personnel(token)[2].get("total")))


def selftest():
    """负向自检：注入「修前口径」（默认口径含 CLOSED + 服务端忽略机构筛选），
    断言本套件的核心断言**真的会报红**。

    为什么必须有：本套件最容易变成一组恒真断言 —— 机构管理/入驻/授权/人员四个面
    在「修前」也可能恰好没有 CLOSED 数据（授权/人员两个面**实测就是**）。所以
    「改完是绿的」本身不构成证据；只有「改回修前口径会红」才是。
    """
    global SELFTEST
    SELFTEST = True
    token = login(TENANT_ADMIN, PWD_TENANT)
    if not token:
        print("!! 登录失败（%s）" % TENANT_ADMIN)
        return 2
    group_surfaces(token)
    group_filters(token)
    fired = {n.split()[0] for n in FAIL}
    # expect = 「修前口径下**必须**报红」的断言集（漏收了哪项，就等于漏掉一项未验证的非真空性）。
    expect = {"C2", "C3", "C4", "F3", "F4", "F7"}
    # extra = 报红但未列入 expect 的项：不是失败（多验证到一项非真空性是好事），
    #         但必须显式打印 —— 否则「预期集漏项」会被悄悄吞掉（本轮 F4 即如此）。
    miss = sorted(expect - fired)
    extra = sorted(fired - expect)
    print("\n=== 负向自检：注入「修前口径」后真的报红的断言 = %s ===" % sorted(fired))
    if extra:
        print("   （额外报红、未列入预期集，非失败；建议补进 expect）：%s" % extra)
    if miss:
        print("!! 注入后仍未报红（说明是恒真断言，必须修）：%s" % miss)
        return 1
    print("=== 负向自检通过：预期 %d/%d 项全部真的报红（断言有效） ==="
          % (len(expect - set(miss)), len(expect)))
    return 0


def main():
    token = login(TENANT_ADMIN, PWD_TENANT)
    if not token:
        print("!! 登录失败（%s）" % TENANT_ADMIN)
        return 2
    closed_ids = group_surfaces(token)
    group_grant_probe(token, closed_ids)
    group_member_probe(token, closed_ids)
    group_delete_invariant(token, closed_ids)
    group_filters(token)

    print("\n=== 结果：通过 %d / 失败 %d / 跳过 %d ===" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    try:
        if "--selftest" in sys.argv:
            sys.exit(selftest())
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
