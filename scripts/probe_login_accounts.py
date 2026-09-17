# -*- coding: utf-8 -*-
"""批量探测登录：把库里全部启用账号分别用候选口令试一遍，定位「登不上去」的账号。

只读：不修改任何数据。
"""
import sys
from pathlib import Path

import httpx
import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=30, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)

CANDIDATES = ["User@123", "Admin@123", "123456"]


def login(u, p):
    try:
        d = C.post(f"{BASE}/auth/login", json={"username": u, "password": p}).json()
    except Exception as e:
        return None, f"transport:{e.__class__.__name__}"
    if d.get("code") == 0:
        return d["data"]["accessToken"], "ok"
    return None, d.get("message")


def main():
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.tenant_id, u.status, u.password_hash,
                       GROUP_CONCAT(r.role_code ORDER BY r.id) AS roles
                FROM sys_user u
                LEFT JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                LEFT JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL
                WHERE u.deleted_at IS NULL AND u.status='ENABLED'
                GROUP BY u.id ORDER BY u.tenant_id, u.id""")
            users = cur.fetchall()
    finally:
        conn.close()

    print(f"启用账号 {len(users)} 个，候选口令 {CANDIDATES}\n")
    fails = []
    hdr = f"{'id':<6}{'username':<20}{'tid':>4}  {'roles':<34}{'hash前缀':<12}结果"
    print(hdr)
    print("-" * len(hdr))
    for u in users:
        hit = None
        for p in CANDIDATES:
            tok, msg = login(u["username"], p)
            if tok:
                hit = p
                break
        roles = u["roles"] or "(无角色)"
        hp = (u["password_hash"] or "")[:10]
        if hit:
            mark = "OK  " + hit
        else:
            mark = "FAIL " + str(msg)
            fails.append(u)
        print(f"{u['id']:<6}{u['username']:<20}{u['tenant_id']:>4}  {roles:<34}{hp:<12}{mark}")

    print("\n" + "=" * 70)
    print(f"可登录 {len(users) - len(fails)}/{len(users)}；失败 {len(fails)} 个")
    if fails:
        print("\n失败清单（含口令哈希前缀，用于判断编码方式）：")
        for u in fails:
            print(f"  {u['id']:<6}{u['username']:<20}tid={u['tenant_id']:<3}"
                  f"roles={u['roles']}  hash={(u['password_hash'] or '(空)')[:32]}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
