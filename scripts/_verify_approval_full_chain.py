# -*- coding: utf-8 -*-
"""费用报销审批全链路 API 探针：提交 -> 用户端各列表 -> 管理端待办 -> 回库核对。

测试目标（用户报障）：
  用户发起审批（如费用报销）后，用户端「我的申请/审批记录」无记录展示，
  管理端未收到对应审批申请。

核心方法（铁律 7/12）：不能只看接口说成功，必须回库核对三套数据源：
  A. approval          —— 单级审批（/v1/approvals）
  B. approval_order    —— 多级审批引擎（/v1/workflow/mine、/v1/workflow/tasks）
  C. form_submission   —— 表单台账（/v1/form-submissions）
"""
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import time
import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=40, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
MARK = "FULLCHAIN-%s" % time.strftime("%m%d%H%M%S")


def login(u, p):
    r = C.post(f"{BASE}/auth/login", json={"username": u, "password": p})
    b = r.json()
    data = b.get("data") or {}
    return data.get("accessToken"), data


def hd(tok):
    return {"Authorization": "Bearer " + tok}


def brief(tag, r, limit=5):
    try:
        b = r.json()
        data = b.get("data")
        if isinstance(data, list):
            print(f"  {tag}: HTTP {r.status_code} code={b.get('code')} len={len(data)}")
            for x in data[:limit]:
                print("      " + json.dumps(x, ensure_ascii=False)[:260])
            return data
        print(f"  {tag}: HTTP {r.status_code} code={b.get('code')} data={json.dumps(data, ensure_ascii=False)[:300]}")
        return data
    except Exception as ex:
        print(f"  {tag}: HTTP {r.status_code} raw={r.text[:200]} ({ex})")
        return None


def db(q, args=None):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(q, args or ())
            return cur.fetchall()
    finally:
        conn.close()


def sample_value(prop):
    """按 schema 给一个合法示例值。"""
    t = prop.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    if prop.get("enum"):
        return prop["enum"][0]  # 枚举字段取合法值，不能拿随机串
    if "x-options-ref" in prop:
        return None  # 由调用方按引用表填
    if t == "integer" or t == "number":
        return 100
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "object":
        return {}
    title = str(prop.get("title", ""))
    if "日期" in title or title in ("start_date", "end_date"):
        return time.strftime("%Y-%m-%d")
    if "原因" in title or "事由" in title or "说明" in title:
        return MARK + " 费用报销全链路测试"
    if "金额" in title:
        return 100
    if "单据" in title or "编号" in title:
        return MARK
    return MARK


print("=" * 70)
print("费用报销审批全链路测试  MARK=" + MARK)
print("=" * 70)

print("\n== 0. 登录 ==")
utok, udata = login("zhangsan", "User@123")
atok, adata = login("dsj_admin", "Admin@123")
print("  用户端 zhangsan:", "OK" if utok else "FAIL")
print("  管理端 dsj_admin:", "OK" if atok else "FAIL")
if not (utok and atok):
    sys.exit(1)
uinfo = udata.get("user") or udata
uid = uinfo.get("userId") or uinfo.get("id")
utid = uinfo.get("tenantId")
print(f"  uid={uid} tenant={utid} roles={uinfo.get('roles')}")

print("\n== 1. 表单配置（DB 真源） ==")
rows = db("""SELECT id, tenant_id, code, name, biz_type, submit_policy, status, version
             FROM form_template WHERE code IN ('expense_form','expense_claim')
             ORDER BY tenant_id, id""")
for r in rows:
    print("   ", json.dumps(r, ensure_ascii=False, default=str))
mine = [r for r in rows if r["code"] == "expense_form" and r["tenant_id"] in (0, utid)]
tpl = next((r for r in mine if r["tenant_id"] == utid), mine[0] if mine else None)
print("  命中模板:", json.dumps(tpl, ensure_ascii=False, default=str) if tpl else "NOT FOUND")
if not tpl:
    sys.exit(1)

schema = json.loads(db("SELECT schema_json FROM form_template WHERE id=%s", (tpl["id"],))[0]["schema_json"])
props = schema.get("properties") or {}
required = schema.get("required") or []
print("  required:", required)
print("  properties:", list(props.keys()))
payload = {}
for key in required:
    if key in ("proof", "attachment", "files"):
        continue
    v = sample_value(props.get(key, {}))
    if v is not None:
        payload[key] = v
if "title" in props and "title" not in payload:
    payload["title"] = MARK + " 费用报销"
print("  提交 payload:", json.dumps(payload, ensure_ascii=False))

print("\n== 2. 提交前三套数据源快照 ==")
before = {}
before["workflow_mine"] = brief("workflow/mine", C.get(f"{BASE}/workflow/mine", headers=hd(utok)))
before["approvals_mine"] = brief("approvals/mine", C.get(f"{BASE}/approvals", params={"scope": "mine"}, headers=hd(utok)))
before["form_subs"] = brief("form-submissions", C.get(f"{BASE}/form-submissions", headers=hd(utok)))
before["admin_todo"] = brief("admin /workflow/tasks?scope=todo", C.get(f"{BASE}/workflow/tasks", params={"scope": "todo"}, headers=hd(atok)))

print("\n== 3. 真实提交费用报销（表单入口） ==")
r = C.post(f"{BASE}/forms/expense_form/submit", headers=hd(utok), json={
    "data": payload, "conversationId": None, "runId": None, "assigneeUserIds": None,
})
sub_resp = brief("POST /forms/expense_form/submit", r)
print("  原始响应:", r.text[:800])

print("\n== 4. 提交后三套数据源（用户端 + 管理端） ==")
after = {}
after["workflow_mine"] = brief("workflow/mine", C.get(f"{BASE}/workflow/mine", headers=hd(utok)))
after["approvals_mine"] = brief("approvals/mine", C.get(f"{BASE}/approvals", params={"scope": "mine"}, headers=hd(utok)))
after["form_subs"] = brief("form-submissions", C.get(f"{BASE}/form-submissions", headers=hd(utok)))
after["admin_todo"] = brief("admin /workflow/tasks?scope=todo", C.get(f"{BASE}/workflow/tasks", params={"scope": "todo"}, headers=hd(atok)))

print("\n== 5. 回库核对 ==")
sub_id = (sub_resp or {}).get("submissionId") if isinstance(sub_resp, dict) else None
print("  submissionId:", sub_id)
if sub_id:
    s = db("SELECT id,tenant_id,code,biz_type,status,approval_order_id,applicant_id,data_json FROM form_submission WHERE id=%s", (sub_id,))
    print("  form_submission:", json.dumps(s, ensure_ascii=False, default=str)[:600])
    oid = s[0].get("approval_order_id") if s else None
    if oid:
        o = db("SELECT id,tenant_id,biz_type,title,status,applicant_id FROM approval_order WHERE id=%s", (oid,))
        t = db("SELECT id,order_id,assignee_id,status FROM approval_task WHERE order_id=%s", (oid,))
        print("  approval_order:", json.dumps(o, ensure_ascii=False, default=str))
        print("  approval_task:", json.dumps(t, ensure_ascii=False, default=str)[:600])
    else:
        print("  approval_order: NONE（未创建审批单）")
        print("  approval_task:  NONE")
else:
    print("  提交未返回 submissionId，按 MARK 反查：")
    hits = db("SELECT id,code,status,approval_order_id,data_json FROM form_submission WHERE data_json LIKE %s ORDER BY id DESC LIMIT 3", (f"%{MARK}%",))
    print("   ", json.dumps(hits, ensure_ascii=False, default=str)[:800])

print("\n== 6. 对照：数字人审批卡提交（单级 /approvals） ==")
r2 = C.post(f"{BASE}/approvals", headers=hd(utok), json={
    "bizType": "EXPENSE", "title": MARK + " 数字人审批卡", "content": "全链路对照测试",
    "runId": None, "conversationId": None, "resultId": None,
})
card = brief("POST /approvals", r2)
wm = C.get(f"{BASE}/workflow/mine", headers=hd(utok)).json().get("data") or []
am = C.get(f"{BASE}/approvals", params={"scope": "mine"}, headers=hd(utok)).json().get("data") or []
print("  -> workflow/mine 含该卡:", any(MARK in json.dumps(x, ensure_ascii=False) for x in wm))
print("  -> approvals/mine 含该卡:", any(MARK in json.dumps(x, ensure_ascii=False) for x in am))

print("\n== 7. 结论 ==")
print("  表单提交回执 status =", (sub_resp or {}).get("status") if isinstance(sub_resp, dict) else "?")
print("  是否创建 approval_order =", bool((sub_resp or {}).get("approvalOrderId")) if isinstance(sub_resp, dict) else "?")
print("  workflow/mine 是否新增 =", len(after["workflow_mine"] or []) - len(before["workflow_mine"] or []))
print("  approvals/mine 是否新增 =", len(after["approvals_mine"] or []) - len(before["approvals_mine"] or []))
print("  form-submissions 是否新增 =", len(after["form_subs"] or []) - len(before["form_subs"] or []))
print("  管理端 todo 是否新增 =", len(after["admin_todo"] or []) - len(before["admin_todo"] or []))
