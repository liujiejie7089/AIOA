#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""统计：租户管理员 → 机构（企业管理员）→ 部门（负责人）→ 普通用户 的人员层级。

输出 JSON 到 stdout，便于上层渲染；控制台另打印一张人读表格。
用法：python scripts/stat_org_hierarchy.py [--tenant 9] [--json]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pymysql  # noqa: E402

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def q(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def main():
    only = None
    if "--tenant" in sys.argv:
        only = int(sys.argv[sys.argv.index("--tenant") + 1])

    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            tenants = q(cur, """
                SELECT id, code, name FROM sys_tenant
                WHERE deleted_at IS NULL AND id > 1 ORDER BY id""")
            if only:
                tenants = [t for t in tenants if t["id"] == only]

            out = []
            for t in tenants:
                tid = t["id"]
                tadmin = q(cur, """
                    SELECT u.id, u.username, COALESCE(u.nickname,u.username) AS name
                    FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                    JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL AND r.role_code='ROLE_TENANT_ADMIN'
                    WHERE u.deleted_at IS NULL AND u.status='ENABLED' AND u.tenant_id=%s
                    ORDER BY u.id""", (tid,))
                insts = q(cur, """
                    SELECT i.id, i.name, i.code, i.status, i.onboard_step,
                           i.admin_user_id, i.admin_name
                    FROM org_institution i
                    WHERE i.tenant_id=%s AND i.deleted_at IS NULL ORDER BY i.id""", (tid,))
                depts = q(cur, """
                    SELECT d.id, d.institution_id, d.name, d.code, d.leader_user_id, d.leader_name
                    FROM org_department d JOIN org_institution i ON i.id=d.institution_id
                    WHERE i.tenant_id=%s AND i.deleted_at IS NULL AND d.deleted_at IS NULL
                    ORDER BY d.institution_id, d.id""", (tid,))
                members = q(cur, """
                    SELECT m.id, m.institution_id, m.department_id, m.user_id, m.name,
                           m.job_title, m.employee_no, m.status,
                           u.username,
                           GROUP_CONCAT(r.role_code ORDER BY r.id) AS roles
                    FROM org_member m
                    JOIN org_institution i ON i.id=m.institution_id AND i.deleted_at IS NULL
                    JOIN sys_user u ON u.id=m.user_id AND u.deleted_at IS NULL
                    LEFT JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                    LEFT JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL
                    WHERE m.tenant_id=%s AND m.deleted_at IS NULL
                    GROUP BY m.id ORDER BY m.institution_id, m.department_id, m.user_id""", (tid,))

                def is_admin(roles):
                    roles = roles or ""
                    return "ROLE_TENANT_ADMIN" in roles or "ROLE_ORG_ADMIN" in roles

                inst_nodes = []
                for i in insts:
                    ims = [m for m in members if m["institution_id"] == i["id"]]
                    org_admins = [m for m in ims if "ROLE_ORG_ADMIN" in (m["roles"] or "")]
                    plain = [m for m in ims if not is_admin(m["roles"])]
                    ds = []
                    for d in [x for x in depts if x["institution_id"] == i["id"]]:
                        dm = [m for m in plain if m["department_id"] == d["id"]]
                        ds.append({
                            "id": d["id"], "name": d["name"], "code": d["code"],
                            "leader_user_id": d["leader_user_id"], "leader_name": d["leader_name"],
                            "member_count": len(dm),
                            "members": [{"user_id": m["user_id"], "username": m["username"],
                                         "name": m["name"], "job_title": m["job_title"],
                                         "roles": m["roles"]} for m in dm],
                        })
                    nod = [m for m in plain if not any(m["department_id"] == d["id"] for d in ds)]
                    inst_nodes.append({
                        "id": i["id"], "name": i["name"], "code": i["code"], "status": i["status"],
                        "onboard_step": i["onboard_step"],
                        "admin_user_id": i["admin_user_id"], "admin_name": i["admin_name"],
                        "org_admin_count": len(org_admins),
                        "org_admins": [{"user_id": m["user_id"], "username": m["username"],
                                        "name": m["name"], "roles": m["roles"]} for m in org_admins],
                        "departments": ds,
                        "dept_total": len(ds),
                        "member_total": len(plain),
                        "dept_leader_total": sum(1 for d in ds if d["leader_user_id"]),
                        "unassigned": [{"user_id": m["user_id"], "username": m["username"],
                                        "name": m["name"]} for m in nod],
                    })
                out.append({
                    "tenant_id": tid, "code": t["code"], "name": t["name"],
                    "tenant_admins": tadmin,
                    "institutions": inst_nodes,
                    "inst_total": len(inst_nodes),
                    "org_admin_total": sum(i["org_admin_count"] for i in inst_nodes),
                    "dept_total": sum(i["dept_total"] for i in inst_nodes),
                    "member_total": sum(i["member_total"] for i in inst_nodes),
                })
    finally:
        conn.close()

    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print(f"{'租户':<28}{'租户管理员':<14}{'机构':>5}{'企业管理员':>8}{'部门':>5}{'普通用户':>8}")
    print("-" * 78)
    for t in out:
        admins = "、".join(a["name"] for a in t["tenant_admins"]) or "-"
        print(f"{t['name']:<28}{admins:<14}{t['inst_total']:>5}"
              f"{t['org_admin_total']:>8}{t['dept_total']:>5}{t['member_total']:>8}")
    print("-" * 78)
    print(f"{'合计':<28}{'':<14}{sum(t['inst_total'] for t in out):>5}"
          f"{sum(t['org_admin_total'] for t in out):>8}"
          f"{sum(t['dept_total'] for t in out):>5}"
          f"{sum(t['member_total'] for t in out):>8}")


if __name__ == "__main__":
    main()
