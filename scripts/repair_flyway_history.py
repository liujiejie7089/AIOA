# -*- coding: utf-8 -*-
"""修复 Flyway 历史表：把已存在于库中的历史迁移标记为「已成功应用」。

适用场景
--------
本库的 `flyway_schema_history` 曾长期只保留一条 `v=1, success=0` 的失败记录，
而实际表结构（V1–V21）早已建好。项目一直靠
`-Dspring.flyway.validate-on-migrate=false` 启动来跳过校验。

一旦用不带该 flag 的方式启动，或历史表被清掉，就会出现：
  * `Detected failed migration to version 1 (init)` —— 卡在失败记录
  * 或 Flyway 试图重放 V1–V21 —— `CREATE TABLE` / `ALTER TABLE` 撞表

此时用本脚本重建历史表：把 `db/migration` 下 **up_to_version（含）之前**的迁移
全部插成 `success=1`，使 Flyway 只需应用其后的新版本。

用法
----
    python scripts/repair_flyway_history.py            # 默认 up_to = 当前目录最大版本-1？
    python scripts/repair_flyway_history.py --up-to 21 # 显式指定：把 V1..V21 标为已应用

注意：脚本会先把历史表重命名为 `<表名>_broken_<日期>`（不删数据），并导出 JSON 备份。
修复后仍建议按项目约定携带 `-Dspring.flyway.validate-on-migrate=false` 启动。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import zlib

try:
    import pymysql
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：请 pip install pymysql")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIG_DIR = os.path.join(ROOT, "server", "aioa-boot", "src", "main", "resources", "db", "migration")
HISTORY = "flyway_schema_history"

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa", charset="utf8mb4")


def flyway_checksum(path):
    """近似 Flyway 的行级 CRC32（去 BOM、按行 update），用于填充历史表 checksum。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if text.startswith("\ufeff"):
        text = text[1:]
    crc = 0
    for line in text.splitlines():
        crc = zlib.crc32(line.encode("utf-8"), crc)
    return crc - 2 ** 32 if crc >= 2 ** 31 else crc


def migrations():
    out = []
    for f in os.listdir(MIG_DIR):
        m = re.match(r"V(\d+)__(.+)\.sql$", f)
        if m:
            out.append((int(m.group(1)), m.group(2), f))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--up-to", type=int, required=True,
                    help="把 V1..V<up-to> 标记为已应用（通常 = 当前已存在于库中的最大版本）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    target = [(v, d, f) for v, d, f in migrations() if v <= args.up_to]
    if not target:
        sys.exit("未在 %s 找到 ≤V%d 的迁移文件" % (MIG_DIR, args.up_to))
    print("将标记为已应用：%s" % ", ".join("V%d" % v for v, _, _ in target))

    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                (DB["database"], HISTORY))
    exists = cur.fetchone()[0] > 0

    stamp = dt.datetime.now().strftime("%Y%m%d")
    if exists and not args.dry_run:
        cur.execute("SELECT installed_rank,version,description,type,script,checksum,installed_by,"
                    "installed_on,execution_time,success FROM %s ORDER BY installed_rank" % HISTORY)
        rows = cur.fetchall()
        cols = ["installed_rank", "version", "description", "type", "script", "checksum",
                "installed_by", "installed_on", "execution_time", "success"]
        backup = os.path.join(ROOT, "flyway_history_backup_%s.json" % stamp)
        with open(backup, "w", encoding="utf-8") as fh:
            json.dump({"backed_up_at": dt.datetime.now().isoformat(),
                       "columns": cols,
                       "rows": [[str(c) for c in r] for r in rows]}, fh, ensure_ascii=False, indent=2)
        print("已备份历史记录 %d 条 -> %s" % (len(rows), backup))
        cur.execute("DROP TABLE IF EXISTS %s_broken_%s" % (HISTORY, stamp))
        cur.execute("RENAME TABLE %s TO %s_broken_%s" % (HISTORY, HISTORY, stamp))
        print("已归档原表为 %s_broken_%s（不删数据）" % (HISTORY, stamp))
        cur.execute("CREATE TABLE %s LIKE %s_broken_%s" % (HISTORY, HISTORY, stamp))
    elif not exists and not args.dry_run:
        cur.execute("""CREATE TABLE %s (
            installed_rank INT NOT NULL,
            version VARCHAR(50) DEFAULT NULL,
            description VARCHAR(200) NOT NULL,
            type VARCHAR(20) NOT NULL,
            script VARCHAR(1000) NOT NULL,
            checksum INT DEFAULT NULL,
            installed_by VARCHAR(100) NOT NULL,
            installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            execution_time INT NOT NULL,
            success TINYINT(1) NOT NULL,
            PRIMARY KEY (installed_rank)
        ) ENGINE=InnoDB""" % HISTORY)
        print("历史表不存在，已新建 %s" % HISTORY)
    else:
        print("[dry-run] 跳过建表/归档")

    if args.dry_run:
        print("[dry-run] 结束")
        return

    payload = []
    for rank, (v, desc, script) in enumerate(target, start=1):
        ck = flyway_checksum(os.path.join(MIG_DIR, script))
        payload.append((rank, str(v), desc, "SQL", script, ck, DB["user"], 0, 1))

    cur.execute("DELETE FROM %s WHERE version IS NOT NULL" % HISTORY)
    cur.executemany(
        "INSERT INTO %s (installed_rank,version,description,type,script,checksum,"
        "installed_by,execution_time,success) VALUES (%%s,%%s,%%s,%%s,%%s,%%s,%%s,%%s,%%s)" % HISTORY,
        payload)
    conn.commit()
    cur.execute("SELECT installed_rank,version,description,success FROM %s ORDER BY installed_rank" % HISTORY)
    out = cur.fetchall()
    print("已写入 %d 条历史记录：" % len(out))
    for r in out:
        print("   ", r)
    print("\n完成。请按项目约定启动：java -Dspring.flyway.validate-on-migrate=false -jar <fat-jar>")
    conn.close()


if __name__ == "__main__":
    main()
