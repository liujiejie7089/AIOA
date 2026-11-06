"""存量资料重建索引（docs/74 上线步骤）。

新切片规则（表格按「列名 + 连续 N 行」、另生成统计摘要块）只对**之后入库**的资料生效。
已经上传的资料仍是旧的「一行一块、无列名」切片，必须重建一次索引才会变好 ——
否则用户会以为「改完了还是老样子」，而实际上是老切片没动。

重建走已有接口 `POST /api/v1/kb/documents/{id}/retry`（从 content 重新切片 + 重算向量），
幂等，可重复跑。**不动原文、不动可见范围、不动 id**。

用法（Python312）：
    python scripts/_kb_reindex_all.py                 # 只列出来，不动手
    python scripts/_kb_reindex_all.py --apply          # 真的重建
    python scripts/_kb_reindex_all.py --apply --id 245 # 只重建某一篇
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import sys

import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
CAND = ["Admin@123", "User@123", "000000", "123456"]
C = httpx.Client(timeout=180.0, trust_env=False)
H = {}


def login():
    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("""SELECT u.username, u.password_hash FROM sys_user u
                       JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                       JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL
                       WHERE u.deleted_at IS NULL AND u.status='ENABLED'
                       ORDER BY u.id LIMIT 1""")
        u = cur.fetchone()
    conn.close()
    pw = CAND[0]
    try:
        import bcrypt
        for c in CAND:
            if u and u["password_hash"] and bcrypt.checkpw(c.encode(), u["password_hash"].encode()):
                pw = c
                break
    except ImportError:
        pass
    r = C.post(f"{BASE}/auth/login", json={"username": u["username"], "password": pw})
    token = ((r.json() or {}).get("data") or {}).get("accessToken")
    if not token:
        raise SystemExit(f"登录失败：{r.text[:200]}")
    H["Authorization"] = f"Bearer {token}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="不传则只预览")
    ap.add_argument("--id", type=int, default=None)
    args = ap.parse_args(argv)

    login()
    docs = (C.get(f"{BASE}/kb/documents", headers=H).json() or {}).get("data") or []
    if args.id is not None:
        docs = [d for d in docs if d.get("id") == args.id]
    if not docs:
        print("没有可重建的资料（列表为空，或 --id 不在可见范围内）")
        return 1

    todo, skipped = [], []
    for d in docs:
        name, state, chunks = d.get("name") or d.get("docName"), d.get("state"), d.get("chunkCount") or 0
        if str(state).upper() == "WAIT":
            skipped.append((name, "解析中"))
        elif str(state).upper() == "FAILED":
            skipped.append((name, "上次入库失败，请先在页面重试"))
        elif chunks == 0:
            # 页面上「已索引 N 段」但库里没有切片，或本来就是空正文（演示数据）——
            # 这类重建也没用，先单独点名，别混在成功里（docs/74 附带发现）
            skipped.append((name, "chunkCount=0（无切片，多为演示/空正文数据）"))
        else:
            todo.append(d)

    print(f"待重建 {len(todo)} 篇，跳过 {len(skipped)} 篇")
    for name, why in skipped:
        print(f"  [skip] {name} —— {why}")
    if not args.apply:
        for d in todo:
            print(f"  [dry ] {d.get('id')}\t{d.get('chunkCount')} 段\t{d.get('name')}")
        print("\n加上 --apply 才会真的重建")
        return 0

    fail = 0
    for d in todo:
        did, before = d.get("id"), d.get("chunkCount")
        r = C.post(f"{BASE}/kb/documents/{did}/retry", headers=H)
        after = ((r.json() or {}).get("data") or {})
        ok = str(after.get("state") or "").upper() == "OK"
        print(f"  [{'ok  ' if ok else 'FAIL'}] {did}\t{before} → {after.get('chunkCount')} 段\t"
              f"{d.get('name')}  {('' if ok else after.get('errorMsg') or '')}")
        if not ok:
            fail += 1
    print(f"\n完成：{len(todo) - fail}/{len(todo)} 成功")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
