# -*- coding: utf-8 -*-
"""只读探查：各租户的资源池席位（用来判断「调整资源」弹窗点第一行时 0 是否本来就对）。"""
import pymysql

conn = pymysql.connect(host="localhost", port=3306, user="root", password="",
                       database="aioa", charset="utf8mb4")
with conn.cursor() as c:
    c.execute("SELECT id, code, name, status, domain FROM sys_tenant ORDER BY id")
    print("== sys_tenant ==")
    for r in c.fetchall():
        print("  id=%s code=%s name=%s status=%s domain=%s" % r)

    c.execute("SELECT tenant_id, period, SUM(token_total), SUM(expert_seats), SUM(skill_seats), "
              "COUNT(*) FROM tenant_resource_pool WHERE deleted_at IS NULL GROUP BY tenant_id, period "
              "ORDER BY tenant_id")
    print("== tenant_resource_pool (sum by tenant) ==")
    for r in c.fetchall():
        print("  tenant_id=%s period=%s tokenTotal=%s expertSeats=%s skillSeats=%s rows=%s" % r)

    c.execute("SHOW COLUMNS FROM sys_tenant")
    cols = [r[0] for r in c.fetchall()]
    print("== sys_tenant columns ==")
    print("  " + ", ".join(cols))
    print("  parent_id/level 是否还在: parent_id=%s level=%s" % ("parent_id" in cols, "level" in cols))

    c.execute("SHOW INDEX FROM sys_tenant")
    idx = sorted({r[2] for r in c.fetchall()})
    print("== sys_tenant indexes ==")
    print("  " + ", ".join(idx))
    print("  idx_tenant_parent 是否还在: %s" % ("idx_tenant_parent" in idx))
conn.close()
