# -*- coding: utf-8 -*-
"""T21 演示数据清理执行器（逻辑删除，先备份）。

用法：
    python scripts/cleanup_demo_data.py --dry-run   # 只列出将被清理的行，不改库
    python scripts/cleanup_demo_data.py             # 备份 + 执行 cleanup_demo_data.sql

备份：cleanup_backup_<YYYYmmdd_HHMMSS>.json（仓库根），含被影响行的全字段快照，
      回滚方式见文件内 rollback_sql 字段。
"""
import argparse
import datetime as dt
import json
import os
import sys

try:
    import pymysql
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：请 pip install pymysql")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_FILE = os.path.join(ROOT, "server", "scripts", "cleanup_demo_data.sql")

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa", charset="utf8mb4")

# 与 SQL 中的条件一一对应（用于「先查将被影响的行」）
TARGETS = [
    ("agent_worker", "重复的「晨报员」（保留 id 最小的一条）",
     "SELECT * FROM agent_worker WHERE deleted_at IS NULL AND name='晨报员' "
     "AND id NOT IN (SELECT keep_id FROM (SELECT MIN(id) AS keep_id FROM agent_worker "
     "WHERE deleted_at IS NULL AND name='晨报员') t)"),
    ("agent_worker", "「一句话创建」测试留下的碎片命名员工",
     "SELECT * FROM agent_worker WHERE deleted_at IS NULL AND (name LIKE '按当前配置重新生成%' "
     "OR name LIKE '合同到期前 7 天%助手' OR name LIKE '每天 8 点推送行%助手' "
     "OR name LIKE 'E2E-%' OR name LIKE '冒烟%' OR name='临时通用助手')"),
    ("approval_order", "测试/冒烟/回归/联调造单",
     "SELECT * FROM approval_order WHERE deleted_at IS NULL AND (title IN "
     "('测试审批单-发起人','e2e 审批流转单','e2e权限测试单','test','多角色冒烟-提交',"
     "'curl测试','通知链路验证单','意见流验证单','对外发布审批（总测试）') "
     "OR title LIKE '回归-%' OR biz_type='LEAVE' "
     "OR content LIKE '%批次二验证%' OR content LIKE '%截图用%')"),
    ("user_result", "「我的成果」中的回归测试记录",
     "SELECT * FROM user_result WHERE deleted_at IS NULL "
     "AND (title LIKE '回归-%' OR meta LIKE '%回归测试%')"),
]


def rows_as_dicts(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = pymysql.connect(**DB)
    cur = conn.cursor()

    snapshot, plan = {}, []
    for table, label, sql in TARGETS:
        cols, rows = rows_as_dicts(cur, sql)
        ids = [r["id"] for r in rows]
        plan.append((table, label, len(rows), ids))
        snapshot.setdefault(table, [])
        snapshot[table].extend(rows)
        print("[%s] %-34s 将逻辑删除 %d 条  ids=%s" % (table, label, len(rows), ids))

    total = sum(n for _, _, n, _ in plan)
    print("\n合计 %d 条" % total)
    if args.dry_run:
        print("[dry-run] 未改动数据库")
        return
    if total == 0:
        print("没有需要清理的数据")
        return

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(ROOT, "cleanup_backup_%s.json" % stamp)
    rollback = {}
    for table, _, _, ids in plan:
        if ids:
            rollback[table] = "UPDATE %s SET deleted_at = NULL WHERE id IN (%s);" % (
                table, ",".join(str(i) for i in sorted(ids)))
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump({
            "backed_up_at": dt.datetime.now().isoformat(),
            "note": "T21 演示数据清理前快照（逻辑删除，可回滚）",
            "rollback_sql": rollback,
            "rows": {k: [{kk: (str(vv) if vv is not None else None) for kk, vv in r.items()}
                         for r in v] for k, v in snapshot.items()},
        }, fh, ensure_ascii=False, indent=2)
    print("\n已备份受影响行 -> %s" % backup)
    print("回滚语句：")
    for s in rollback.values():
        print("  " + s)

    with open(SQL_FILE, "r", encoding="utf-8") as fh:
        sql_text = fh.read()
    # 注意：必须先按行剔除注释，再按 ';' 切分。若先切分，每个语句块的开头都是
    # 它上方的注释行，`startswith('--')` 会把整块（含真正的 SQL）一起丢掉。
    body = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    affected = 0
    for s in stmts:
        affected += cur.execute(s)
    conn.commit()
    print("\n执行完成，共 %d 条语句，影响 %d 行" % (len(stmts), affected))

    cur.execute("SELECT COUNT(*) FROM agent_worker WHERE deleted_at IS NULL")
    print("剩余可见数字员工：%d 个" % cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM approval_order WHERE deleted_at IS NULL")
    print("剩余可见审批单：%d 条" % cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM user_result WHERE deleted_at IS NULL")
    print("剩余可见成果：%d 条" % cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
