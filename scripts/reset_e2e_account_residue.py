# -*- coding: utf-8 -*-
"""E2E 残留账号清理（演示库卫生）。

背景（2026-09-27 实测发现）：
    `scripts/e2e_v63_org_feedback.py` 每次运行会新建 1 家机构 + 1 个部门 + 3 名员工 + **4 个账号**
    （e2eadm*/e2eled*/e2emem*/e2emem2*），收尾只把机构置 CLOSED，**账号原样留在账号池里**。
    该套件已跑过 11 次 ⇒ 演示库累积 **44 个 ENABLED 的 e2e* 账号**（43 个还绑着 E2E 员工）。

    后果不是报错，而是**污染**：V67 批次 C 的「给员工追加账号」候选接口 `GET /api/v1/org/accounts`
    是**租户级**查询（规格要求「虚拟管理员账号」必须可选），于是这 44 个账号全被吸进下拉，
    把真实候选（12 个）淹掉。同一原因也让租户 2 的机构列表里 13/26 是 `E2E企业-*`（50%）。

处置（本脚本）：
    **软删** `sys_user` 里 `username LIKE 'e2e%'` 的存活行 —— 行保留（`org_member.user_id` 还指得到人，
    排查证据不丢），但 `selectTenantAccounts` 有 `u.deleted_at IS NULL` 条件，故软删即退出候选池。
    **不删机构/部门/员工**：e2e_v63 明确以「置 CLOSED 保留证据」为设计意图，本脚本尊重该意图。
    **不断言/不修改 audit_log**（审计不可篡改）。

    `e2e_v63_org_feedback.py` 已同步修复（收尾会软删自己新建的 4 个账号），故本脚本是一次性清历史。

铁律：先备份整行到 JSON，再执行（同 reset_v24_demo.py）。
用法：
    python scripts/reset_e2e_account_residue.py --dry-run
    python scripts/reset_e2e_account_residue.py
"""
import argparse
import datetime
import json
import os

import pymysql

DB = dict(host="127.0.0.1", port=3306, user="root", password="",
          database="aioa", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)

USER_LIKE = "e2e%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写库")
    ap.add_argument("--prefix", default=USER_LIKE, help="账号前缀（默认 e2e%%）")
    args = ap.parse_args()

    c = pymysql.connect(**DB)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id, tenant_id, username, nickname, status, created_at "
                        "FROM sys_user WHERE deleted_at IS NULL AND username LIKE %s ORDER BY id",
                        (args.prefix,))
            rows = cur.fetchall()
    finally:
        c.close()

    print("=" * 78)
    print("E2E 残留账号清理  prefix=%s  dry_run=%s" % (args.prefix, args.dry_run))
    print("=" * 78)
    print("命中存活账号：%d 个" % len(rows))
    for r in rows[:8]:
        print("  #%s tenant=%s %s(%s) %s" % (r["id"], r["tenant_id"], r["username"],
                                             r["nickname"], r["status"]))
    if len(rows) > 8:
        print("  ...（其余 %d 个略）" % (len(rows) - 8))

    if not rows:
        print("\n无需清理。")
        return 0

    if args.dry_run:
        print("\n[--dry-run] 未写库。去掉 --dry-run 执行。")
        return 0

    # 先备份整行（可据此逐行恢复 deleted_at）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bdir = os.path.join(root, "logs", "reset_backup")
    os.makedirs(bdir, exist_ok=True)
    out = os.path.join(bdir, "e2e_account_residue_%s.json"
                       % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"backed_up_at": str(datetime.datetime.now()),
                   "prefix": args.prefix,
                   "rows": [{k: (str(v) if isinstance(v, datetime.datetime) else v)
                             for k, v in r.items()} for r in rows]},
                  f, ensure_ascii=False, indent=2)
    print("\n已备份 %d 行 → %s" % (len(rows), out))

    c = pymysql.connect(**DB)
    try:
        with c.cursor() as cur:
            cur.execute("UPDATE sys_user SET deleted_at = NOW(6) "
                        "WHERE deleted_at IS NULL AND username LIKE %s", (args.prefix,))
            n = cur.rowcount
            c.commit()
    finally:
        c.close()

    print("已软删 %d 个账号（行保留，已退出候选池）。" % n)

    # 复核：候选池里不应再有该前缀
    c = pymysql.connect(**DB)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM sys_user "
                        "WHERE deleted_at IS NULL AND username LIKE %s", (args.prefix,))
            left = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM sys_user WHERE deleted_at IS NULL")
            total = cur.fetchone()["n"]
    finally:
        c.close()
    print("复核：该前缀存活账号 %d 个（应为 0）；本租户存活账号总数 %d" % (left, total))
    return 0 if left == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
