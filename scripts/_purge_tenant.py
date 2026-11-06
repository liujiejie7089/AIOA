"""按租户彻底清理某个租户的全部数据（2026-11-05，用户要求删掉 WJJ-DEMO）。

安全设计（为什么不是一句 DELETE）：
  1. **先备份再删**：把即将删除的每一行导出成 JSON（含 datetime/Decimal 转字符串），
     出问题可以精确回灌；不依赖 mysqldump（本机没装 MySQL 客户端）。
  2. **两个口径**：带 ``tenant_id`` 的表按租户删；不带 ``tenant_id`` 的 8 张表逐个判性质
     （平台级配置一律跳过，只有 form_template_version / revoked_token 属于该租户）。
  3. **先子后父**：先算出 form_template 的 id 集合，再删版本行，最后删主表，
     否则先删模板会让「按 template_id 删版本」查不到目标。
  4. **删完必须证明没伤到别人**：删前删后各做一次「全表 × 全租户行数快照」，
     逐表比对其它租户的行数；有任何差异就整体回滚并报错。

用法：
   python scripts/_purge_tenant.py            # 只看会删什么（dry-run）
   python scripts/_purge_tenant.py --apply    # 真删
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pymysql

TENANT_ID = 3
TENANT_CODE = "WJJ-DEMO"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
OUT = Path(".workbuddy/tmp/tenant-purge")
# 平台级配置表：不属于任何租户，**永远不许碰**
PLATFORM_TABLES = {
    "flyway_schema_history", "flyway_schema_history_broken_20260911",
    "gitee_platform_config", "model_config", "model_config_snapshot", "quota_package",
}


def dump(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat(sep=" ") if isinstance(o, datetime) else o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    return str(o)


def connect():
    c = pymysql.connect(**DB)
    c.autocommit = False          # 显式事务：pymysql 默认不回滚也不提交，必须自己掌控
    return c


def meta(cur):
    cur.execute("""SELECT TABLE_NAME AS t FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA='aios' AND COLUMN_NAME='tenant_id'""")
    with_tid = {r["t"] for r in cur.fetchall()}
    cur.execute("""SELECT TABLE_NAME AS t FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA='aios' AND TABLE_TYPE='BASE TABLE'""")
    all_tables = {r["t"] for r in cur.fetchall()}
    return with_tid, all_tables


def count_snapshot(cur, tables):
    """全表 × 全租户行数快照，用于「有没有误伤别的租户」的前后比对。"""
    snap = {}
    for t in sorted(tables):
        if "tenant_id" not in set_column_names(cur, t):
            continue
        cur.execute(f"SELECT tenant_id AS tid, COUNT(*) AS n FROM `{t}` GROUP BY tenant_id")
        snap[t] = {int(r["tid"] if r["tid"] is not None else -1): int(r["n"]) for r in cur.fetchall()}
    return snap


_COL_CACHE = {}


def set_column_names(cur, table):
    if table not in _COL_CACHE:
        cur.execute("""SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA='aios' AND TABLE_NAME=%s""", (table,))
        _COL_CACHE[table] = {r["c"] for r in cur.fetchall()}
    return _COL_CACHE[table]


def main():
    apply = "--apply" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.cursor()

    with_tid, all_tables = meta(cur)
    print(f"表总数 {len(all_tables)}；带 tenant_id {len(with_tid)}")

    # ---------- 租户身份校验：按 code 认人，不认手抄的 id ----------
    cur.execute("SELECT id, code, name FROM sys_tenant WHERE id=%s", (TENANT_ID,))
    t = cur.fetchone()
    if not t or t["code"] != TENANT_CODE:
        print(f"[ABORT] id={TENANT_ID} 不是 {TENANT_CODE}：{t}")
        return 1
    print(f"目标租户：id={t['id']} code={t['code']} name={t['name']}")

    cur.execute("SELECT id, username FROM sys_user WHERE tenant_id=%s", (TENANT_ID,))
    users = [r["id"] for r in cur.fetchall()]
    print(f"该租户账号：{users}")

    before = count_snapshot(cur, all_tables)

    # ---------- 先算「跨表引用」的 id 集合（必须早于删主表） ----------
    form_ids = []
    if "form_template" in all_tables:
        cur.execute("SELECT id FROM form_template WHERE tenant_id=%s", (TENANT_ID,))
        form_ids = [r["id"] for r in cur.fetchall()]

    # ---------- 计划 ----------
    plan = []          # (table, where_sql, params, 描述)
    for tbl in sorted(with_tid):
        if tbl in PLATFORM_TABLES or tbl == "sys_tenant":
            continue
        plan.append((tbl, "tenant_id=%s", (TENANT_ID,), "按租户"))

    if form_ids:
        ph = ",".join(["%s"] * len(form_ids))
        plan.append(("form_template_version", f"template_id IN ({ph})", tuple(form_ids),
                     f"模板版本（template_id ∈ {len(form_ids)} 个）"))
    if users:
        ph = ",".join(["%s"] * len(users))
        plan.append(("revoked_token", f"user_id IN ({ph})", tuple(users), "已吊销令牌"))

    # 统计每个表要删多少行
    todo = []
    for tbl, where, params, why in plan:
        cols = set_column_names(cur, tbl)
        if tbl == "revoked_token" and "user_id" not in cols:
            continue
        cur.execute(f"SELECT COUNT(*) AS n FROM `{tbl}` WHERE {where}", params)
        n = cur.fetchone()["n"]
        if n:
            todo.append((tbl, where, params, why, n))

    total = sum(x[4] for x in todo)
    print(f"\n将删除 {len(todo)} 张表、共 {total} 行：")
    for tbl, _w, _p, why, n in sorted(todo, key=lambda x: -x[4]):
        print(f"  {n:>7}  {tbl:<38} {why}")
    if not apply:
        print("\n[dry-run] 未做任何修改。加 --apply 执行。")
        return 0

    # ---------- 备份 ----------
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = OUT / f"tenant-{TENANT_CODE}-{stamp}.json"
    payload = {"tenantId": TENANT_ID, "tenantCode": TENANT_CODE, "takenAt": stamp, "tables": {}}
    for tbl, where, params, _why, _n in todo:
        cur.execute(f"SELECT * FROM `{tbl}` WHERE {where}", params)
        rows = cur.fetchall()
        payload["tables"][tbl] = [{k: dump(v) for k, v in r.items()} for r in rows]
    cur.execute("SELECT * FROM sys_tenant WHERE id=%s", (TENANT_ID,))
    payload["tables"]["sys_tenant"] = [{k: dump(v) for k, v in r.items()} for r in cur.fetchall()]
    backup.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已备份到 {backup}（{sum(len(v) for v in payload['tables'].values())} 行）")

    # ---------- 执行 ----------
    deleted = {}
    try:
        for tbl, where, params, _why, _n in todo:
            cur.execute(f"DELETE FROM `{tbl}` WHERE {where}", params)
            deleted[tbl] = cur.rowcount
        # 租户行本身最后删：前面任何一步失败都整体回滚，租户还在，可重来
        cur.execute("DELETE FROM sys_tenant WHERE id=%s", (TENANT_ID,))
        deleted["sys_tenant"] = cur.rowcount

        # ---------- 校验 ----------
        after = count_snapshot(cur, all_tables)
        damaged = []
        for tbl, per_tenant in before.items():
            for tid, n in per_tenant.items():
                if tid == TENANT_ID:
                    continue
                now_n = after.get(tbl, {}).get(tid, 0)
                if now_n != n:
                    damaged.append((tbl, tid, n, now_n))
        if damaged:
            raise RuntimeError(f"误删了其它租户的数据，已回滚：{damaged[:5]}")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[ROLLBACK] {e}")
        return 2

    # ---------- 复核：租户 3 是否真的清零 ----------
    cur.execute("SELECT COUNT(*) AS n FROM sys_tenant WHERE id=%s", (TENANT_ID,))
    left_tenant = cur.fetchone()["n"]
    print(f"\n删除完成，共 {sum(deleted.values())} 行；租户行剩余 {left_tenant}")
    if left_tenant:
        print("[WARN] 租户行没删掉")
        return 3
    print("其它租户行数逐表比对：全部一致（无误伤）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
