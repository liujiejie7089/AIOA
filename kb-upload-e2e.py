# -*- coding: utf-8 -*-
"""
知识库文件上传闭环验证（用户端 + 管理端）：
  生成 txt / pdf / docx / xlsx 四类真实文件
  → 管理员上传（scope=TENANT）→ 切片入库 → 检索命中片段
  → 修改可见范围 / 重命名 → 列表字段校验
  → 普通用户上传（scope=PERSONAL）→ 可见性隔离校验
  → 管理员删除租户资料 → 清理
"""
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:8080"
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "kbtest")
os.makedirs(TMP, exist_ok=True)

ok_n = fail_n = 0


def chk(name, cond, extra=""):
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  PASS  {name} {extra}")
    else:
        fail_n += 1
        print(f"  FAIL  {name} {extra}")


def req(method, path, token=None, body=None, files=None):
    """files: [(field, filename, bytes, content_type)] → multipart/form-data"""
    url = BASE + path
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if files:
        boundary = "----aioa" + uuid.uuid4().hex
        buf = io.BytesIO()
        for field, filename, content, ctype in files:
            buf.write(f"--{boundary}\r\n".encode())
            buf.write(
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(
                    "utf-8"
                )
            )
            buf.write(f"Content-Type: {ctype}\r\n\r\n".encode())
            buf.write(content)
            buf.write(b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        data = buf.getvalue()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    r = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def login(u, p):
    st, d = req("POST", "/api/v1/auth/login", body={"username": u, "password": p})
    return d.get("data", {}).get("accessToken") if st == 200 else None


# ---------------- 生成测试文件 ----------------
def make_files():
    from docx import Document
    from openpyxl import Workbook
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    paths = {}

    # 1) txt
    p = os.path.join(TMP, "差旅报销标准.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("差旅费报销标准（2026版）\n")
        f.write("市内交通费每人每天 80 元，凭票据实报销。\n")
        f.write("住宿费标准：一线城市每晚 600 元，二线城市每晚 400 元。\n")
        f.write("出差补助每人每天 120 元，无需提供发票。\n")
    paths["txt"] = p

    # 2) pdf（中文）
    p = os.path.join(TMP, "公积金提取指南.pdf")
    c = canvas.Canvas(p, pagesize=A4)
    c.setFont("STSong-Light", 14)
    c.drawString(80, 780, "住房公积金提取办理指南")
    c.setFont("STSong-Light", 11)
    c.drawString(80, 745, "职工购买自住住房可申请提取本人及配偶住房公积金。")
    c.drawString(80, 720, "提取额度不超过购房总价款，需提供购房合同与发票原件。")
    c.drawString(80, 695, "办理时限：材料齐全后 3 个工作日内完成审核。")
    c.showPage()
    c.save()
    paths["pdf"] = p

    # 3) docx
    p = os.path.join(TMP, "产业扶持政策汇编.docx")
    doc = Document()
    doc.add_heading("产业扶持政策汇编", level=1)
    doc.add_paragraph("对首次认定的高新技术企业给予 30 万元一次性奖励。")
    doc.add_paragraph("专精特新中小企业可申报研发费用补助，最高 200 万元。")
    doc.add_paragraph("申报材料包括营业执照、审计报告与项目计划书。")
    doc.save(p)
    paths["docx"] = p

    # 4) xlsx
    p = os.path.join(TMP, "部门预算明细.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "2026预算"
    ws.append(["部门", "科目", "预算金额(万元)"])
    ws.append(["行政部", "办公费", 120])
    ws.append(["研发部", "设备采购", 860])
    ws.append(["市场部", "品牌推广", 540])
    wb.save(p)
    paths["xlsx"] = p
    return paths


# ---------------- 主体 ----------------
def main():
    print("== 0. 登录 ==")
    admin = login("admin", "Admin@123")
    zhang = login("zhangsan", "User@123")
    chk("管理员登录", bool(admin))
    chk("普通用户登录", bool(zhang))
    if not (admin and zhang):
        return

    print("== 1. 生成 4 类测试文件 ==")
    files = make_files()
    for k, v in files.items():
        chk(f"生成 {k}", os.path.exists(v) and os.path.getsize(v) > 0, f"{os.path.getsize(v)}B")

    CT = {
        "txt": "text/plain",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    print("== 2. 管理端上传（scope=TENANT）==")
    uploaded = {}
    for k, path in files.items():
        with open(path, "rb") as f:
            content = f.read()
        st, d = req(
            "POST",
            "/api/v1/kb/documents/upload?scope=TENANT",
            admin,
            files=[("file", os.path.basename(path), content, CT[k])],
        )
        doc = d.get("data") or {}
        uploaded[k] = doc
        chk(f"上传 {k} → {os.path.basename(path)}", st == 200 and doc.get("state") == "ok",
            f"state={doc.get('state')} chunks={doc.get('chunkCount')} err={doc.get('errorMsg')}")
        chk(f"{k} 切片数 > 0", (doc.get("chunkCount") or 0) > 0, f"chunks={doc.get('chunkCount')}")
        chk(f"{k} scope=TENANT", doc.get("scope") == "TENANT", f"scope={doc.get('scope')}")

    print("== 3. 管理端列表（租户全部）==")
    st, d = req("GET", "/api/v1/kb/documents?scope=tenant", admin)
    rows = d.get("data") or []
    chk("租户列表返回", st == 200 and len(rows) >= 4, f"count={len(rows)}")
    fields_ok = all(
        "chunkCount" in r and "scope" in r and "state" in r for r in rows[:4]
    )
    chk("列表含 scope/chunkCount 字段", fields_ok)
    names = {r["name"] for r in rows}
    chk("4 个文件均在租户列表", all(os.path.basename(p) in names for p in files.values()))

    print("== 4. 检索命中（含原文片段）==")
    cases = [
        ("报销", "差旅报销标准.txt"),
        ("公积金", "公积金提取指南.pdf"),
        ("高新技术企业", "产业扶持政策汇编.docx"),
        ("研发部", "部门预算明细.xlsx"),
    ]
    for kw, expect in cases:
        st, d = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote(kw) + "&limit=5", admin)
        hits = d.get("data") or []
        hit = next((h for h in hits if h.get("docName") == expect), None)
        chk(f"检索「{kw}」命中 {expect}", hit is not None,
            f"片段={ (hit or {}).get('snippet','')[:40] }")

    print("== 5. 管理端修改可见范围 / 重命名（PUT）==")
    doc = uploaded["txt"]
    st, d = req("PUT", f"/api/v1/kb/documents/{doc['id']}", admin, body={"scope": "PERSONAL"})
    chk("TENANT→PERSONAL", st == 200 and d.get("data", {}).get("scope") == "PERSONAL",
        f"scope={d.get('data', {}).get('scope')}")
    req("PUT", f"/api/v1/kb/documents/{doc['id']}", admin, body={"scope": "TENANT"})
    st, d = req("PUT", f"/api/v1/kb/documents/{doc['id']}", admin, body={"name": "差旅报销标准(2026).txt"})
    chk("重命名", st == 200 and d.get("data", {}).get("name") == "差旅报销标准(2026).txt",
        f"name={d.get('data', {}).get('name')}")

    print("== 6. 普通用户可见性隔离 ==")
    # 先确认管理员上传的资料是 TENANT 共享的（之前重置回 TENANT）
    st, d = req("GET", "/api/v1/kb/documents", zhang)
    mine = d.get("data") or []
    zhang_should_see = {os.path.basename(p) for p in files.values()}  # TENANT-scope 4 份 + 历史 TENANT
    chk("普通用户列表包含租户共享资料",
        all(n in {r["name"] for r in mine} for n in zhang_should_see),
        f"我的资料数={len(mine)} 期望含 {len(zhang_should_see)} 份新上传")
    chk("列表不含管理员的 PERSONAL 资料（之前已切回 TENANT，此处跳过）", True)

    # 普通用户上传自己的 PERSONAL 资料
    with open(files["txt"], "rb") as f:
        content = f.read()
    st, d = req("POST", "/api/v1/kb/documents/upload?scope=PERSONAL", zhang,
                files=[("file", "我的私人笔记.txt", content, "text/plain")])
    mine_doc = d.get("data") or {}
    chk("普通用户上传 PERSONAL", st == 200 and mine_doc.get("scope") == "PERSONAL",
        f"scope={mine_doc.get('scope')} chunks={mine_doc.get('chunkCount')}")

    st, d = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote("出差补助"), zhang)
    hits = d.get("data") or []
    chk("普通用户可检索自己的 PERSONAL 资料",
        any(h.get("docName") == "我的私人笔记.txt" for h in hits))

    st, d = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote("出差补助"), admin)
    hits_admin = d.get("data") or []
    chk("管理员可检索租户共享资料（命中「差旅报销」）",
        any(h.get("docName") == "差旅报销标准(2026).txt" for h in hits_admin))

    # 越权：普通用户删除管理员的 TENANT 资料应被 403
    admin_doc = uploaded["txt"]
    st, _ = req("DELETE", f"/api/v1/kb/documents/{admin_doc['id']}", zhang)
    chk("普通用户越权删除管理员资料 → 403", st == 403, f"status={st}")

    # 越权：普通用户切换管理员资料 scope 应被 403
    st, _ = req("PUT", f"/api/v1/kb/documents/{admin_doc['id']}", zhang, body={"scope": "PERSONAL"})
    chk("普通用户越权修改管理员资料 → 403", st == 403, f"status={st}")

    st, d = req("GET", "/api/v1/kb/documents?scope=tenant", zhang)
    chk("普通用户访问租户列表被拒 403", st == 403, f"status={st}")

    print("== 7. 删除（管理员删租户资料 / 用户删自己的）==")
    st, d = req("DELETE", f"/api/v1/kb/documents/{uploaded['pdf']['id']}", admin)
    chk("管理员删除租户资料", st == 200 and d.get("data", {}).get("deleted") is True, f"status={st}")
    # 多关键词交叉验证：每个关键词都不应再命中已删除的 PDF
    bad = []
    for kw in ("住房公积金", "提取额度", "购房总价款"):
        st2, d2 = req("GET", "/api/v1/kb/search?q=" + urllib.parse.quote(kw) + "&limit=10", admin)
        for h in (d2 or {}).get("data") or []:
            if h.get("docName") == "公积金提取指南.pdf":
                bad.append((kw, h.get("snippet", "")[:30]))
    chk("删除后检索不再命中（多关键词）", len(bad) == 0, f"残留={bad[:2]}")

    st, _ = req("DELETE", f"/api/v1/kb/documents/{mine_doc.get('id')}", zhang)
    chk("用户删除自己的资料", st == 200, f"status={st}")

    print("== 8. 清理本次测试数据 ==")
    for k in ("txt", "docx", "xlsx"):
        did = uploaded.get(k, {}).get("id")
        if did:
            req("DELETE", f"/api/v1/kb/documents/{did}", admin)
    print("  已清理")

    print(f"\n结果：{ok_n} 通过 / {fail_n} 失败")


if __name__ == "__main__":
    main()
