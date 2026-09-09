# -*- coding: utf-8 -*-
"""知识库闭环验证：检索命中、工具网关片段、删除、失败重试"""
import json, urllib.parse, urllib.request

BASE = "http://127.0.0.1:8080"
ok = fail = 0

def req(method, path, token, body=None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Authorization", "Bearer " + token)
    if body is not None:
        r.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    else:
        data = None
    try:
        with urllib.request.urlopen(r, data, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {}

def login(u, p):
    s, d = req("POST", "/api/v1/auth/login", None, {"username": u, "password": p})
    return d["data"]["accessToken"]

def check(n, c, d=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS {n} {d}")
    else: fail += 1; print(f"  FAIL {n} {d}")

tok = login("admin", "Admin@123")

print("== A. 知识库检索（FR-F3 / FR-D5） ==")
for kw in ["智能体", "微服务", "PoC"]:
    s, d = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote(kw), tok)
    hits = (d.get("data") or [])
    check(f"检索「{kw}」", s == 200 and len(hits) > 0,
          f"hits={len(hits)}" + (f" 首条片段={hits[0].get('snippet','')[:40]}..." if hits else ""))

print("== B. 工具网关检索（agent 引用溯源数据源） ==")
s, d = req("POST", "/api/v1/tools/invoke", tok, {"name": "search_kb_documents", "arguments": {"keyword": "智能体"}})
rows = (d.get("data") or {}).get("result") if isinstance(d.get("data"), dict) else None
rows = rows if isinstance(rows, list) else (d.get("data") or [])
check("工具调用返回片段", s == 200 and isinstance(rows, list) and len(rows) > 0,
      f"rows={len(rows) if isinstance(rows,list) else 0}")
if isinstance(rows, list) and rows:
    r0 = rows[0]
    check("片段字段 snippet 存在", "snippet" in r0, f"keys={list(r0.keys())[:6]}")
    check("片段内容非空", bool(r0.get("snippet")), f"snippet={(r0.get('snippet') or '')[:40]}...")

print("== C. 清单与三态 ==")
s, d = req("GET", "/api/v1/kb/documents", tok)
docs = d.get("data") or []
check("资料清单", s == 200 and len(docs) > 0, f"count={len(docs)}")
check("状态已入库", any(x.get("state") == "ok" for x in docs),
      f"states={[x.get('state') for x in docs][:5]}")
check("切片数回填", any((x.get("chunkCount") or 0) > 0 for x in docs),
      f"chunks={[x.get('chunkCount') for x in docs][:5]}")

print("== D. 删除与重试 ==")
s, d = req("POST", "/api/v1/kb/documents", tok, {"name": "无正文测试.txt", "icon": "doc", "sizeBytes": 10})
doc_id = (d.get("data") or {}).get("id")
check("登记无正文资料（应为 wait）", (d.get("data") or {}).get("state") == "wait", f"state={(d.get('data') or {}).get('state')}")
if doc_id:
    s, d = req("POST", f"/api/v1/kb/documents/{doc_id}/retry", tok)
    check("无正文重试 → failed 而非 500", s == 200 and (d.get("data") or {}).get("state") == "failed",
          f"state={(d.get('data') or {}).get('state')} msg={(d.get('data') or {}).get('errorMsg')}")
    s, d = req("DELETE", f"/api/v1/kb/documents/{doc_id}", tok)
    check("删除资料", s == 200 and (d.get("data") or {}).get("deleted") is True, f"http={s}")
    s, d = req("GET", "/api/v1/kb/documents", tok)
    check("删除后清单不含该资料", all(x.get("id") != doc_id for x in (d.get("data") or [])))

print(f"\n==== RESULT: {ok} pass / {fail} fail ====")
