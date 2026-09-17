# -*- coding: utf-8 -*-
"""V39 · 验证 `ApprovalFlowProvisioner`（新租户/新机构入驻时自动播种默认审批流）。

为什么单独验：`e2e_v39_applicant_superior.py` 覆盖的是「引擎按层级递推」，
而播种器只在**发布 `TenantProvisionedEvent`（新建机构）**时触发 —— 属于另一条代码路径，
且它内部用 try/catch 吞掉异常 + 只记 warn，**失败是静默的**，不实测就等于没验。

手法（可逆）：
  1. 记录 tenant 9 基线（机构数 / 流程定义条数）；
  2. 直接删掉 tenant 9 的 `RESOURCE_OPEN` 默认流，模拟「V26 之后建的租户」；
  3. 以租户管理员身份新建一个探针机构 → 触发事件；
  4. 断言 `RESOURCE_OPEN` 被补回、其余 3 条**不重复**、且没有新增多余流程；
  5. 回滚：软删探针机构 / 其管理员 / 成员关系，并断言机构数回到基线。

前置：后端 :8080 已启动、V39 迁移已执行。
"""
import sys

import httpx
import pymysql

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=90, trust_env=False)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", autocommit=True)

TENANT_ID = 9
PROBE_CODE = "V39PROBE"
PROBE_ADMIN = "v39probe_admin"
DEFAULTS = ("PERMISSION_GRANT", "LEAVE", "QUOTA_EXPAND", "RESOURCE_OPEN")

results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def login(name, pwd):
    d = C.post(f"{BASE}/auth/login", json={"username": name, "password": pwd}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"]


def req(method, path, tok=None, **kw):
    h = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = C.request(method, BASE + path, headers=h, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"code": -1}


def db(sql, args=None, fetch=True):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            rows = cur.fetchall() if (fetch and cur.description) else []
            n = cur.rowcount
        conn.commit()
        return rows, n
    finally:
        conn.close()


def flow_count(biz=None):
    if biz:
        rows, _ = db("SELECT id FROM approval_flow_def WHERE tenant_id=%s AND institution_id=0 "
                     "AND biz_type=%s AND deleted_at IS NULL", (TENANT_ID, biz))
    else:
        rows, _ = db("SELECT id FROM approval_flow_def WHERE tenant_id=%s AND institution_id=0 "
                     "AND deleted_at IS NULL", (TENANT_ID,))
    return len(rows)


def inst_count(tok):
    st, b = req("GET", "/tenant/institutions", tok)
    d = b.get("data")
    if isinstance(d, list):
        return len(d)
    if isinstance(d, dict):
        return len(d.get("items") or d.get("list") or d.get("records") or [])
    return None


def cleanup_probe():
    """软删探针机构及其管理员 / 成员关系，让全部 API 都看不到它。"""
    db("UPDATE sys_user SET deleted_at=NOW(6) WHERE username=%s AND deleted_at IS NULL", (PROBE_ADMIN,))
    db("UPDATE org_member SET deleted_at=NOW(6) WHERE tenant_id=%s AND institution_id IN "
       "(SELECT id FROM org_institution WHERE code=%s)", (TENANT_ID, PROBE_CODE))
    db("UPDATE org_department SET deleted_at=NOW(6) WHERE institution_id IN "
       "(SELECT id FROM org_institution WHERE code=%s)", (PROBE_CODE,))
    db("UPDATE org_institution SET deleted_at=NOW(6) WHERE tenant_id=%s AND code=%s",
       (TENANT_ID, PROBE_CODE))


def main():
    tok_admin = login("admin", "Admin@123")
    tok_ten = login("znkj_admin", "User@123")

    # 先清掉可能残留的探针，保证可重复运行
    cleanup_probe()

    base_inst = inst_count(tok_ten)
    base_flows = flow_count()
    print(f"[baseline] tenant {TENANT_ID}: 机构数={base_inst} 租户级默认流={base_flows}")
    if not check("基线：tenant 9 已有 4 条租户级默认流", base_flows == 4, f"flows={base_flows}"):
        sys.exit(1)

    # ---- 制造「缺一条默认流」的状态 ----
    _, n = db("DELETE FROM approval_flow_def WHERE tenant_id=%s AND institution_id=0 "
              "AND biz_type='RESOURCE_OPEN'", (TENANT_ID,))
    check("前置：已移除 RESOURCE_OPEN 默认流（模拟 V26 之后建的租户）", n == 1, f"deleted={n}")
    check("前置：现在只剩 3 条", flow_count() == 3, f"flows={flow_count()}")

    # ---- 触发事件：新建机构 ----
    st, b = req("POST", "/tenant/institutions", tok_ten, json={
        "name": "V39播种校验机构", "code": PROBE_CODE, "orgType": "ENTERPRISE",
        "adminUsername": PROBE_ADMIN, "adminName": "播种校验", "adminPassword": "User@123",
        "remark": "V39 provisioner 校验用，脚本会自动回滚",
    })
    if not check("新建机构成功（应发布 TenantProvisionedEvent）", b.get("code") == 0,
                 f"st={st} {str(b)[:200]}"):
        sys.exit(1)
    probe_inst_id = b["data"]["id"]
    print(f"        probe institutionId={probe_inst_id}")

    # ---- 断言播种结果 ----
    check("★ RESOURCE_OPEN 默认流被租户入驻自动补回", flow_count("RESOURCE_OPEN") == 1,
          f"count={flow_count('RESOURCE_OPEN')}")
    check("★ 租户级默认流总数回到 4（无重复插入）", flow_count() == 4, f"flows={flow_count()}")

    rows, _ = db("SELECT biz_type, COUNT(*) AS c FROM approval_flow_def "
                 "WHERE tenant_id=%s AND institution_id=0 AND deleted_at IS NULL "
                 "GROUP BY biz_type", (TENANT_ID,))
    got = {r[0]: r[1] for r in rows}
    check("★ 每条业务类型恰好 1 条（幂等：已存在的不重复插）",
          got == {k: 1 for k in DEFAULTS}, f"got={got}")

    rows, _ = db("SELECT steps_json FROM approval_flow_def WHERE tenant_id=%s AND institution_id=0 "
                 "AND biz_type='PERMISSION_GRANT' AND deleted_at IS NULL", (TENANT_ID,))
    check("★ 补回的流程用的是 APPLICANT_SUPERIOR 递推模板",
          rows and "APPLICANT_SUPERIOR" in str(rows[0][0]), f"steps={rows[0][0] if rows else None}")

    # 新建机构不能污染「租户级」（institution_id=0）的定义
    rows, _ = db("SELECT COUNT(*) FROM approval_flow_def WHERE tenant_id=%s AND institution_id<>0 "
                 "AND deleted_at IS NULL", (TENANT_ID,))
    check("机构级流程定义未被误插（播种只写 institution_id=0）", rows[0][0] == 0, f"n={rows[0][0]}")

    # ---- 回滚 ----
    cleanup_probe()
    after_inst = inst_count(tok_ten)
    check("回滚：机构数回到基线", after_inst == base_inst, f"before={base_inst} after={after_inst}")
    rows, _ = db("SELECT COUNT(*) FROM sys_user WHERE username=%s AND deleted_at IS NULL", (PROBE_ADMIN,))
    check("回滚：探针管理员已不可见", rows[0][0] == 0, f"n={rows[0][0]}")

    passed = sum(1 for _, c, _ in results if c)
    print("\n" + "=" * 66)
    print(f"V39 默认审批流播种器校验：{passed}/{len(results)} 通过")
    if passed != len(results):
        for t, c, d in results:
            if not c:
                print(f"  - {t}  {d}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
