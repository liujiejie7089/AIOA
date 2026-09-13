"""诊断 #210：用户端提交请假后，机构管理员为何收不到请求。

两条链路对照：
  A) 新链路（多级审批引擎）: POST /api/v1/leave/requests → approval_task + 通知解析出的审批人
  B) 旧链路（用户端 H5 实际在用）: POST /api/v1/approvals → 仅 approval_order + 通知租户管理员

分别检查机构管理员（ORG_ADMIN）能看到什么。
"""
import json

import httpx

BASE = "http://127.0.0.1:8080/api/v1"
MEMBER = ("jybgs_m01", "User@123")      # tenant4 / inst17 / 部门77 普通成员
ORG_ADMIN = ("jyfzyjy_admin", "User@123")  # tenant4 / inst17 ORG_ADMIN (user 3048)
TENANT_ADMIN = ("jyj_admin", "User@123")   # tenant4 租户管理员

cli = httpx.Client(trust_env=False, timeout=20)


def login(creds):
    r = cli.post(f"{BASE}/auth/login", json={"username": creds[0], "password": creds[1]})
    j = r.json()
    assert j.get("code") == 0, j
    d = j["data"]
    return d["accessToken"], d["user"]


def call(method, path, token, **kw):
    h = {"Authorization": f"Bearer {token}"}
    r = cli.request(method, f"{BASE}{path}", headers=h, **kw)
    try:
        body = r.json()
    except Exception:
        body = {"_raw": r.text[:200]}
    return r.status_code, body


mem_t, mem_u = login(MEMBER)
org_t, org_u = login(ORG_ADMIN)
tan_t, tan_u = login(TENANT_ADMIN)
print("member:", mem_u["username"], "roles=", mem_u["roles"])
print("orgadmin:", org_u["username"], "roles=", org_u["roles"], "instId=", org_u.get("institutionId"))
print()

st, types = call("GET", "/leave/types", mem_t)
print("A1 假种列表:", st, [t["code"] for t in types.get("data", [])])
st, bal = call("GET", "/leave/balance", mem_t)
print("A2 我的余额:", st, json.dumps(bal.get("data"), ensure_ascii=False))
print()

# ---- A) 新链路：真实请假流程 ----
types = types.get("data") or []
code = types[0]["code"] if types else "ANNUAL"
st, res = call("POST", "/leave/requests", mem_t, json={
    "leaveTypeCode": code,
    "startDate": "2026-10-12",
    "endDate": "2026-10-13",
    "days": 2,
    "reason": "诊断脚本 #210",
})
print("A3 提交请假(新链路):", st, json.dumps(res, ensure_ascii=False)[:600])
new_order_id = res.get("data", {}).get("orderId")
print()

# 机构管理员视角
st, todo_new = call("GET", "/workflow/tasks?scope=todo", org_t)
print("A4 机构管理员 /workflow/tasks?scope=todo:", st,
      json.dumps([{k: t.get(k) for k in ("taskId", "title", "approverType", "approverName", "seq")}
                  for t in (todo_new.get("data") or [])], ensure_ascii=False))
st, notif = call("GET", "/notifications?limit=20", org_t)
nd = notif.get("data")
items = nd.get("items") if isinstance(nd, dict) else nd
print("A5 机构管理员通知:", st, json.dumps([i.get("title") for i in (items or [])][:6], ensure_ascii=False))
print()

# ---- B) 旧链路：用户端 H5 实际走的路径 ----
st, res_b = call("POST", "/approvals", mem_t, json={
    "bizType": "请假",
    "title": "诊断 旧链路请假",
    "content": "2026-10-20 ~ 2026-10-21",
    "formData": json.dumps({"leaveType": "年假", "start": "2026-10-20", "end": "2026-10-21"}),
})
print("B1 提交请假(旧链路/用户端在用):", st, json.dumps(res_b, ensure_ascii=False)[:400])
legacy_id = res_b.get("data", {}).get("id")
print()

st, todo_legacy = call("GET", "/approvals?scope=todo", org_t)
print("B2 机构管理员 /approvals?scope=todo:", st, json.dumps(todo_legacy, ensure_ascii=False)[:300])
st, todo_legacy_t = call("GET", "/approvals?scope=todo", tan_t)
print("B3 租户管理员 /approvals?scope=todo:", st,
      "条数=", len(todo_legacy_t.get("data") or []) if st == 200 else todo_legacy_t.get("message"))
st, notif_org = call("GET", "/notifications?limit=20", org_t)
nd = notif_org.get("data")
items = nd.get("items") if isinstance(nd, dict) else nd
print("B4 机构管理员通知(旧链路提交后):", st,
      json.dumps([i.get("title") for i in (items or [])][:6], ensure_ascii=False))

# 旧链路是否生成了 approval_task
print()
print("新链路 orderId =", new_order_id, " 旧链路 approvalId =", legacy_id)
print("提示：旧链路不产生 approval_task，故 /workflow/tasks 里只有新链路那一单。")

# 清理：撤销本次诊断产生的新链路请假单
st, cancel = call("POST", f"/leave/requests/{res.get('data', {}).get('leaveRequestId')}/cancel", mem_t)
print("清理 撤销诊断请假单:", st, json.dumps(cancel, ensure_ascii=False)[:200])
cli.close()
