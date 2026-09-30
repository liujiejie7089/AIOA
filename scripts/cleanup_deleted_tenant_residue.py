"""清理「已删除租户」的残留数据（默认干跑，--apply 才写库，写前必留 JSON 备份 + 回滚 SQL）。

## 为什么需要它

`TenantDeleteService.onApproved` 的级联在 2026-09-24 只覆盖了 `org_*`（机构/部门/员工/账号绑定），
**漏了 `sys_user`**（只把账号置 `DISABLED`、没写 `deleted_at`）。而平台管理员的「人员管理」
渲染的正是 `sys_user`（**跨租户全集**）⇒ 已删租户的账号仍会挂成一个分组继续展示。

用户反馈原文（2026-09-30）：
  「我已经删除了 test 租户，但是组织与员工中的人员管理还能看到 test」

代码侧已修（级联补上账号与角色）。本脚本负责把**修复之前**就已经删掉的租户的残留补清。

## 清理范围（刻意收窄，不做「见 token 就删」）

- **清理**：`sys_user` / `sys_user_role` —— 它们是「跨租户全集」视图（人员管理）的数据源，
  租户已删却仍会展示，属真正的**污染**。
- **不动**：`audit_log`（hash 链，append-only，删行会破坏链式完整性）、`approval_*` / `notification*`
  （删除动作自己的审批与通知留痕）。
- **只报告**：其余 `tenant_id` 非空且仍有存活行的表 —— 它们都是租户内私有数据，
  租户被软删后已不可达（`resolveRequestTenant` 对已删租户一律 404），无须改动。

用法：
  python scripts/cleanup_deleted_tenant_residue.py            # 干跑，只报告
  python scripts/cleanup_deleted_tenant_residue.py --apply     # 真正清理（先写备份）
"""
import argparse
import datetime as dt
import json
import os
import sys

import pymysql

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa", charset="utf8mb4")

# 要清理的表（跨租户全集视图的数据源）；其余只报告
PURGE = ["sys_user", "sys_user_role"]
# 明确不动的表（留痕 / 审计）
KEEP = {"audit_log", "approval_order", "approval_task", "approval_flow_def", "notification",
        "notification_delivery", "client_activity_log"}
BACKUP_DIR = "logs"


def connect():
    return pymysql.connect(**DB)


def tables_with_tenant(cur):
    cur.execute("""SELECT TABLE_NAME FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='aioa' AND COLUMN_NAME='tenant_id' ORDER BY TABLE_NAME""")
    return [r[0] for r in cur.fetchall()]


def has_column(cur, table, col):
    cur.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='aioa' AND TABLE_NAME=%s AND COLUMN_NAME=%s""", (table, col))
    return cur.fetchone()[0] > 0


def survey(cur, tables):
    """已软删租户 × 各表存活行数。"""
    cur.execute("SELECT id, name, code, deleted_at FROM sys_tenant WHERE deleted_at IS NOT NULL ORDER BY id")
    dead = cur.fetchall()
    out = []
    for tid, name, code, deleted in dead:
        rows = {}
        for t in tables:
            cur.execute("SELECT COUNT(*) FROM `%s` WHERE tenant_id=%%s" % t, (tid,))
            tot = cur.fetchone()[0]
            if not tot:
                continue
            alive = tot
            if has_column(cur, t, "deleted_at"):
                cur.execute("SELECT COUNT(*) FROM `%s` WHERE tenant_id=%%s AND deleted_at IS NULL" % t, (tid,))
                alive = cur.fetchone()[0]
            rows[t] = (tot, alive)
        out.append(dict(tenantId=tid, name=name, code=code, deletedAt=str(deleted), rows=rows))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只干跑报告）")
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()
    tables = tables_with_tenant(cur)
    dead = survey(cur, tables)

    if not dead:
        print("没有已软删的租户，无需清理。")
        return 0

    print("=== 已软删租户及其残留 ===")
    for d in dead:
        print("\n租户 id=%s「%s」code=%s 删除于 %s" % (d["tenantId"], d["name"], d["code"], d["deletedAt"]))
        for t, (tot, alive) in sorted(d["rows"].items()):
            flag = "★待清理" if (t in PURGE and alive) else ("留痕不动" if t in KEEP else "")
            print("   %-28s 总=%-4s 存活=%-4s %s" % (t, tot, alive, flag))

    plan = []
    for d in dead:
        for t in PURGE:
            if d["rows"].get(t, (0, 0))[1] > 0:
                plan.append((d["tenantId"], d["name"], t, d["rows"][t][1]))
    if not plan:
        print("\n无需清理：已删租户名下没有存活的账号/角色行。")
        return 0

    print("\n=== 计划清理 ===")
    for tid, name, t, n in plan:
        print("   租户 %s「%s」→ %s 软删 %d 行" % (tid, name, t, n))

    if not args.apply:
        print("\n（干跑）未写库。加 --apply 执行。")
        return 0

    # 备份：被抓取行的主键 + 回滚 SQL
    backup = {"createdAt": dt.datetime.now().isoformat(), "items": []}
    for tid, name, t, n in plan:
        cur.execute("SELECT id FROM `%s` WHERE tenant_id=%%s AND deleted_at IS NULL" % t, (tid,))
        ids = [r[0] for r in cur.fetchall()]
        backup["items"].append(dict(table=t, tenantId=tid, ids=ids,
                                    rollback="UPDATE `%s` SET deleted_at=NULL WHERE id IN (%s)"
                                             % (t, ",".join(str(i) for i in ids) or "NULL")))
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, "cleanup_tenant_residue_%s.json"
                        % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)
    print("\n备份已写：%s" % path)

    total = 0
    for tid, name, t, n in plan:
        cur.execute("UPDATE `%s` SET deleted_at=NOW(6) WHERE tenant_id=%%s AND deleted_at IS NULL" % t, (tid,))
        total += cur.rowcount
        print("   已清理 %s：%d 行（租户 %s）" % (t, cur.rowcount, tid))
    conn.commit()
    print("共清理 %d 行。" % total)

    # 复核
    print("\n=== 复核（应为 0 存活）===")
    for t in PURGE:
        cur.execute("SELECT COUNT(*) FROM `%s` wt JOIN sys_tenant st ON st.id=wt.tenant_id "
                    "WHERE st.deleted_at IS NOT NULL AND wt.deleted_at IS NULL" % t)
        print("   已删租户名下存活的 %s 行数 = %s" % (t, cur.fetchone()[0]))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
