#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OA 业务链接线哨兵（docs/57 阶段一 A1–A5 的验收判据）。

用法:
    python scripts/_verify_oa_wiring.py            # 只验数据层 + 代码层
    python scripts/_verify_oa_wiring.py --api      # 追加接口层（需要后端已重启加载新代码）

判据说明：
    · 数据层用 pymysql 直连库（credential 与 application.yml 默认一致：root / 空密码）
    · 代码层用文件检索（确认新增的类/字段/修复真的落盘了）
    · 接口层只在 --api 时跑：后端未重启会读到旧代码，此时该组判 SKIP 而不是判红，
      避免把「没重启」误报成「代码有 bug」。

退出码：0 = 全绿（或仅 SKIP）；1 = 有红。
"""
from __future__ import annotations

import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = dict(host="127.0.0.1", user="root", password="", database="aios", charset="utf8mb4")

GREEN, RED, SKIP = [], [], []


def ok(name, detail=""):
    GREEN.append((name, detail))
    print(f"  \033[32mOK\033[0m   {name}" + (f"  ({detail})" if detail else ""))


def bad(name, detail=""):
    RED.append((name, detail))
    print(f"  \033[31mRED\033[0m  {name}" + (f"  ({detail})" if detail else ""))


def skip(name, why):
    SKIP.append((name, why))
    print(f"  \033[33mSKIP\033[0m {name}  —— {why}")


def grep_file(relpath, needle):
    """在仓库文件里找关键字（代码层判据）。"""
    p = os.path.join(ROOT, relpath)
    if not os.path.exists(p):
        return False
    with open(p, encoding="utf-8") as f:
        return needle in f.read()


def data_checks(cur):
    print("\n[1] 数据层：能力接线（A1 / A2）")

    cur.execute("SELECT COUNT(*) FROM worker_capability WHERE alive=1 "
                "AND (tool_names_json IS NULL OR tool_names_json='' OR tool_names_json='[]')")
    n = cur.fetchone()[0]
    ok("能力表无空工具声明", f"空值 {n} 行") if n == 0 else bad("能力表无空工具声明", f"仍有 {n} 行")

    cur.execute("SELECT COUNT(*) FROM worker_capability WHERE alive=1 "
                "AND approval_biz_type IS NOT NULL AND approval_biz_type<>''")
    n = cur.fetchone()[0]
    ok("已绑定审批流的能力", f"{n} 行") if n >= 200 else bad("已绑定审批流的能力", f"仅 {n} 行（期望 ≥200）")

    cur.execute("SELECT COUNT(DISTINCT approval_biz_type) FROM worker_capability "
                "WHERE alive=1 AND approval_biz_type IS NOT NULL")
    n = cur.fetchone()[0]
    ok("审批业务类型种类", f"{n} 种") if n >= 19 else bad("审批业务类型种类", f"仅 {n} 种（期望 ≥19）")

    print("\n[2] 数据层：审批流定义（A2）")
    cur.execute("""SELECT COUNT(*) FROM (
        SELECT DISTINCT t.tenant_id, c.approval_biz_type
          FROM (SELECT DISTINCT tenant_id FROM worker_capability WHERE tenant_id>0) t
          JOIN (SELECT DISTINCT approval_biz_type FROM worker_capability
                 WHERE alive=1 AND approval_biz_type IS NOT NULL) c
          LEFT JOIN approval_flow_def d
                 ON d.tenant_id=t.tenant_id AND d.institution_id=0 AND d.biz_type=c.approval_biz_type
         WHERE d.id IS NULL) x""")
    n = cur.fetchone()[0]
    ok("每个租户的每个审批业务都有流程定义", f"缺口 {n} 处") if n == 0 else \
        bad("每个租户的每个审批业务都有流程定义", f"缺口 {n} 处")

    cur.execute("SELECT COUNT(*) FROM approval_flow_def WHERE biz_type='EXPENSE'")
    n = cur.fetchone()[0]
    ok("报销审批流已建", f"{n} 条") if n > 0 else bad("报销审批流已建", "0 条")

    print("\n[3] 数据层：报销审批字段（A3）")
    cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema='aios' AND table_name='pm_expense'
                      AND column_name IN ('approval_status','order_id')""")
    n = cur.fetchone()[0]
    ok("pm_expense 审批字段齐备", f"{n}/2") if n == 2 else bad("pm_expense 审批字段齐备", f"仅 {n}/2")

    print("\n[4] 数据层：催办字段（A4）")
    cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema='aios' AND table_name='approval_task'
                      AND column_name IN ('remind_count','last_remind_at')""")
    n = cur.fetchone()[0]
    ok("approval_task 催办字段齐备", f"{n}/2") if n == 2 else bad("approval_task 催办字段齐备", f"仅 {n}/2")


def code_checks():
    print("\n[5] 代码层：新增能力落盘")
    checks = [
        ("报销审批回调已实现",
         "server/aios-project/src/main/java/cn/aios/project/service/ExpenseApprovalCallback.java",
         "implements ApprovalCallback"),
        ("报销提交/重提已实现",
         "server/aios-project/src/main/java/cn/aios/project/service/PmExpenseService.java",
         "submitForApproval"),
        ("催办服务已实现",
         "server/aios-org/src/main/java/cn/aios/org/service/ApprovalFlowService.java",
         "public Map<String, Object> remind("),
        ("超时扫描器已实现",
         "server/aios-org/src/main/java/cn/aios/org/support/ApprovalOverdueScanner.java",
         "@Scheduled"),
        ("通知网关已钉 HTTP/1.1",
         "server/aios-resource/src/main/java/cn/aios/resource/service/notify/HttpGatewayChannel.java",
         "HttpClient.Version.HTTP_1_1"),
        ("新租户播种器含员工侧流程",
         "server/aios-org/src/main/java/cn/aios/org/support/ApprovalFlowProvisioner.java",
         'new Seed("EXPENSE"'),
    ]
    for name, rel, needle in checks:
        ok(name, rel.split("/")[-1]) if grep_file(rel, needle) else bad(name, f"{rel} 里找不到 {needle!r}")

    print("\n[6] 迁移脚本")
    mig = "server/aios-boot/src/main/resources/db/migration/"
    for name, fn in [("V89 能力接线", "V89__oa_module_capability_wiring.sql"),
                     ("V90 催办字段", "V90__approval_task_remind.sql"),
                     ("V91 报销审批字段", "V91__pm_expense_approval.sql")]:
        ok(name) if os.path.exists(os.path.join(ROOT, mig, fn)) else bad(name, "文件不存在")


def api_checks():
    print("\n[7] 接口层（--api）")
    try:
        import requests
    except ImportError:
        skip("接口层整体", "未安装 requests")
        return
    s = requests.Session()
    s.trust_env = False  # 走系统代理会对 down 的服务返回 502，必须绕过
    try:
        r = s.post("http://localhost:8080/api/v1/auth/login",
                   # 口令与既有哨兵 _verify_oa_module_forms.py:88 保持一致
                   json={"username": "wjj_xu", "password": "User@123"}, timeout=5)
        if r.status_code != 200:
            skip("接口层整体", f"登录返回 {r.status_code}（需后端在线且账号可用）")
            return
        body = r.json()
        # 登录包结构：{"code":0,"data":{"accessToken": ...}}（实测）
        token = body.get("data", {}).get("accessToken") or body.get("accessToken")
        if body.get("code") != 0 or not token:
            skip("接口层整体", f"登录未成功：{str(body)[:120]}")
            return
        s.headers["Authorization"] = "Bearer " + token
    except Exception as ex:
        skip("接口层整体", f"后端不可达：{str(ex)[:60]}")
        return

    r = s.get("http://localhost:8080/api/v1/workflow/tasks/summary", timeout=8)
    ok("审批中心可访问", f"HTTP {r.status_code}") if r.status_code == 200 else \
        bad("审批中心可访问", f"HTTP {r.status_code}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", action="store_true", help="追加接口层验收（需要后端重启加载新代码）")
    args = ap.parse_args()

    print("=" * 78)
    print("OA 业务链接线哨兵  (docs/57 阶段一)")
    print("=" * 78)

    try:
        import pymysql
    except ImportError:
        print("未安装 pymysql，数据层判据无法运行")
        sys.exit(1)
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            data_checks(cur)
    finally:
        conn.close()

    code_checks()
    if args.api:
        api_checks()
    else:
        skip("接口层", "未加 --api（或后端尚未重启加载新代码时不要开，会误报）")

    print("\n" + "=" * 78)
    print(f"绿 {len(GREEN)}   红 {len(RED)}   跳过 {len(SKIP)}")
    if RED:
        for n, d in RED:
            print(f"  RED  {n}  {d}")
    print("=" * 78)
    sys.exit(1 if RED else 0)


if __name__ == "__main__":
    main()
