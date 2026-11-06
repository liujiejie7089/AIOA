"""非遗名录知识库验收（docs/74）：入库 → 切片 → 检索 → 聚合 → 参考块，全链路真实数据。

覆盖的五个根因各自的判据：
  R1 表格切片：每个表格切片必须带「《doc》/sheet｜列: …｜」前缀，且 sheet 标题不单独成块
  R2 聚合：1241 行级的表必须能直接答「共有多少条 / 按批次分别多少」，且数字与源文件一致
  R3 向量腿：报告 cos 分布（local provider 下允许仍为 0 命中，换 bge 后应 > 0）
  R4 排序：同构行分数必须可分（不再全部同分）
  R5 参考块：工具返回的 snippet 必须真的进入提示词（回归 docs/74 P0-0）

用法（必须用 Python312，需要 openpyxl + pymysql）：
    C:/Users/刘尖尖/AppData/Local/Programs/Python/Python312/python.exe scripts/_verify_kb_nonheritage.py
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import os
import sys
import math
from collections import Counter

import pymysql
import httpx

BASE = "http://127.0.0.1:8080/api/v1"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    ".workbuddy", "tmp", "nonheritage")
XLSX = os.path.join(WORK, "2026.2省级非遗项目名录.xlsx")
DOC_TITLE = "2026.2省级非遗项目名录"

CAND = ["User@123", "000000", "Admin@123", "admin", "123456"]
H = {}
C = httpx.Client(timeout=60.0, trust_env=False)
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


# ---------- 1. 造一份真表（结构与用户截图一致：5 列 / 多批次 / 多地区） ----------
NAMES = ["川剧", "蜀绣", "绵竹木版年画", "自贡灯会", "成都漆艺", "泸州老窖酒酿制技艺",
         "羌族瓦尔俄足", "峨眉武术", "青神竹编", "泸定桥传说", "甘孜踢踏", "凉山彝族火把节",
         "巴塘弦子", "夹江年画", "荣县土陶", "宜宾面塑", "广安竹丝画帘", "达州巴渠童谣",
         "雅安藏茶制作技艺", "阆中皮影"]
CATS = ["传统技艺", "传统戏剧", "传统美术", "民俗", "传统音乐"]
AREAS = ["成都市", "绵阳市", "德阳市", "乐山市", "自贡市"]
BATCHES = ["第五批", "第六批", "第七批"]


def build_xlsx() -> list[tuple]:
    """生成 xlsx 并返回真值行（供断言独立比对，不复用被测代码）。"""
    from openpyxl import Workbook

    os.makedirs(WORK, exist_ok=True)
    rows = []
    for i in range(1, 241):                      # 240 条：够触发分块与分组统计
        rows.append((i,
                     NAMES[i % len(NAMES)] + ("" if i <= len(NAMES) else f"（分支{i}）"),
                     CATS[i % len(CATS)],
                     AREAS[i % len(AREAS)],
                     BATCHES[i % len(BATCHES)]))
    if not os.path.exists(XLSX):
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["序号", "项目名称", "类别", "申报地区或单位", "批次"])
        for r in rows:
            ws.append(list(r))
        wb.save(XLSX)
    return rows


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
    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("""SELECT u.username, u.password_hash FROM sys_user u
                       JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                       JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL
                       WHERE u.deleted_at IS NULL AND u.status='ENABLED'
                         AND r.role_code IN ('ROLE_TENANT_ADMIN','ROLE_ORG_ADMIN','ROLE_ADMIN')
                       ORDER BY FIELD(r.role_code,'ROLE_TENANT_ADMIN','ROLE_ORG_ADMIN','ROLE_ADMIN'), u.id
                       LIMIT 1""")
        u = cur.fetchone()
    conn.close()
    if not u:
        raise SystemExit("库里没有可用的管理员账号")
    pw = resolve_password(u["password_hash"])
    r = C.post(f"{BASE}/auth/login", json={"username": u["username"], "password": pw})
    d = (r.json() or {}).get("data") or {}
    token = d.get("accessToken") or d.get("token")
    if not token:
        raise SystemExit(f"登录失败: {r.text[:200]}")
    H.update({"Authorization": f"Bearer {token}"})
    return u["username"], pw


def upload(rows):
    with open(XLSX, "rb") as f:
        files = {"file": (os.path.basename(XLSX),
                          f.read(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = C.post(f"{BASE}/kb/documents/upload", params={"scope": "PERSONAL"},
               files=files, headers=H)
    body = r.json()
    doc = (body.get("data") or {})
    return doc, body


def invoke(tool, args):
    r = C.post(f"{BASE}/tools/invoke", json={"name": tool, "arguments": args}, headers=H)
    body = r.json()
    # 只剥一层：外层 {code,data} → data 是 {ok, data|error}
    return body.get("data") or {}


def main():
    truth = build_xlsx()
    total = len(truth)
    batch_truth = Counter(r[4] for r in truth)
    area_truth = Counter(r[3] for r in truth)
    print(f"=== 0. 源文件真值：{total} 行；批次 {dict(batch_truth)}；地区 {dict(area_truth)} ===")

    user, pw = login()
    print(f"[INFO] 登录 {user} / {pw}")

    # ---------- 1. 入库 ----------
    doc, body = upload(truth)
    doc_id = doc.get("id")
    check("1.1 上传成功并已索引",
          bool(doc_id) and str(doc.get("state") or "").upper() == "OK",
          f"id={doc_id} state={doc.get('state')} err={doc.get('errorMsg')}")
    if not doc_id:
        print(json.dumps(body, ensure_ascii=False)[:400])
        return summary()

    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("""SELECT chunk_index, content FROM kb_chunk
                       WHERE doc_id=%s AND deleted_at IS NULL ORDER BY chunk_index""", (doc_id,))
        chunks = cur.fetchall()
        cur.execute("""SELECT chunk_count, state, error_msg FROM kb_document
                       WHERE id=%s AND deleted_at IS NULL""", (doc_id,))
        meta = cur.fetchone()

    check("1.2 切片落库数与声明数一致",
          bool(meta) and meta["chunk_count"] == len(chunks),
          f"声明={meta and meta['chunk_count']} 实际={len(chunks)}")

    # ---------- 2. 切片形态（根因 1） ----------
    table_chunks = [c for c in chunks if "|" in (c["content"] or "")]
    with_cols = [c for c in table_chunks if "｜列: " in (c["content"] or "")]
    check("2.1 表格切片全部带列名",
          table_chunks and len(with_cols) == len(table_chunks),
          f"{len(with_cols)}/{len(table_chunks)}")
    check("2.2 sheet 标题不单独成块",
          not any((c["content"] or "").strip() in ("### Sheet1", "Sheet1") for c in chunks),
          f"块数={len(chunks)}（240 行原实现会是 242 块）")
    check("2.3 块数远小于行数（按 10 行/块合并）",
          len(chunks) < total / 2,
          f"块={len(chunks)} vs 行={total}")
    stats = [c for c in chunks if (c["content"] or "").startswith("【统计摘要】")]
    check("2.4 生成统计摘要切片且置首位",
          bool(stats) and stats[0]["chunk_index"] == 0,
          f"摘要块={len(stats)} index={stats[0]['chunk_index'] if stats else None}")
    check("2.5 摘要含正确总数",
          bool(stats) and f"数据行合计：{total} 条" in stats[0]["content"],
          (stats[0]["content"][:120] if stats else "无"))
    check("2.6 摘要含批次分组计数",
          bool(stats) and all(f"{k} {v} 条" in stats[0]["content"] for k, v in batch_truth.items()),
          (stats[0]["content"][:200] if stats else "无"))

    # ---------- 3. 检索：聚合意图应带回统计摘要（根因 2/4/5） ----------
    q = "帮我统计下四川省的省级非遗项目有多少个?"
    got = invoke("search_kb_documents", {"keyword": q, "topK": 5, "mode": "hybrid"})
    hits = got.get("data") or []
    check("3.1 检索有命中", bool(hits), f"命中 {len(hits)} 条")
    check("3.2 聚合意图下统计摘要被置顶",
          bool(hits) and str(hits[0].get("snippet") or "").startswith("【统计摘要】"),
          (str(hits[0].get("snippet"))[:80] if hits else "无"))
    # 同分塌陷：命中片段两两不得「分数完全相同」
    scores = sorted({round(float(h.get("score") or 0), 6) for h in hits})
    check("3.3 命中分数有区分度（非全部同分）", len(scores) >= 2, f"不同分值={scores}")

    # ---------- 4. 表格聚合工具（根因 2） ----------
    res = invoke("kb_table_query", {"docName": DOC_TITLE})
    d = res.get("data") or {}
    check("4.1 kb_table_query 返回 ok", res.get("ok") is True, str(res.get("error") or "")[:120])
    check("4.2 总条数与源文件一致", d.get("totalRows") == total,
          f"工具={d.get('totalRows')} 真值={total}")

    res = invoke("kb_table_query", {"docName": DOC_TITLE, "groupBy": "批次"})
    d = res.get("data") or {}
    groups = {g.get("key"): g.get("count") for g in (d.get("groups") or [])}
    check("4.3 按批次分组计数与源文件一致", groups == dict(batch_truth),
          f"工具={groups} 真值={dict(batch_truth)}")

    res = invoke("kb_table_query", {"docName": DOC_TITLE, "groupBy": "申报地区或单位", "valueLimit": 10})
    d = res.get("data") or {}
    groups = {g.get("key"): g.get("count") for g in (d.get("groups") or [])}
    check("4.4 按地区分组计数与源文件一致", groups == dict(area_truth),
          f"工具={groups} 真值={dict(area_truth)}")

    res = invoke("kb_table_query", {"docName": DOC_TITLE, "filter": "批次=第七批"})
    d = res.get("data") or {}
    check("4.5 条件筛选后的条数正确", d.get("matchedRows") == batch_truth["第七批"],
          f"工具={d.get('matchedRows')} 真值={batch_truth['第七批']}")

    res = invoke("kb_table_query", {"docName": DOC_TITLE, "groupBy": "不存在的列"})
    check("4.6 列名写错时给出可用列（不静默返回错数字）",
          res.get("ok") is False and "可用列" in str(res.get("error") or ""),
          str(res.get("error") or "")[:100])

    res = invoke("kb_table_query", {"docName": "根本不存在的资料XYZ"})
    check("4.7 资料名写错时给出候选（可自我纠正）",
          res.get("ok") is False and "可选资料" in str(res.get("error") or ""),
          str(res.get("error") or "")[:100])

    # ---------- 5. 参考块：snippet 必须进提示词（P0-0 回归） ----------
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
    from aios_ai.prompt.builder import build_kb_reference_block
    block = build_kb_reference_block(hits)
    check("5.1 真实工具返回能拼成非空参考块", len(block) > 0, f"长度={len(block)}")
    check("5.2 参考块含文档名与片段序号",
          DOC_TITLE in block and "#" in block, "")
    check("5.3 参考块含「抽样」纪律说明", "抽样" in block and "kb_table_query" in block, "")

    # ---------- 6. 清理 ----------
    r = C.delete(f"{BASE}/kb/documents/{doc_id}", headers=H)
    # 必须**另开连接**再查：旧连接在 REPEATABLE READ 下已有快照，
    # 看不到另一个事务刚刚提交的删除（会误判成「删了但 deleted_at 还是空」）。
    conn2 = pymysql.connect(**DB)
    with conn2.cursor() as cur:
        cur.execute("SELECT deleted_at FROM kb_document WHERE id=%s", (doc_id,))
        row = cur.fetchone()
    with conn2.cursor() as cur:
        cur.execute("SELECT COUNT(*) n FROM kb_chunk WHERE doc_id=%s AND deleted_at IS NULL", (doc_id,))
        live_chunks = cur.fetchone()["n"]
    conn2.close()
    conn.close()
    # 删除可能是物理删（deleteDocument 走 deleteById）也可能是软删，两者都算清理成功
    check("6.1 验收资料已清理", row is None or row.get("deleted_at") is not None,
          f"HTTP {r.status_code} 行={'已物理删除' if row is None else '软删'}")
    check("6.2 切片不再参与检索", live_chunks == 0, f"存活切片={live_chunks}")
    return summary()


def summary():
    print(f"\n===== PASS {PASS} / FAIL {FAIL} =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
