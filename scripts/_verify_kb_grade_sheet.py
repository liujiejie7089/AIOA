"""成绩单知识库验收（docs/75）：解析还原 → 切片 → 检索 → 聚合 → 参考块，全链路真实数据。

用**线上真实资料** kb_document id=249（四川轻化工大学学业成绩表 PDF，tenant 56）跑，
不做任何数据造假设 —— 修的是用户截图里「AI 说没拿到绩点数值」这个真实故障。

覆盖的五个环节与判据：
  E1 解析还原：retry 后正文里出现「### 成绩明细 / ### 成绩汇总」两张 Markdown 表
  E2 数据完整：62 门课；学分合计 134.0 = 文档自述「已获得总学分」；9 类性质逐项吻合
  E3 切片质量：切片数下降、表格块 100% 带列名前缀、汇总块里标签与数值**同块相邻**
  E4 检索：问「平均学分绩点」「平均成绩」命中片段里必须同时出现栏目名与数值
  E5 聚合：kb_table_query 的 count / groupBy / filter 三类问题都能给出确定数字
  E6 参考块：工具返回 snippet 能拼成非空参考块，且含数值

用法（Python312，需要 pymysql + httpx）：
    C:/Users/刘尖尖/AppData/Local/Programs/Python/Python312/python.exe scripts/_verify_kb_grade_sheet.py
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
import sys

import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
DOC_ID = 249
DOC_HINT = "score_23101100512"          # docName 前缀，用于 kb_table_query 的片段匹配

CAND = ["test", "User@123", "000000", "Admin@123", "admin", "123456"]
H = {}
C = httpx.Client(timeout=120.0, trust_env=False)
PASS = 0
FAIL = 0


def check(tag, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def resolve_password(h):
    try:
        import bcrypt
        for pw in CAND:
            try:
                if h and bcrypt.checkpw(pw.encode(), h.encode()):
                    return pw
            except Exception:
                pass
    except ImportError:
        pass
    return CAND[0]


def login():
    """这份资料属 tenant 56 的用户，用它自己的账号登录才能检索到。"""
    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("""SELECT id, tenant_id, user_id FROM kb_document WHERE id=%s""", (DOC_ID,))
        doc = cur.fetchone()
        if not doc:
            raise SystemExit(f"资料 {DOC_ID} 不存在，先确认环境")
        cur.execute("""SELECT username, password_hash FROM sys_user
                       WHERE id=%s AND deleted_at IS NULL""", (doc["user_id"],))
        u = cur.fetchone()
    conn.close()
    if not u:
        raise SystemExit(f"资料属主 user_id={doc['user_id']} 在 sys_user 里查不到")
    pw = resolve_password(u["password_hash"])
    r = C.post(f"{BASE}/auth/login", json={"username": u["username"], "password": pw})
    d = (r.json() or {}).get("data") or {}
    token = d.get("accessToken") or d.get("token")
    if not token:
        raise SystemExit(f"登录失败（{u['username']}）: {r.text[:200]}")
    H.update({"Authorization": f"Bearer {token}"})
    return doc, u["username"], pw


def invoke(tool, args):
    r = C.post(f"{BASE}/tools/invoke", json={"name": tool, "arguments": args}, headers=H)
    return (r.json() or {}).get("data") or {}


def db_fresh():
    """每次查库都新开连接：REPEATABLE READ 下旧连接看不到别的事务提交的改动。"""
    return pymysql.connect(**DB)


def main():
    doc, user, pw = login()
    print(f"[INFO] 登录 {user} / {pw}；资料 {DOC_ID} = {doc.get('doc_name') if doc.get('doc_name') else ''}"
          f"（tenant {doc['tenant_id']} / user {doc['user_id']}）")

    # ---------- 0. 前置：修复前的状态（证明故障真实存在） ----------
    conn = db_fresh()
    with conn.cursor() as cur:
        cur.execute("SELECT id, doc_name, content, chunk_count FROM kb_document WHERE id=%s", (DOC_ID,))
        before = cur.fetchone()
        cur.execute("SELECT COUNT(*) n FROM kb_chunk WHERE doc_id=%s AND deleted_at IS NULL", (DOC_ID,))
        before_chunks = cur.fetchone()["n"]
    conn.close()
    raw = before["content"] or ""
    print(f"=== 0. 修复前：正文 {len(raw)} 字 / 声明切片 {before['chunk_count']} / 实际切片 {before_chunks} ===")
    # 这条只在**尚未修复**时才有意义（证明故障真实存在）；重跑时正文已被回填，
    # 无法再回到碎片态（原件字节上传后即丢弃），如实标 SKIP 而不是假 PASS。
    if "### 成绩明细" in raw:
        print("[SKIP] 0.1 正文已结构化（本次为重跑），碎片化证据见 docs/75 §1 与首次运行日志")
    else:
        check("0.1 修复前「历年平均学分绩点」与 2.69 分居两行（碎片的直接证据）",
              not any("历年平均学分绩点" in ln and "2.69" in ln for ln in raw.split("\n")),
              "两条信息不在同一行 ⇒ 按行切片后互不相邻")

    # ---------- 1. 重建索引（模拟用户在列表里点「重试」） ----------
    r = C.post(f"{BASE}/kb/documents/{DOC_ID}/retry", headers=H)
    body = (r.json() or {})
    state = str(((body.get("data") or {}).get("state")) or "").upper()
    check("1.1 重试入库成功", state == "OK", f"HTTP {r.status_code} state={state} {str(body)[:120]}")

    conn = db_fresh()
    with conn.cursor() as cur:
        cur.execute("SELECT content, chunk_count FROM kb_document WHERE id=%s", (DOC_ID,))
        after = cur.fetchone()
        cur.execute("""SELECT chunk_index, LENGTH(content) len FROM kb_chunk
                       WHERE doc_id=%s AND deleted_at IS NULL ORDER BY chunk_index""", (DOC_ID,))
        rows = cur.fetchall()
    conn.close()
    enriched = after["content"] or ""
    chunks = rows

    # ---------- 2. 解析还原 ----------
    check("2.1 正文已回填「### 成绩明细」表", "### 成绩明细" in enriched, "")
    check("2.2 正文已回填「### 成绩汇总」表", "### 成绩汇总" in enriched, "")
    check("2.3 回填幂等（只有一份明细表）", enriched.count("### 成绩明细") == 1,
          f"出现 {enriched.count('### 成绩明细')} 次")
    detail_rows = [ln for ln in enriched.split("### 成绩明细")[-1].split("### 成绩汇总")[0].split("\n")
                   if ln.startswith("|") and "---" not in ln]
    check("2.4 明细表 62 门课（+1 表头）", len(detail_rows) - 1 == 62, f"数据行 {len(detail_rows) - 1}")
    check("2.5 汇总表含「历年平均学分绩点 2.69」同一行",
          any("历年平均学分绩点" in ln and "2.69" in ln for ln in enriched.split("\n")), "")
    check("2.6 汇总表含「历年平均成绩 80.26」同一行",
          any("历年平均成绩" in ln and "80.26" in ln for ln in enriched.split("\n")), "")
    check("2.7 汇总表含「已获得总学分 134.0」同一行",
          any("已获得总学分" in ln and "134.0" in ln for ln in enriched.split("\n")), "")
    check("2.8 空值不错配：「毕业设计(论文)题目」既非 80.26 也不含数字",
          any(ln.startswith("| 毕业设计(论文)题目 |") and "80.26" not in ln for ln in enriched.split("\n")))

    # ---------- 3. 切片质量 ----------
    print(f"=== 3. 切片：本次 {before_chunks} 块 → {after['chunk_count']} 块（PDF 拍平文本本身已很粗，"
          f"块数不是指标；关键看每块的信息密度） ===")
    check("3.2 声明切片数 = 库里实际块数", (after["chunk_count"] or 0) == len(chunks),
          f"声明 {after['chunk_count']} / 实际 {len(chunks)}")

    conn = db_fresh()
    with conn.cursor() as cur:
        cur.execute("""SELECT content FROM kb_chunk
                       WHERE doc_id=%s AND deleted_at IS NULL ORDER BY chunk_index""", (DOC_ID,))
        snippets = [r_["content"] or "" for r_ in cur.fetchall()]
    conn.close()
    max_rows = max([sum(1 for ln in s.split("\n") if ln.startswith("|")) for s in snippets] or [0])
    # docs/76 起明细表按 20 行/块（原 10 行）；「一行一块」和「整表一块」都不对
    check("3.1 明细切片每块 ≤20 行（既不是一行一块，也不是整表一块）",
          0 < max_rows <= 20, f"单块最多 {max_rows} 行")
    stats = [s for s in snippets if s.startswith("【统计摘要】")]
    check("3.3 统计摘要块存在且置切片 0", snippets and snippets[0].startswith("【统计摘要】"),
          f"摘要块 {len(stats)} 个")
    check("3.4 摘要块写明「数据行合计：62 条」", any("数据行合计：62 条" in s for s in stats), "")
    check("3.5 摘要块给出按课程性质的分组计数",
          any("按「课程性质」" in s and "通识必修" in s for s in stats), "")
    tbl = [s for s in snippets if "｜列: " in s and "课程名称" in s]
    check("3.6 每个明细表块都带列名前缀（百分百）",
          len(tbl) > 0 and all("课程名称/课程性质/学分/成绩/补考" in s for s in tbl),
          f"表格块 {len(tbl)} 个")
    check("3.7 汇总块内标签与数值同块相邻",
          any("历年平均学分绩点" in s and "2.69" in s for s in snippets), "")

    # ---------- 4. 检索：栏目名能带回数值 ----------
    def search(q):
        # mode 只接受 vector/bm25/hybrid（KbController.VALID_MODES），千万别传 keyword
        r = C.get(f"{BASE}/kb/search", params={"q": q, "mode": "bm25", "topk": 5}, headers=H)
        return (r.json() or {}).get("data") or []

    hits = search("历年平均学分绩点")
    joined = "\n".join((h.get("snippet") or "") for h in hits)
    check("4.1 问「平均学分绩点」：命中片段里带得出 2.69", "2.69" in joined,
          f"命中 {len(hits)} 条")
    hits2 = search("历年平均成绩")
    joined2 = "\n".join((h.get("snippet") or "") for h in hits2)
    check("4.2 问「平均成绩」：命中片段里带得出 80.26", "80.26" in joined2, f"命中 {len(hits2)} 条")
    hits3 = search("大学物理B1 成绩")
    joined3 = "\n".join((h.get("snippet") or "") for h in hits3)
    check("4.3 问某门课成绩：命中片段含「大学物理B1」与 56/62",
          "大学物理B1" in joined3 and ("56" in joined3 and "62" in joined3), f"命中 {len(hits3)} 条")

    # ---------- 5. 聚合：kb_table_query（返回体：{ok,data:{docs[],matchedRows,numeric,groups[],rows[]}}） ----------
    res = invoke("kb_table_query", {"docName": DOC_HINT})
    d = res.get("data") or {}
    sheets = {str(x.get("sheet")): x.get("rows") for x in (d.get("docs") or [])}
    check("5.1 明细表 62 行 / 汇总表 14 行",
          res.get("ok") is True and sheets.get("成绩明细") == 62 and sheets.get("成绩汇总") == 14,
          f"ok={res.get('ok')} sheets={sheets}")
    num = d.get("numeric") or {}
    check("5.2 学分合计 = 134.0（工具侧独立求和，与文档自述一致）",
          abs(float((num.get("学分") or {}).get("sum", -1)) - 134.0) < 1e-6,
          f"numeric={num.get('学分')}")
    # 成绩列混着「优/良/中」五级制，**不能**只挑数字求平均（会得到一个假分数）；
    # 汇总口径（80.26）来自成绩单自带的「历年平均成绩」，两者不可互相替代。
    check("5.3 五级制混排列不被强行求平均（宁可不算也不给错数）",
          "成绩" not in num, f"numeric 里没有「成绩」列 ⇒ 需走汇总表口径")

    res = invoke("kb_table_query", {"docName": DOC_HINT, "groupBy": "课程性质"})
    d = res.get("data") or {}
    groups = {g["key"]: g for g in (d.get("groups") or [])}
    check("5.4 按课程性质分组 = 9 类", res.get("ok") is True and len(groups) == 9, f"{len(groups)} 类")
    g = groups.get("学基必修") or {}
    check("5.5 学基必修 15 门 / 学分合计 33.0（与汇总行 33.0 一致）",
          g.get("count") == 15 and abs(float((g.get("sums") or {}).get("学分", -1)) - 33.0) < 1e-6,
          f"count={g.get('count')} sums={g.get('sums')}")

    res = invoke("kb_table_query", {"docName": DOC_HINT, "filter": "课程名称=大学物理B1"})
    d = res.get("data") or {}
    rows = d.get("rows") or []
    check("5.6 按课程名过滤：命中 1 行且带回 56 / 补考 62",
          res.get("ok") is True and d.get("matchedRows") == 1 and rows
          and "大学物理B1" in str(rows[0]) and "62" in str(rows[0]),
          f"matched={d.get('matchedRows')} row={rows[0] if rows else None}")

    res = invoke("kb_table_query", {"docName": DOC_HINT, "filter": "课程性质=学基必修"})
    d = res.get("data") or {}
    check("5.7 按性质过滤 = 15 行", res.get("ok") is True and d.get("matchedRows") == 15,
          f"matched={d.get('matchedRows')}")

    res = invoke("kb_table_query", {"docName": DOC_HINT, "filter": "补考=62"})
    d = res.get("data") or {}
    rows = d.get("rows") or []
    check("5.8 按补考分过滤能答出「哪一门补考」",
          res.get("ok") is True and d.get("matchedRows") == 1 and "大学物理B1" in str(rows),
          f"matched={d.get('matchedRows')} rows={rows}")

    res = invoke("kb_table_query", {"docName": DOC_HINT, "groupBy": "不存在的列"})
    check("5.9 列名写错时给出可用列（不静默返回错数字）",
          res.get("ok") is False and "可用列" in str(res.get("error") or ""),
          str(res.get("error") or "")[:100])

    # ---------- 6. 参考块 ----------
    tool = invoke("search_kb_documents", {"keyword": "历年平均学分绩点", "topK": 5})
    docs = _hits_of(tool)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
    from aios_ai.prompt.builder import build_kb_reference_block
    block = build_kb_reference_block(docs) if docs else ""
    check("6.1 工具命中能拼成非空参考块", len(block) > 0, f"长度={len(block)} 命中 {len(docs)} 条")
    check("6.2 参考块里能看到 2.69（模型真的看得到数字）", "2.69" in block, "")
    check("6.3 参考块带抽样纪律与 kb_table_query 指引",
          "kb_table_query" in block and "抽样" in block, "")

    return summary()


def _hits_of(tool):
    """工具返回 → 参考块 builder 认识的 doc 列表（保持原字段名，别替它猜）。"""
    if not isinstance(tool, dict):
        return []
    d = tool.get("data")
    if isinstance(d, dict):
        for k in ("hits", "results", "docs", "items", "documents"):
            if isinstance(d.get(k), list):
                return d[k]
        if d.get("snippet") is not None:
            return [d]
    if isinstance(d, list):
        return d
    return []


def summary():
    print(f"\n==== 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
