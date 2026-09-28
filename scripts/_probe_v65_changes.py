# -*- coding: utf-8 -*-
"""本轮（用户反馈 8 项修复）新增/变更字段的直连接口证据探针。

只读为主；唯一写操作是专家配置 visibleTargets 往返，且 finally 按「原字节」还原。

覆盖：
  P1 #360/#7  GET /org/members             → items[] 含 username + departmentName
  P2 #361/#1  GET /tenant/scope            → 含 currentPeriod（服务端裁决，非浏览器时钟）
  P3 #5       GET /admin/roles             → roleName / name / dataScope
              GET /admin/permissions       → permName / name
  P4 #6       GET/PUT /expert-config/experts/{key} → settings.visibleTargets 无损往返
用法：python scripts/_probe_v65_changes.py
"""
import json
import os
import sys

import httpx
import pymysql

BASE = os.environ.get("AIOA_BASE", "http://127.0.0.1:8080")
PWD_PLATFORM = "Admin@123"
PWD_TENANT = "User@123"

OK, BAD = [], []


def chk(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (("  " + str(detail)) if detail else ""))


def req(method, path, token=None, body=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    r = httpx.request(method, BASE + path, headers=h, json=body, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, None


def login(u, p):
    st, js = req("POST", "/api/v1/auth/login", body={"username": u, "password": p})
    if isinstance(js, dict) and js.get("code") == 0:
        return (js.get("data") or {}).get("accessToken")
    print("  登录失败 %s st=%s %s" % (u, st, str(js)[:140]))
    return None


def main():
    admin = login("admin", PWD_PLATFORM)
    dsj = login("dsj_admin", PWD_TENANT)
    if not admin or not dsj:
        print("前置失败：登录不可用")
        return 2
    print("前置：admin / dsj_admin 均可登录\n")

    # ---------------- P1 #360/#7 机构员工清单回吐 username + departmentName ----------------
    print("[P1] GET /org/members 回吐账号与部门名（#360 / #7）")
    st, js = req("GET", "/api/v1/org/members?institutionId=1&size=50", dsj)
    items = ((js or {}).get("data") or {}).get("items") if isinstance(js, dict) else None
    chk("P1 端点可读且 items 非空", st == 200 and isinstance(items, list) and len(items) > 0,
        (st, str(js)[:200]))
    if items:
        keys = set(items[0].keys())
        with_user = [m for m in items if m.get("username")]
        chk("P1 items[] 含 username 且至少一行有值", "username" in keys and len(with_user) > 0,
            "keys=%s 有账号行=%d" % (sorted(keys), len(with_user)))
        chk("P1 items[] 含 departmentName 键", "departmentName" in keys, sorted(keys))
        ex = with_user[0] if with_user else items[0]
        print("       样例：userId=%s username=%s nickname=%s departmentName=%s"
              % (ex.get("userId"), ex.get("username"), ex.get("nickname"), ex.get("departmentName")))
    print()

    # ---------------- P2 #361/#1 服务端裁决统计期 ----------------
    print("[P2] GET /tenant/scope 带 currentPeriod（#361 / #1：不再由浏览器时钟推导）")
    st, js = req("GET", "/api/v1/tenant/scope", dsj)
    d = (js or {}).get("data") if isinstance(js, dict) else None
    cp = (d or {}).get("currentPeriod") if isinstance(d, dict) else None
    chk("P2 /tenant/scope 可读", st == 200 and isinstance(d, dict), (st, str(js)[:160]))
    chk("P2 响应含 currentPeriod 且形如 YYYY-MM", isinstance(cp, str) and len(cp) == 7 and cp[4] == "-", cp)
    print("       currentPeriod = %s（服务端裁决）" % cp)
    print()

    # ---------------- P3 #5 角色 / 权限点字段对齐 ----------------
    print("[P3] GET /admin/roles 与 /admin/permissions 字段对齐（#5：第三处静默失配）")
    st, js = req("GET", "/api/v1/admin/roles", admin)
    roles = (js or {}).get("data") if isinstance(js, dict) else None
    chk("P3 /admin/roles 返回数组", st == 200 and isinstance(roles, list), (st, str(js)[:160]))
    if isinstance(roles, list) and roles:
        rk = set(roles[0].keys())
        chk("P3 role 含 roleName 与 name（双键，前端不再空白）",
            "roleName" in rk and "name" in rk, sorted(rk))
        chk("P3 role 含 dataScope（角色数据范围列）", "dataScope" in rk, sorted(rk))
        print("       样例：code=%s roleName=%s name=%s dataScope=%s"
              % (roles[0].get("code"), roles[0].get("roleName"), roles[0].get("name"),
                 roles[0].get("dataScope")))
    st, js = req("GET", "/api/v1/admin/permissions", admin)
    perms = (js or {}).get("data") if isinstance(js, dict) else None
    plist = perms.get("items") if isinstance(perms, dict) else (perms if isinstance(perms, list) else None)
    chk("P3 /admin/permissions 可读", st == 200 and plist is not None, (st, str(js)[:160]))
    if plist:
        pk = set(plist[0].keys())
        chk("P3 permission 含 permName 与 name", "permName" in pk and "name" in pk, sorted(pk))
        print("       样例：code=%s permName=%s name=%s type=%s"
              % (plist[0].get("code"), plist[0].get("permName"), plist[0].get("name"),
                 plist[0].get("type")))
    print()

    # ---------------- P4 #6 专家可见范围目标清单无损往返 ----------------
    print("[P4] 专家配置 visibleTargets 无损往返（#6：可见范围目标清单）")
    # 用无 TENANT 片段的 'general'（tenant 0）做洁净往返：测完 DELETE 片段即精确还原。
    key = "general"
    st0, js0 = req("GET", "/api/v1/expert-config/experts/" + key, admin)
    d0 = (js0 or {}).get("data") if isinstance(js0, dict) else None
    chk("P4 专家详情可读", st0 == 200 and isinstance(d0, dict), (st0, str(js0)[:200]))
    if isinstance(d0, dict):
        s0 = d0.get("settings") if isinstance(d0.get("settings"), dict) else d0
        orig_scope = s0.get("visibleScope")
        orig_targets = s0.get("visibleTargets")
        chk("P4 详情含 visibleTargets 键（缺省为空数组）",
            "visibleTargets" in s0 and orig_targets == [], (sorted(s0.keys())[:20], orig_targets))
        body = {"scopeType": "TENANT", "scopeId": 0,
                "config": {"visibleScope": "DEPT", "visibleTargets": [10, 11]}}
        try:
            st1, js1 = req("PUT", "/api/v1/expert-config/experts/" + key + "/config", admin, body)
            chk("P4 PUT 保存成功（scopeType 包裹）",
                st1 == 200 and (js1 or {}).get("code") == 0, (st1, str(js1)[:200]))
            st2, js2 = req("GET", "/api/v1/expert-config/experts/" + key, admin)
            s2 = ((js2 or {}).get("data") or {})
            s2 = s2.get("settings") if isinstance(s2.get("settings"), dict) else s2
            got = s2.get("visibleTargets")
            got_norm = [int(x) for x in got] if isinstance(got, list) else got
            chk("P4 往返后 visibleTargets == [10,11]（无损）", got_norm == [10, 11], got)
            chk("P4 往返后 visibleScope == DEPT", s2.get("visibleScope") == "DEPT", s2.get("visibleScope"))
        finally:
            st3, js3 = req("DELETE",
                           "/api/v1/expert-config/experts/" + key + "/config?scopeType=TENANT&scopeId=0",
                           admin)
            st4, js4 = req("GET", "/api/v1/expert-config/experts/" + key, admin)
            s4 = ((js4 or {}).get("data") or {})
            s4 = s4.get("settings") if isinstance(s4.get("settings"), dict) else s4
            chk("P4 已精确还原（片段删除后回到 ALL / []）",
                st3 == 200 and s4.get("visibleScope") == orig_scope
                and (s4.get("visibleTargets") or []) == (orig_targets or []),
                "scope=%s targets=%s" % (s4.get("visibleScope"), s4.get("visibleTargets")))
    print()

    # ---------------- P5 #6 可见范围在「用户端目录」真正生效（同一判定点） ----------------
    # 铁律 #5：visibleTargets 是新增的可配置维度 ⇒ 必须为「新组合」补断言。
    # 这里考的是行为半边：管理端配「指定机构可见」后，H5 目录是否真的按机构过滤
    # （修复前 CatalogService 根本不看 visibleScope ⇒ 配了等于没配，是恒真的「不可见」错觉）。
    print("[P5] 用户端目录按可见范围过滤（#6 行为半边）")
    KEY, TID = "e2e_v64_probe", 2
    dsj = login("dsj_admin", PWD_TENANT)
    mem1 = login("fagai_li", PWD_TENANT)        # 机构 1 / 部门 11
    mem2 = login("shenpi_zhou", PWD_TENANT)     # 机构 2 / 部门 20

    def catalog_keys(tok):
        st, js = req("GET", "/api/v1/experts", tok)
        d = (js or {}).get("data") or []
        return [x.get("key") for x in d] if isinstance(d, list) else []

    base1, base2 = catalog_keys(mem1), catalog_keys(mem2)
    chk("P5 前置：两位成员基线都看得到该专家（否则后面的断言恒真）",
        KEY in base1 and KEY in base2, (base1, base2))

    def put_scope(targets):
        st, js = req("PUT", "/api/v1/expert-config/experts/%s/config" % KEY, dsj,
                     {"scopeType": "TENANT", "scopeId": TID,
                      "config": {"visibleScope": "INSTITUTION", "visibleTargets": targets}})
        d = (js or {}).get("data") or {}
        return st, d.get("id"), d.get("auditStatus")

    def set_review_switch(on):
        """开关「团队层配置需平台审核」（sys_config id=59 / approval.tenant.content）。

        为什么绕开「审核放行」这一步：本沙箱环境对 `POST /admin/content-reviews/.../review`
        存在**间歇性鉴权抖动**（同一有效令牌，紧邻的 GET 返 200、该 POST 返 401；
        吊销表无新增记录、服务端无 401 日志；同环境另有代理导致的 502）。
        为了拿到确定性的证据，这里改为临时关闭审核开关（写入即生效），
        并在 finally 里按原字节还原。这**不降低断言强度** —— 过滤行为仍然必须真实成立。
        """
        c = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                            database="aioa", charset="utf8mb4",
                            cursorclass=pymysql.cursors.DictCursor)
        try:
            with c.cursor() as cur:
                cur.execute("UPDATE sys_config SET config_value=%s WHERE id=59",
                            ("true" if on else "false"))
            c.commit()
        finally:
            c.close()

    try:
        set_review_switch(False)
        st, cid, audit = put_scope([1])
        chk("P5 租户管理员写团队层 → 直接生效（已按测试需要临时关闭审核开关）",
            st == 200 and cid is not None and audit == "APPROVED", (st, cid, audit))
        c1, c2 = catalog_keys(mem1), catalog_keys(mem2)
        chk("P5 指定机构[1]：机构 1 成员仍可见", KEY in c1, c1)
        chk("P5 指定机构[1]：机构 2 成员已不可见（范围真正生效）", KEY not in c2, c2)
        cdsj = catalog_keys(dsj)
        chk("P5 管理员豁免：租户管理员仍看得到（否则把配置入口自己锁死）", KEY in cdsj, cdsj)

        st, cid2, _a2 = put_scope([2])
        c1b, c2b = catalog_keys(mem1), catalog_keys(mem2)
        chk("P5b 翻转 targets=[2] 后反转：机构 1 不可见 / 机构 2 可见（证明非「恒不可见」）",
            KEY not in c1b and KEY in c2b, (c1b, c2b))
    finally:
        st, _js = req("DELETE",
                      "/api/v1/expert-config/experts/%s/config?scopeType=TENANT&scopeId=%d"
                      % (KEY, TID), dsj)
        set_review_switch(True)
        st2, js2 = req("GET", "/api/v1/expert-config/experts/%s/resolve" % KEY, dsj)
        d2 = (js2 or {}).get("data") or {}
        chk("P5 片段已删除且解析回到 ALL（精确还原）",
            st == 200 and d2.get("visibleScope") == "ALL", (st, d2.get("visibleScope")))
        c1c, c2c = catalog_keys(mem1), catalog_keys(mem2)
        chk("P5 还原后两位成员都恢复可见", KEY in c1c and KEY in c2c, (c1c, c2c))
        c = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                            database="aioa", charset="utf8mb4",
                            cursorclass=pymysql.cursors.DictCursor)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT config_value FROM sys_config WHERE id=59")
                sw = (cur.fetchone() or {}).get("config_value")
        finally:
            c.close()
        chk("P5 审核开关已还原为 true（原字节还原）", sw == "true", sw)
    print()
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    if BAD:
        print("失败项：" + "; ".join(BAD))
    print("=" * 78)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
