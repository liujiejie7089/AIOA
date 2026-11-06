"""成绩单「列出全部 62 门」验收（docs/76）：切片策略 + 取行分页 + 端到端枚举。

复现的事故：用户问「把成绩单里所有课程的成绩列出来」，AI 只答出 14 门 / 10 门。
根因有三层，本脚本逐层给判据：

  L1 切片：PDF 拍平正文「一行一块」⇒ 1800 字切 38 块，每块 4 门课且无列名
  L2 取行：kb_table_query 每页硬上限 10 行且**没有翻页参数** ⇒ 结构上拿不全
  L3 口径：一份资料两张表（明细 62 / 汇总 14）并在一起数 ⇒ 62 被「注水」成 76

判据（A=真机接口，B=端到端问答）：
  A1 切片总数 ≤ 15；PDF 拍平正文块 ≤ 5（段落合并生效）
  A2 汇总表整表一块（14 行在同一个切片里，标签与数值不分家）
  A3 明细表分块数 = 4（20+20+20+2），每块 ≤ 20 行且带列名
  A4 kb_table_query 默认页返回 50 行 + hasMore=true
  A5 翻页拼起来 = 62 门，不重不漏
  A6 limit=500 一次取全 62 行，hasMore=false
  A7 matchedRows=62 而不是 76（并按 sheet 能切到汇总表）
  B1 端到端问「列出全部课程成绩」，回答里课程行 ≥ 60 行
  B2 回答里不再出现「只返回了前 N 行 / 其余没有返回」这类半截话

用法（Python312，需要 pymysql + httpx）：
    C:/Users/刘尖尖/AppData/Local/Programs/Python/Python312/python.exe scripts/_verify_kb_grade_enum.py
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pymysql

DOC_ID = 249
DOC_HINT = "score_23101100512"
COURSES = 62

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


def db():
    return pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)


def main():
    from _verify_kb_grade_answer import post, read_sse, extract_answer, BASE

    tok = post(BASE + "/api/v1/auth/login", {"username": "test", "password": "test"})["data"]["accessToken"]

    def tool(**args):
        r = post(BASE + "/api/v1/tools/invoke",
                 {"name": "kb_table_query", "arguments": dict(args, docName=DOC_HINT)}, tok)
        body = (r or {}).get("data") or {}
        return body, (body.get("data") or {})

    # ---------- A. 切片策略 ----------
    conn = db()
    with conn.cursor() as cur:
        cur.execute("SELECT chunk_index, content FROM kb_chunk "
                    "WHERE doc_id=%s AND deleted_at IS NULL ORDER BY chunk_index", (DOC_ID,))
        rows = cur.fetchall()
    conn.close()
    snippets = [r["content"] or "" for r in rows]
    print(f"=== A. 切片：共 {len(snippets)} 块 ===")

    check("A1 切片总数 ≤ 15（PDF 正文不再一行一块）", len(snippets) <= 15, f"{len(snippets)} 块")
    prose = [s for s in snippets if "｜列: " not in s and not s.startswith("【统计摘要】")]
    check("A1b PDF 拍平正文块 ≤ 5（段落合并生效）", len(prose) <= 5, f"{len(prose)} 块")

    summary_chunks = [s for s in snippets if "成绩汇总｜列: 项目/数值" in s]
    check("A2 汇总表整表一块（标签与数值不分家）", len(summary_chunks) == 1,
          f"{len(summary_chunks)} 块")
    if summary_chunks:
        s0 = summary_chunks[0]
        # 首行（毕业设计题目，值为空）与末行（专基必修课 15.0）都在同一块 ⇒ 整表未被切断
        first_ok = "| 毕业设计(论文)题目 | — |" in s0
        last_ok = "| 专基必修课 | 15.0 |" in s0
        check("A2b 汇总块含首行与末行（整表未被切断）", first_ok and last_ok,
              f"首行={first_ok} 末行={last_ok}")
        check("A2c 绩点与数值同块", "历年平均学分绩点" in s0 and "2.69" in s0)

    detail_chunks = [s for s in snippets if "成绩明细｜列: " in s]
    check("A3 明细表切 4 块（20 行/块）", len(detail_chunks) == 4, f"{len(detail_chunks)} 块")
    ok_rows = True
    for s in detail_chunks:
        n = sum(1 for ln in s.split("\n") if ln.startswith("|")) + 1
        if n > 20:
            ok_rows = False
    check("A3b 每块 ≤ 20 行", ok_rows)
    check("A3c 每块都带列名前缀", all("课程名称/课程性质/学分/成绩/补考" in s for s in detail_chunks))

    # ---------- A4-A7. 取行分页 ----------
    print("=== A4-A7. kb_table_query 分页 ===")
    body, d = tool()
    rows1 = d.get("rows") or []
    check("A4 默认页 50 行 + hasMore=true",
          body.get("ok") is True and len(rows1) == 50 and d.get("hasMore") is True,
          f"returned={len(rows1)} hasMore={d.get('hasMore')} next={d.get('nextOffset')}")
    check("A7 matchedRows=62（不含汇总表的 14 行）", d.get("matchedRows") == COURSES,
          f"matched={d.get('matchedRows')} total={d.get('totalRows')} sheet={d.get('sheet')}")
    check("A7b 告知还有汇总表可选", "成绩汇总" in str(d.get("otherSheets") or []),
          str(d.get("otherSheets")))

    body2, d2 = tool(offset=50)
    rows2 = d2.get("rows") or []
    check("A5 第二页 12 行", len(rows2) == 12, f"returned={len(rows2)}")
    check("A5b 第二页末行 = 第 62 门", d2.get("hasMore") is False, f"hasMore={d2.get('hasMore')}")
    names = {r.get("课程名称") for r in rows1} | {r.get("课程名称") for r in rows2}
    names.discard(None)
    check("A5c 两页合计 62 门，不重不漏", len(names) == COURSES, f"去重后 {len(names)} 门")

    body3, d3 = tool(limit=500)
    check("A6 limit=500 一次取全", len(d3.get("rows") or []) == COURSES and d3.get("hasMore") is False,
          f"returned={len(d3.get('rows') or [])}")

    body4, d4 = tool(sheet="成绩汇总")
    check("A7c 按 sheet 切到汇总表", d4.get("sheet") == "成绩汇总"
          and d4.get("matchedRows") == 14 and list(d4.get("columns") or []) == ["项目", "数值"],
          f"sheet={d4.get('sheet')} matched={d4.get('matchedRows')}")

    # ---------- B. 端到端枚举 ----------
    print("=== B. 端到端：让 AI 列出全部课程 ===")
    q = "把成绩单里所有课程的成绩都列出来，一门都别漏。"
    conv = post(BASE + "/api/v1/conversations", {"title": "enum-probe"}, tok)["data"]
    run = post(f"{BASE}/api/v1/conversations/{conv['id']}/runs", {"text": q, "context": {}}, tok)
    sse = read_sse(f"{BASE}/api/v1/runs/{run['data']['runId']}/events", tok)
    ans = extract_answer(sse)
    if not ans.strip():
        check("B1 回答非空", False, "未取到回答（模型未配置？）")
        return summary()

    course_lines = [ln for ln in ans.splitlines()
                    if ln.startswith("|") and re.search(r"必修|选修", ln)]
    print(f"      回答里课程行 = {len(course_lines)}；回答长度 {len(ans)} 字")
    check("B1 课程行 ≥ 60（基本列全）", len(course_lines) >= 60, f"{len(course_lines)} 行")
    bad = ["只返回了前", "其余", "没有返回", "只拿到了这"]
    hit = [b for b in bad if b in ans]
    check("B2 不再出现「只返回了前 N 行」这类半截话", not hit, f"命中：{hit}")
    check("B3 明确给出课程总数 62", "62" in ans, "")
    return summary()


def summary():
    print(f"\n==== 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
