"""审批流配置工具验收（2026-11-05）。

要证明的核心不是「能改」，而是**不该改的时候改不动**：
  · 缺 defId / 缺 steps / 节点写错 → 一律不落库，只回 missing 清单与要问用户的话；
  · 参数齐了但用户没确认（confirm 缺失）→ 仍然不落库，只回「将要改成什么」；
  · 只有 confirm=true 才真的写，且写后有版本快照、可原样改回。
每一步都回库比对（铁律 12：界面/工具说改了，必须回库确认）。
"""
import json
import sys

import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=40, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def login(username, password="Admin@123"):
    r = C.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    return (r.json().get("data") or {}).get("accessToken")


def db_steps(def_id):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT steps_json FROM approval_flow_def WHERE id=%s", (def_id,))
            return json.loads(cur.fetchone()["steps_json"])
    finally:
        conn.close()


def db_versions(def_id):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM approval_flow_def_version WHERE def_id=%s", (def_id,))
            return cur.fetchone()["n"]
    finally:
        conn.close()


def main():
    token = login("dsj_admin")
    check("L0 登录租户管理员", bool(token))
    if not token:
        return summary()
    H = {"Authorization": f"Bearer {token}"}

    def tools():
        return C.get(f"{BASE}/tools", headers=H).json().get("data") or []

    def invoke(name, args=None):
        # 网关把工具回执裹在统一信封里：{code:0, data:{ok, data|error}}。
        # 这里剥掉信封，断言才能直接看 ok —— 上一版忘了剥，把「真的通过」判成了失败。
        r = C.post(f"{BASE}/tools/invoke", headers=H, json={"name": name, "arguments": args or {}})
        body = r.json()
        return body.get("data") or {}

    print("=== A. 工具已注册 ===")
    names = {t.get("function", {}).get("name") for t in tools() if isinstance(t, dict)}
    for n in ("list_approval_flows", "get_approval_flow", "update_approval_flow"):
        check(f"A {n} 在工具清单里", n in names)

    print("=== B. 查流程 ===")
    b = invoke("list_approval_flows")
    d = b.get("data") or {}
    flows = d.get("flows") or []
    check("B1 能列出流程", b.get("ok") is True and len(flows) > 0, f"count={len(flows)}")
    if not flows:
        return summary()
    f0 = [x for x in flows if x.get("bizType") == "LEAVE"][0] if any(
        x.get("bizType") == "LEAVE" for x in flows) else flows[0]
    check("B2 带中文节点串", "级" in str(f0.get("stepsText")), str(f0.get("stepsText"))[:50])
    def_id = f0.get("defId")

    print("=== C. 参数不足 → 只问不改 ===")
    b = invoke("get_approval_flow")
    d = b.get("data") or {}
    check("C1 不给 defId 时返回候选", b.get("ok") is False and d.get("missing") == ["defId"]
          and len(d.get("candidates") or []) > 0, f"candidates={len(d.get('candidates') or [])}")
    check("C2 给了可直接转述的问题", "哪一条" in str(d.get("question")), str(d.get("question"))[:40])

    b = invoke("update_approval_flow", {"defId": def_id})
    d = b.get("data") or {}
    check("C3 缺 steps 时不改", b.get("ok") is False and "steps" in str(d.get("missing")))
    check("C4 附带当前配置便于追问", bool((d.get("current") or {}).get("stepsText")),
          str((d.get("current") or {}).get("stepsText"))[:40])
    check("C5 附带可选审批人类型", len((d.get("allowedApproverTypes") or {})) >= 4)

    b = invoke("update_approval_flow", {"defId": def_id, "steps": [{"seq": 1, "approver_type": "BOSS"}]})
    d = b.get("data") or {}
    check("C6 节点类型非法 → 指出第几级错在哪", b.get("ok") is False
          and any("不认识" in x for x in (d.get("invalid") or [])), str(d.get("invalid"))[:60])

    print("=== D. 参数齐了但没确认 → 仍不改 ===")
    original = db_steps(def_id)
    v0 = db_versions(def_id)
    changed = [dict(x) for x in original]
    changed[-1] = dict(changed[-1])
    changed[-1]["mode"] = "parallel"
    b = invoke("update_approval_flow", {"defId": def_id, "steps": changed})
    d = b.get("data") or {}
    check("D1 返回 needConfirm", b.get("ok") is False and d.get("needConfirm") is True)
    check("D2 摆出改前/改后", bool(d.get("beforeText")) and bool(d.get("afterText")),
          f"{d.get('beforeText')} → {d.get('afterText')}")
    check("D3 库里没有被改动", db_steps(def_id) == original)
    check("D4 版本数没变", db_versions(def_id) == v0)

    print("=== E. confirm=true 才真的写，且可原样改回 ===")
    b = invoke("update_approval_flow", {"defId": def_id, "steps": changed,
                                        "reason": "验收：把末级改为会签", "confirm": True})
    d = b.get("data") or {}
    check("E1 写入成功", b.get("ok") is True and d.get("message"), str(d.get("message"))[:70])
    now = db_steps(def_id)
    check("E2 库里确实变了", now != original and now[-1].get("mode") == "parallel",
          str(now[-1]))
    check("E3 留了版本快照", db_versions(def_id) == v0 + 1, f"{v0} → {db_versions(def_id)}")

    b = invoke("update_approval_flow", {"defId": def_id, "steps": original,
                                        "reason": "验收：改回原配置", "confirm": True})
    check("E4 能改回原样", b.get("ok") is True and db_steps(def_id) == original)
    check("E5 再留一版快照", db_versions(def_id) == v0 + 2)

    print("=== F. 权限：普通成员改不了 ===")
    conn = pymysql.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("""SELECT u.username, u.password_hash FROM sys_user u
                       JOIN sys_user_role ur ON ur.user_id=u.id AND ur.deleted_at IS NULL
                       JOIN sys_role r ON r.id=ur.role_id AND r.deleted_at IS NULL
                       WHERE u.tenant_id=2 AND u.deleted_at IS NULL AND r.role_code='ROLE_MEMBER'
                       LIMIT 1""")
        member = cur.fetchone()
    conn.close()
    if member:
        import bcrypt
        pw = None
        for cand in ("User@123", "Admin@123", "123456"):
            try:
                if member["password_hash"] and bcrypt.checkpw(cand.encode(),
                                                              member["password_hash"].encode()):
                    pw = cand
                    break
            except Exception:
                pass
        if pw:
            mt = login(member["username"], pw)
            if mt:
                r = C.post(f"{BASE}/tools/invoke", headers={"Authorization": f"Bearer {mt}"},
                           json={"name": "update_approval_flow",
                                 "arguments": {"defId": def_id, "steps": changed, "confirm": True}})
                b = r.json().get("data") or {}
                check("F1 普通成员被拒", b.get("ok") is False and "角色" in str(b.get("error")),
                      str(b.get("error"))[:40])
                check("F2 被拒时也没写库", db_steps(def_id) == original)
            else:
                check("F1 普通成员被拒", False, "该成员口令不在候选里，跳过")
        else:
            check("F1 普通成员被拒", False, "口令未知，跳过")
    else:
        check("F1 普通成员被拒", False, "租户 2 没有 ROLE_MEMBER 账号，跳过")

    print("=== G. 错误信封 ===")
    b = invoke("update_approval_flow", {"defId": 999999, "steps": changed, "confirm": True})
    check("G1 不存在的 defId → 不抛异常、给候选", b.get("ok") is False
          and len(((b.get("data") or {}).get("candidates") or [])) > 0)
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
