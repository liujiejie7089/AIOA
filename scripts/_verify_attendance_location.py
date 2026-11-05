"""定位授权 + 打卡 + 内部数据工具的接口级验收（2026-11-05）。

口径（为什么这么测）：
  · 「必须用户同意」是**服务端**约束，所以断言点在接口层，不在界面层：
    没有 token / token 过期 / token 已被用过 / token 被拒绝过 / token 不是本人的，
    五种情形都必须打不了卡。
  · H5 的定位卡只负责「问一句并取一次坐标」，它不该被当成安全边界；
    这里要证明的正是「即使前端被绕过，也写不进考勤」。
  · 数字人能不能查到内部事实，测的是 /api/v1/tools 的清单与 invoke 结果，
    而不是「模型答得好不好」——后者不可判定。
"""
import sys
import json
from pathlib import Path

import httpx
import pymysql
import bcrypt

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=30, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
CAND = ["User@123", "Admin@123", "123456"]
results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def resolve_password(h):
    for pw in CAND:
        try:
            if h and bcrypt.checkpw(pw.encode(), h.encode()):
                return pw
        except Exception:
            pass
    return "User@123"


def login(username, password, tenant_name=None):
    body = {"username": username, "password": password}
    if tenant_name:
        body["tenantName"] = tenant_name
    r = C.post(f"{BASE}/auth/login", json=body)
    try:
        return r.json()
    except Exception:
        return {"code": -1, "message": f"HTTP {r.status_code}"}


def main():
    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE 'location_consent'")
        t1 = cur.fetchone()
        cur.execute("SHOW TABLES LIKE 'attendance_record'")
        t2 = cur.fetchone()
        cur.execute("""SELECT u.username, u.password_hash FROM sys_user u
                       JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                       JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL
                       WHERE u.deleted_at IS NULL AND u.status='ENABLED' AND r.role_code='ROLE_TENANT_ADMIN'
                       ORDER BY u.id LIMIT 1""")
        admin = cur.fetchone()
    conn.close()

    print("=== A. 数据模型 ===")
    check("A1 location_consent 表已建", bool(t1))
    check("A2 attendance_record 表已建", bool(t2))

    print("=== B. 登录 ===")
    if not admin:
        check("B0 找到租户管理员", False, "库里没有 ROLE_TENANT_ADMIN 账号")
        return summary()
    pw = resolve_password(admin["password_hash"])
    res = login(admin["username"], pw)
    data = res.get("data") or {}
    token = data.get("accessToken") or data.get("token")
    check("B1 登录成功", bool(token), f"{admin['username']} / {pw} code={res.get('code')}")
    if not token:
        print(json.dumps(res, ensure_ascii=False)[:300])
        return summary()
    H = {"Authorization": f"Bearer {token}"}

    def post(path, body=None):
        return C.post(f"{BASE}{path}", json=body or {}, headers=H)

    def get(path):
        return C.get(f"{BASE}{path}", headers=H)

    print("=== C. 定位申请：只建单、不取坐标 ===")
    r = post("/attendance/location-consent", {"origin": "H5"})
    b = r.json()
    c1 = b.get("data") or {}
    check("C1 申请返回 PENDING", c1.get("status") == "PENDING", f"http={r.status_code} status={c1.get('status')}")
    check("C2 带一次性 token", bool(c1.get("token")), f"token={str(c1.get('token'))[:6]}…")
    check("C3 有有效期(<=5min)", 0 < int(c1.get("expiresInSeconds") or 0) <= 300, f"{c1.get('expiresInSeconds')}s")
    check("C4 文案写明用途与时效", "定位" in str(c1.get("prompt")) and "分钟" in str(c1.get("prompt")),
          str(c1.get("prompt"))[:40])
    check("C5 申请单本身不含坐标", c1.get("latitude") is None and c1.get("longitude") is None)

    p = get("/attendance/location-consent/pending").json().get("data") or {}
    check("C6 pending 能取到同一张单", p.get("id") == c1.get("id"), f"pending.id={p.get('id')}")

    print("=== D. 没有授权就打不了卡（服务端硬约束）===")
    r = post("/attendance/clock", {"latitude": 31.23, "longitude": 121.47})
    b = r.json()
    check("D1 无 token ⇒ 200+code400", r.status_code == 200 and b.get("code") == 400, f"http={r.status_code} code={b.get('code')}")
    check("D2 文案说清了要授权", "定位" in str(b.get("message")), str(b.get("message"))[:40])

    r = post("/attendance/clock", {"token": "NOT-A-REAL-TOKEN", "latitude": 31.23, "longitude": 121.47})
    b = r.json()
    check("D3 伪造 token ⇒ code400", b.get("code") == 400, f"code={b.get('code')}")

    print("=== E. 用户拒绝后同一张单不能再用 ===")
    r2 = post("/attendance/location-consent", {"origin": "H5"}).json().get("data") or {}
    deny = post(f"/attendance/location-consent/{r2.get('id')}/deny")
    check("E1 拒绝接口成功", deny.json().get("code") == 0, f"code={deny.json().get('code')}")
    b = post("/attendance/clock", {"token": r2.get("token"), "latitude": 31.23, "longitude": 121.47}).json()
    check("E2 被拒的 token ⇒ 打不了卡", b.get("code") == 400, str(b.get("message"))[:50])
    # 注意：此时 C1 那张单仍是 PENDING，所以 pending 不一定为空 —— 断言的是「被拒这张不在待处理里」
    pd = get("/attendance/location-consent/pending").json().get("data") or {}
    check("E3 被拒的单不再出现在待处理", pd.get("id") != r2.get("id"), f"pending.id={pd.get('id')}")

    print("=== F. 同意 + 打卡（正常路径）===")
    b = post("/attendance/clock", {
        "token": c1.get("token"),
        "latitude": 31.230416, "longitude": 121.473701, "accuracy": 18.5,
        "placeName": "上海市黄浦区（验收）", "source": "H5",
        "consentText": c1.get("prompt"),
    }).json()
    rec = b.get("data") or {}
    check("F1 打卡成功", b.get("code") == 0 and rec.get("id"), f"code={b.get('code')} msg={rec.get('message')}")
    check("F2 自动判定卡类型", rec.get("clockType") in ("ON", "OFF"), f"{rec.get('clockType')}={rec.get('clockTypeLabel')}")
    check("F3 记录带坐标与来源", rec.get("latitude") is not None and rec.get("source") == "H5", str(rec.get("latitude")))
    check("F4 首次打卡不重复", rec.get("duplicated") is False, f"duplicated={rec.get('duplicated')}")

    print("=== G. 一次性：同一张单不能打第二次 ===")
    b = post("/attendance/clock", {"token": c1.get("token"), "latitude": 31.23, "longitude": 121.47}).json()
    check("G1 复用已用 token ⇒ code400", b.get("code") == 400, str(b.get("message"))[:40])
    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("SELECT status, used_at FROM location_consent WHERE token=%s", (c1.get("token"),))
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM attendance_record WHERE consent_id=%s", (c1.get("id"),))
        n = cur.fetchone()["n"]
    conn.close()
    check("G2 授权单已置 USED", (row or {}).get("status") == "USED", str((row or {}).get("status")))
    check("G3 只落了一条考勤记录", n == 1, f"记录数={n}")

    print("=== H. 今日考勤可查 ===")
    t = get("/attendance/today").json().get("data") or {}
    check("H1 today 有记录", len(t.get("records") or []) >= 1, f"records={len(t.get('records') or [])}")
    check("H2 明确标了上班/下班", (t.get("clockedOn") or t.get("clockedOff")) is True,
          f"on={t.get('clockedOn')} off={t.get('clockedOff')}")

    print("=== I. 数字人能看见内部数据（工具清单 + 调用）===")
    tools = get("/tools").json().get("data") or []
    names = {x.get("function", {}).get("name") for x in tools if isinstance(x, dict)}
    for want in ("my_model_accounts", "list_colleagues", "my_attendance", "attendance_clock"):
        check(f"I 工具已注册 {want}", want in names)

    def invoke(name, args=None):
        return post("/tools/invoke", {"name": name, "arguments": args or {}}).json()

    b = invoke("my_model_accounts")
    d = b.get("data") or {}
    check("I5 my_model_accounts 可用", b.get("code") == 0 and isinstance((d.get("data") or {}).get("mine"), list),
          str((d.get("data") or {}).get("summary"))[:60])

    b = invoke("list_colleagues", {"keyword": ""})
    d = (b.get("data") or {}).get("data") or {}
    check("I6 list_colleagues 可用", b.get("code") == 0 and "people" in d, f"count={d.get('count')}")
    leaked = False
    for p_ in (d.get("people") or []):
        if any(k in p_ for k in ("mobile", "email", "phone")):
            leaked = True
    check("I7 同事结果不含手机号/邮箱", not leaked)

    b = invoke("my_attendance", {})
    d = (b.get("data") or {}).get("data") or {}
    check("I8 my_attendance 可用", b.get("code") == 0 and "records" in d, f"records={len(d.get('records') or [])}")

    b = invoke("attendance_clock", {})
    d = (b.get("data") or {}).get("data") or {}
    check("I9 attendance_clock 发起的是申请单", b.get("code") == 0 and d.get("needLocation") is True,
          f"needLocation={d.get('needLocation')} expires={d.get('expiresInSeconds')}s")
    check("I10 申请单来自 AI 侧（origin=AI）",
          (get("/attendance/location-consent/pending").json().get("data") or {}).get("origin") == "AI")
    # 清理这张 AI 单，避免残留待处理申请影响下次人工验证
    pid = (get("/attendance/location-consent/pending").json().get("data") or {}).get("id")
    if pid:
        post(f"/attendance/location-consent/{pid}/deny")

    print("=== J. 错误信封合规（不泄漏原始异常）===")
    b = post("/attendance/clock", {"token": "", "latitude": "abc", "longitude": 200}).json()
    check("J1 非法坐标 ⇒ code400 且有人话", b.get("code") == 400 and isinstance(b.get("message"), str),
          str(b.get("message"))[:40])
    check("J2 不带堆栈/类名", "Exception" not in str(b.get("message")) and "java." not in str(b.get("message")))

    return summary()


def summary():
    ok = sum(1 for _, c, _ in results if c)
    print(f"\n===== {ok}/{len(results)} 通过 =====")
    bad = [t for t, c, _ in results if not c]
    if bad:
        print("失败项：" + "；".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
