# -*- coding: utf-8 -*-
"""演示环境词元额度复位（把被反复测试跑光的额度补回到可用水位）。

背景：`tenant_quota` 的 `used_tokens` 会随每次真实 LLM 会话累加。E2E/联调反复跑
会耗尽演示账号额度，表现为用户端会话里出现「额度已用完。你可以：① 等待下月额度
发放 ② 购买词元包 ③ 联系管理员扩容」，后续职责边界类用例随之失败。这是**环境数据
漂移**，不是功能缺陷。

用法：
    python scripts/reset_demo_quota.py --dry-run          # 只打印将要补的行
    python scripts/reset_demo_quota.py                    # 备份 + 补额度
    python scripts/reset_demo_quota.py --target 2000000   # 自定义补到多少剩余

补法：`free_tokens += (target - left)`，只动 `free_tokens`，不改 `quota_tokens`，
也不改 `used_tokens`（保留真实用量与账本一致性）。仅处理 `left <= threshold` 的行。

备份：quota_backup_<YYYYmmdd_HHMMSS>.json（仓库根），含被改行的改前全字段快照，
      回滚 SQL 见文件内 rollback_sql 字段。
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
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa", charset="utf8mb4")

DEFAULT_TARGET = 1_000_000   # 补到剩余 100 万词元
DEFAULT_THRESHOLD = 50_000   # 剩余低于 5 万才算「需要补」

SELECT_SQL = """
SELECT q.id, q.tenant_id, q.user_id, q.quota_tokens, q.used_tokens, q.free_tokens,
       GREATEST(0, COALESCE(q.quota_tokens,0) + COALESCE(q.free_tokens,0)
                   - COALESCE(q.used_tokens,0)) AS left_tokens,
       u.username
FROM tenant_quota q
LEFT JOIN sys_user u ON u.id = q.user_id
WHERE GREATEST(0, COALESCE(q.quota_tokens,0) + COALESCE(q.free_tokens,0)
                  - COALESCE(q.used_tokens,0)) <= %s
ORDER BY q.user_id
"""


def rows_as_dicts(cur, sql, args=()):
    cur.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return cols, [dict(zip(cols, r)) for r in cur.fetchall()]


def jsonable(v):
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只列出将被补额度的行")
    ap.add_argument("--target", type=int, default=DEFAULT_TARGET, help="补到的剩余额度")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help="剩余低于该值才处理")
    args = ap.parse_args()

    if args.target <= args.threshold:
        sys.exit("--target 必须大于 --threshold")

    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cols, rows = rows_as_dicts(cur, SELECT_SQL, (args.threshold,))
        if not rows:
            print("无需处理：没有剩余额度低于 %s 的账号。" % f"{args.threshold:,}")
            return

        plans = []
        for r in rows:
            add = args.target - int(r["left_tokens"])
            plans.append((r, add))
            who = r["username"] or ("租户共享(user_id=%s)" % r["user_id"] if r["user_id"] == 0 else "user_id=%s" % r["user_id"])
            print("  · tenant=%s user=%s %-24s 剩余 %10s → 补 %9s → 剩余 %10s"
                  % (r["tenant_id"], r["user_id"], who,
                     f"{r['left_tokens']:,}", f"{add:,}", f"{args.target:,}"))

        if args.dry_run:
            print("\n[dry-run] 共 %d 行，未改库。" % len(plans))
            return

        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(ROOT, "quota_backup_%s.json" % ts)
        rollback = ["UPDATE tenant_quota SET free_tokens=%s WHERE id=%s;"
                    % (r["free_tokens"], r["id"]) for r, _ in plans]
        payload = {
            "created_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": "演示环境额度复位（E2E 反复调用真实 LLM 导致 used_tokens 漂移）",
            "target_left": args.target,
            "threshold": args.threshold,
            "affected": [{k: jsonable(v) for k, v in r.items()} for r, _ in plans],
            "rollback_sql": rollback,
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        n = 0
        with conn.cursor() as cur:
            for r, add in plans:
                cur.execute(
                    "UPDATE tenant_quota SET free_tokens = COALESCE(free_tokens,0) + %s WHERE id = %s",
                    (add, r["id"]))
                n += cur.rowcount
        conn.commit()
        print("\n已补 %d 行，备份：%s" % (n, os.path.basename(backup_path)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
