"""V1.2 新接口验证：经营数据看板 / 数字员工 / 成果沉淀（含管理端越权 403）"""
import httpx, json, sys

BASE = "http://127.0.0.1:8080/api/v1"
ok = fail = 0


def rec(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"PASS  {name}" + (f"  -- {detail}" if detail else ""))
    else:
        fail += 1
        print(f"FAIL  {name}" + (f"  -- {detail}" if detail else ""))


def login(u, p):
    r = httpx.post(f"{BASE}/auth/login", json={"username": u, "password": p}, timeout=20, trust_env=False)
    d = r.json()
    return (d.get("data") or {}).get("accessToken") if d.get("code") == 0 else None


def cli(tok):
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {tok}"}, timeout=20, trust_env=False)


ZS = login("zhangsan", "User@123")
AD = login("admin", "Admin@123")
rec("T01 双账号登录", bool(ZS and AD))
if not (ZS and AD):
    sys.exit(1)

c = cli(ZS)
a = cli(AD)

# ---- 经营数据看板 ----
try:
    b = c.get("/kpi/board", params={"period": "month"}).json()["data"]
    rec("T02 本月看板 4 指标", len(b.get("metrics", [])) == 4, str([m["label"] for m in b.get("metrics", [])]))
    rec("T03 本月趋势 6 点", len(b.get("trend", [])) == 6, str([t["label"] for t in b.get("trend", [])]))
    rec("T04 本月 AI 解读非空", bool(b.get("insight")), b.get("insight", "")[:30])
    rec("T05 数据来源非空", bool(b.get("source")), b.get("source", "")[:30])
    hot = [t for t in b.get("trend", []) if t.get("hot")]
    rec("T06 趋势含当期高亮", len(hot) == 1)
except Exception as e:
    rec("T02-T06 经营看板读取", False, str(e))

try:
    bq = c.get("/kpi/board", params={"period": "quarter"}).json()["data"]
    rec("T07 本季看板切换", len(bq.get("metrics", [])) == 4 and bq["period"] == "quarter",
        str([m["label"] + m["value"] for m in bq.get("metrics", [])]))
except Exception as e:
    rec("T07 本季看板切换", False, str(e))

# ---- 数字员工 ----
try:
    ws = c.get("/workers").json()["data"]
    rec("T08 数字员工列表 3 个", len(ws) == 3, str([w["name"] for w in ws]))
    rec("T09 数字员工 on=true", all(w["on"] for w in ws))
    w0 = ws[0]
    neww = c.post("/workers", json={"name": "季度报表员", "icon": "bot",
                                    "description": "每季度首日汇总经营数据",
                                    "scheduleText": "每季度首日 09:00"}).json()["data"]
    rec("T10 创建数字员工", neww.get("name") == "季度报表员" and neww.get("on"))
    tg = c.post(f"/workers/{neww['id']}/toggle").json()["data"]
    rec("T11 停用数字员工", tg.get("on") is False and tg.get("status") == "已停用")
    tg2 = c.post(f"/workers/{neww['id']}/toggle").json()["data"]
    rec("T12 恢复数字员工", tg2.get("on") is True)
except Exception as e:
    rec("T08-T12 数字员工", False, str(e))

# ---- 成果沉淀 ----
try:
    rs = c.get("/results").json()["data"]
    rec("T13 我的成果列表", len(rs) >= 2, str([r["title"] for r in rs]))
    rid = rs[0]["id"]
    det = c.get(f"/results/{rid}").json()["data"]
    rec("T14 成果详情含正文", bool(det.get("body")), (det.get("body") or "")[:24])
    nr = c.post("/results", json={"title": "测试成果.docx", "icon": "doc",
                                  "meta": "刚刚 · 测试", "body": "正文测试内容"}).json()["data"]
    rec("T15 存为成果", nr.get("title") == "测试成果.docx")
    upd = c.put(f"/results/{nr['id']}", json={"status": "SUBMITTED"}).json()["data"]
    rec("T16 成果发起审批", upd.get("status") == "SUBMITTED")
except Exception as e:
    rec("T13-T16 成果沉淀", False, str(e))

# ---- 管理端 CRUD + 越权 ----
try:
    m = a.get("/admin/kpi/metrics", params={"period": "month"}).json()["data"]
    rec("T17 管理端读指标", len(m) == 4)
    cm = a.post("/admin/kpi/metrics", json={"period": "month", "label": "毛利率", "valueText": "32.4%",
                                            "deltaText": "+1.2%", "up": 1, "compareLabel": "环比",
                                            "sortNo": 5}).json()["data"]
    rec("T18 管理端新增指标", cm.get("label") == "毛利率")
    um = a.put(f"/admin/kpi/metrics/{cm['id']}", json={"period": "month", "label": "毛利率",
                                                       "valueText": "33.0%", "deltaText": "+1.8%",
                                                       "up": 1, "compareLabel": "环比",
                                                       "sortNo": 5}).json()["data"]
    rec("T19 管理端改指标", um.get("valueText") == "33.0%")
    a.delete(f"/admin/kpi/metrics/{cm['id']}")
    rec("T20 管理端删指标", len(a.get("/admin/kpi/metrics", params={"period": "month"}).json()["data"]) == 4)

    tr = a.get("/admin/kpi/trend", params={"period": "month"}).json()["data"]
    rec("T21 管理端读趋势", len(tr) == 6)
    ins = a.put("/admin/kpi/insight", params={"period": "month"},
                json={"content": "测试解读", "sourceText": "测试来源"}).json()["data"]
    rec("T22 管理端保存解读", ins.get("content") == "测试解读")
    b2 = c.get("/kpi/board", params={"period": "month"}).json()["data"]
    rec("T23 用户端读到新解读", b2.get("insight") == "测试解读")

    aw = a.get("/admin/workers").json()["data"]
    rec("T24 管理端数字员工列表", len(aw) >= 3, str(len(aw)))
    ar = a.get("/admin/results").json()["data"]
    rec("T25 管理端成果列表", len(ar) >= 2, str(len(ar)))
except Exception as e:
    rec("T17-T25 管理端 CRUD", False, str(e))

# ---- 越权 403 ----
for path, name in [("/admin/kpi/metrics", "T26 普通用户读指标"),
                   ("/admin/workers", "T27 普通用户读数字员工"),
                   ("/admin/results", "T28 普通用户读成果")]:
    try:
        r = c.get(path)
        rec(name + "→403", r.status_code == 403, f"HTTP {r.status_code}")
    except Exception as e:
        rec(name + "→403", False, str(e))

# 清理测试成果
try:
    for r in c.get("/results").json()["data"]:
        if r["title"] == "测试成果.docx":
            a.delete(f"/admin/results/{r['id']}")
    # 清理新增的数字员工
    for w in a.get("/admin/workers").json()["data"]:
        if w["name"] == "季度报表员":
            a.delete(f"/admin/workers/{w['id']}")
except Exception:
    pass

print(f"\n==== {ok} passed, {fail} failed ====")
sys.exit(1 if fail else 0)
