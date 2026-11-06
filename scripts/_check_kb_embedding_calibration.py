"""知识库向量阈值标定（docs/74 P0-3）。

为什么需要它：`aios.kb.embedding-provider=local` 时向量腿是 FNV 哈希 char2gram（**无语义**），
实测余弦最高 0.157、中位 0.080，而默认阈值 `DEFAULT_KB_THRESHOLD=0.5` ⇒ **0 条过阈**，
hybrid 实际退化为纯关键词。换成语义 embedding（bge-m3 / bge-small-zh）后，
分布会整体上移，**阈值必须重新标定**，否则要么仍全被拦、要么把噪声放进来。

做法：调 `/api/v1/kb/search?mode=vector&threshold=0&topk=200`，拿到每条命中片段的余弦分
（mode=vector 时 score 就是余弦），按真实问句统计分布，给出建议阈值。
不读库、不算向量，全部走线上同一条代码路径。

用法（Python312）：
    python scripts/_check_kb_embedding_calibration.py
    python scripts/_check_kb_embedding_calibration.py --queries "报销标准是什么" "年假几天"
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import json
import statistics
import sys

import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
CAND = ["Admin@123", "User@123", "000000", "123456"]
C = httpx.Client(timeout=60.0, trust_env=False)
H = {}

DEFAULT_QUERIES = [
    "报销标准是什么",
    "年假有几天",
    "四川省省级非遗项目有多少个",
    "差旅住宿上限",
]


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
    d = (r.json() or {}).get("data") or {}
    token = d.get("accessToken") or d.get("token")
    if not token:
        raise SystemExit(f"登录失败：{r.text[:200]}")
    H["Authorization"] = f"Bearer {token}"
    return u["username"]


def scores(q: str) -> list[float]:
    r = C.get(f"{BASE}/kb/search", params={"q": q, "mode": "vector",
                                           "threshold": 0, "topk": 200}, headers=H)
    rows = (r.json() or {}).get("data") or []
    out = []
    for row in rows:
        s = row.get("score")
        if s is not None:
            out.append(float(s))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", nargs="*", default=None)
    ap.add_argument("--provider", default=None, help="仅用于报告展示，如 local / http(bge-m3)")
    args = ap.parse_args(argv)

    user = login()
    probe = C.get(f"{BASE}/kb/store", headers=H).json().get("data") or {}
    provider = args.provider or probe.get("embeddingProvider") or probe.get("embedding-provider") or "?"
    print(f"[INFO] 登录 {user}；库内 provider={provider} dims={probe.get('embeddingDims')}")

    qs = args.queries or DEFAULT_QUERIES
    all_scores: list[float] = []
    tops: list[float] = []
    print(f"\n{'查询':<28}{'命中':>5}{'最高':>8}{'中位':>8}{'≥0.5':>7}")
    for q in qs:
        ss = scores(q)
        all_scores.extend(ss)
        if ss:
            tops.append(max(ss))
        ge = sum(1 for s in ss if s >= 0.5)
        med = statistics.median(ss) if ss else 0.0
        print(f"{q[:26]:<28}{len(ss):>5}{max(ss) if ss else 0:>8.3f}{med:>8.3f}{ge:>7}")

    if not all_scores:
        print("\n[结论] 一条向量命中都没有：库里没有切片，或 provider 维度与存量向量不一致"
              "（换 provider 后必须 reembed-on-start=true 重算，否则余弦恒 0）。")
        return 1

    p50 = statistics.median(all_scores)
    p90 = statistics.quantiles(all_scores, n=10)[-1] if len(all_scores) >= 10 else max(all_scores)
    pass_rate = sum(1 for s in all_scores if s >= 0.5) / len(all_scores)
    suggest = round(min(tops) * 0.9, 2) if tops else 0.0
    print(f"\n分布：中位 {p50:.3f} / P90 {p90:.3f} / 最大 {max(all_scores):.3f}；"
          f"≥0.5 占 {pass_rate * 100:.1f}%")
    print(f"建议阈值（能保住每个问句的 top1）：{suggest}")
    if pass_rate < 0.05:
        print("\n[结论] 当前 provider 的余弦分整体远低于 0.5 ⇒ 向量腿**实质失效**（这就是 local 的表现）。"
              "\n       换语义 embedding 后重跑本脚本再定阈值："
              "\n       AIOS_KB_EMBEDDING_PROVIDER=http AIOS_KB_EMBEDDING_URL=http://<host>:11434/api/embeddings"
              "\n       AIOS_KB_EMBEDDING_MODEL=bge-m3 AIOS_KB_EMBEDDING_DIMS=1024 AIOS_KB_REEMBED_ON_START=true")
    elif pass_rate > 0.95:
        print("\n[结论] 阈值 0.5 几乎不拦任何片段 ⇒ 偏松，建议上调到 " + str(round(p50, 2)) + " 以上。")
    else:
        print(f"\n[结论] 分布健康。若默认 0.5 与建议值相差 >0.15，请在专家设置 threshold 里改成 {suggest}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
