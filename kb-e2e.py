# -*- coding: utf-8 -*-
"""知识库 RAG 闭环验证：上传(txt/xlsx/pdf) → 解析入库 → 检索命中 → 片段溯源 → 删除"""
import json, urllib.parse, urllib.request, os

BASE = "http://127.0.0.1:8080"
ok = fail = 0

def req(method, path, token=None, body=None, form=None):
    url = BASE + path
    headers = {}
    if token: headers["Authorization"] = "Bearer " + token
    data = None
    if form is not None:
        data = form
    elif body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    r = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode("utf-8"))
        except Exception: return e.code, {}

def login(u, p):
    s, d = req("POST", "/api/v1/auth/login", body={"username": u, "password": p})
    assert s == 200 and d.get("code") == 0, f"login fail {s} {d}"
    return d["data"]["accessToken"]

def upload(token, path, filename, scope="PERSONAL"):
    """multipart 上传"""
    boundary = "----aioakbtest"
    with open(path, "rb") as f:
        content = f.read()
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    url = f"{BASE}/api/v1/kb/documents/upload?scope={scope}"
    r = urllib.request.Request(url, method="POST", data=body, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    with urllib.request.urlopen(r, timeout=60) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS {name} {detail}")
    else: fail += 1; print(f"  FAIL {name} {detail}")

admin = login("admin", "Admin@123")
print("== 1. 多格式上传解析入库 ==")

# 生成测试文件
os.makedirs("logs/kbtest", exist_ok=True)
files = {}
# txt
p = "logs/kbtest/政策说明.txt"
open(p, "w", encoding="utf-8").write("小微企业税收优惠政策：月销售额 10 万元以下免征增值税。\n办理渠道：电子税务局或市民之家税务窗口。")
files["txt"] = (p, "政策说明.txt")
# xlsx（用最小 OOXML 手写较麻烦，改用 csv 后缀模拟表格 + 生成 xlsx 通过 openpyxl）
try:
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["事项", "办理时限", "受理窗口"])
    ws.append(["企业开办", "0.5 个工作日", "市民之家企业服务专区"])
    ws.append(["公积金提取", "3 个工作日", "市民之家二楼公积金窗口"])
    p = "logs/kbtest/办事时限表.xlsx"; wb.save(p)
    files["xlsx"] = (p, "办事时限表.xlsx")
except Exception as e:
    print("  (skip xlsx:", e, ")")
# pdf（最小可用 PDF，含可抽取文本）
pdf_src = ("%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
           "/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
           "4 0 obj<</Length 96>>stream\nBT /F1 24 Tf 72 700 Td (Gov Service Guide: housing fund withdrawal in 3 workdays) Tj ET\nendstream endobj\n"
           "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
           "trailer<</Root 1 0 R>>\n")
p = "logs/kbtest/服务指南.pdf"
open(p, "wb").write(pdf_src.encode("latin-1"))
files["pdf"] = (p, "服务指南.pdf")

doc_ids = {}
for kind, (path, name) in files.items():
    s, d = upload(admin, path, name, "TENANT")
    doc = d.get("data") or {}
    check(f"上传 {kind}（{name}）", s == 200 and doc.get("state") == "ok",
          f"state={doc.get('state')} chunks={doc.get('chunkCount')} err={doc.get('errorMsg')}")
    doc_ids[kind] = doc.get("id")

print("== 2. 检索命中与原文片段 ==")
for q, expect in [("税收优惠", "txt"), ("公积金提取", "xlsx"), ("housing fund", "pdf"), ("实体", "docx")]:
    s, d = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote(q) + "&limit=3", admin)
    hits = d.get("data") or []
    hit_ok = len(hits) > 0 and any(h.get("snippet") for h in hits)
    check(f"检索「{q}」命中并带片段", hit_ok,
          f"hits={len(hits)} " + (str(hits[0].get('docName')) if hits else ""))
    if hits and hits[0].get("snippet"):
        print("       片段:", hits[0]["snippet"][:60].replace("\n", " "))

print("== 3. 清单三态与可见范围 ==")
s, d = req("GET", "/api/v1/kb/documents", admin)
docs = d.get("data") or []
check("清单返回资料", len(docs) >= 4, f"count={len(docs)}")
states = {x.get("state") for x in docs}
check("状态字段存在", states.issubset({"ok", "wait", "failed"}), f"states={states}")
check("切片数已回填", any((x.get("chunkCount") or 0) > 0 for x in docs),
      f"chunks={[x.get('chunkCount') for x in docs][:5]}")

print("== 4. 改可见范围与删除 ==")
if doc_ids.get("txt"):
    s, d = req("PUT", f"/api/v1/kb/documents/{doc_ids['txt']}", admin, {"scope": "PERSONAL"})
    check("改为 PERSONAL", (d.get("data") or {}).get("scope") == "PERSONAL", f"scope={(d.get('data') or {}).get('scope')}")
    s, d = req("DELETE", f"/api/v1/kb/documents/{doc_ids['txt']}", admin)
    check("删除资料", s == 200 and (d.get("data") or {}).get("deleted") is True, f"http={s}")
    s, d = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote("税收优惠"), admin)
    check("删除后检索不到", len(d.get("data") or []) == 0, f"hits={len(d.get('data') or [])}")

print(f"\n==== RESULT: {ok} pass / {fail} fail ====")
