# -*- coding: utf-8 -*-
"""
_dryrun_oa_module_forms.py — V86 迁移 dry-run 校验（docs/52 P5）
================================================================================

在真实库 aios 上**只读式**校验 V86 是否可正确执行并产出预期计数：
  - 若 V85 四张表尚未存在（本机后端未重启，符合预期），则在**事务内**按 V85 的 DDL 建表；
  - 跑 V86 全部 INSERT；
  - 查出三个计数：43 个平台模板 / 43 个平台版本 / worker_capability 覆盖 43 个模块；
  - **ROLLBACK** 撤销所有 INSERT（业务数据绝不提交）；
  - **DROP** 掉测试期间建的 V85 四表，把库恢复到执行前状态；
  - 报告三计数与 rollback 证据。

安全约束
--------
- 绝不 COMMIT 任何业务数据；
- 若 V85 四表已有任意一张存在（说明后端已应用过），脚本直接中止，**不DROP、不改动**，
  避免误删 lead 已落地的表；
- finally 中无论如何都尝试 DROP 测试表，保证库干净。

运行：python scripts/_dryrun_oa_module_forms.py
依赖：pymysql
"""
import os
import sys

import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
V85 = os.path.join(REPO, "server", "aios-boot", "src", "main", "resources", "db", "migration", "V85__form_domain.sql")
V86 = os.path.join(REPO, "server", "aios-boot", "src", "main", "resources", "db", "migration", "V86__oa_module_forms.sql")

FORM_TABLES = ["form_template", "form_template_version", "form_submission", "worker_capability"]

CODES = [
    "doc_draft", "archive_borrow", "meeting_book", "contact_add", "worklog_submit",
    "workplan_submit", "weekly_submit", "expense_form", "travel_form", "seal_apply",
    "project_create", "favorite_add", "milestone_add", "calendar_event", "notice_publish",
    "publish_article", "assign_task", "remind_rule", "vehicle_apply", "leave_request",
    "attendance_appeal", "doc_upload", "party_apply", "union_apply", "todo_add",
    "delegate_rule", "portal_layout", "approval_launch", "hr_register", "recruit_req",
    "train_signup", "knowledge_upload", "asset_apply", "contract_draft", "task_supervise",
    "crm_add", "finance_apply", "purchase_req", "survey_launch", "security_apply",
    "integration_req", "analytics_board", "mobile_checkin",
]


def split_stmts(text):
    """按 ';' 切分语句；逐行剔除以 -- 开头的注释行，仅保留含真实语句的片段。

    注意：V85/V86 的注释常与语句同行段（如首段为「头注释 + CREATE TABLE ...」），
    不能整段丢弃，否则会漏执行 CREATE TABLE。
    """
    out = []
    for part in text.split(";"):
        lines = [ln for ln in part.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        s = "\n".join(lines).strip()
        if s:
            out.append(s)
    return out


def main():
    with open(V85, encoding="utf-8") as fh:
        v85_sql = fh.read()
    with open(V86, encoding="utf-8") as fh:
        v86_sql = fh.read()

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", autocommit=False, connect_timeout=10)
    cur = conn.cursor()

    try:
        # 0) 安全检查：V85 表是否已存在
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='aios' AND TABLE_NAME IN %s", (FORM_TABLES,)
        )
        existing = sorted(r[0] for r in cur.fetchall())
        if existing:
            print("ABORT: 以下 V85 表已存在，疑似后端已应用，停止 dry-run 以免误改：%s" % existing)
            sys.exit(2)

        # 1) 事务内按 V85 建表（DDL 会隐式提交，但表是临时的，finally 会 DROP）
        print("== 按 V85 DDL 建临时表（事务内）==")
        for stmt in split_stmts(v85_sql):
            cur.execute(stmt)

        # 2) 跑 V86（INSERT 在事务中，未提交）
        print("== 执行 V86 全部 INSERT（事务内，未提交）==")
        n = 0
        for stmt in split_stmts(v86_sql):
            cur.execute(stmt)
            n += 1
        print("   V86 语句数=%d" % n)

        # 3) 三计数
        cur.execute(
            "SELECT COUNT(*) FROM form_template WHERE tenant_id=0 AND code IN %s", (CODES,)
        )
        cnt_template_platform = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM form_template_version v "
            "JOIN form_template f ON f.id=v.template_id WHERE f.tenant_id=0"
        )
        cnt_version_platform = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT form_code) FROM worker_capability")
        cnt_cap_distinct = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM worker_capability")
        cnt_cap_total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM form_template WHERE tenant_id>0")
        cnt_template_tenant = cur.fetchone()[0]

        # 4) ROLLBACK：撤销所有 INSERT 业务数据（绝不提交）
        conn.rollback()
        print("== ROLLBACK 完成（业务数据已撤销，未提交）==")

        # rollback 后复查：表应还在，但业务数据应为 0
        cur.execute("SELECT COUNT(*) FROM form_template")
        after_rollback_rows = cur.fetchone()[0]

        # 5) DROP 临时表，恢复库到执行前
        for t in FORM_TABLES:
            cur.execute("DROP TABLE IF EXISTS `%s`" % t)
        print("== DROP 临时表完成：%s ==" % ", ".join(FORM_TABLES))

        # 6) 最终确认：V85 表应已不存在
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='aios' AND TABLE_NAME IN %s", (FORM_TABLES,)
        )
        leftover = sorted(r[0] for r in cur.fetchall())

        print("\n================ DRY-RUN 结果 ================")
        print("计数 A · 平台 form_template (tenant=0, 43 codes) = %d  (期望 43)" % cnt_template_platform)
        print("计数 B · 平台 form_template_version            = %d  (期望 43)" % cnt_version_platform)
        print("计数 C · worker_capability 覆盖 distinct form_code = %d  (期望 43)" % cnt_cap_distinct)
        print("        worker_capability 总行数              = %d  (期望 ≥ 43, 含租户实例)" % cnt_cap_total)
        print("        回填租户 form_template 行数           = %d" % cnt_template_tenant)
        print("ROLLBACK 证据: rollback 后 form_template 行数 = %d (期望 0)" % after_rollback_rows)
        print("DROP 证据    : 执行后残留 V85 表             = %s (期望 [])" % leftover)
        print("==============================================")

        ok = (cnt_template_platform == 43 and cnt_version_platform == 43
              and cnt_cap_distinct == 43 and after_rollback_rows == 0 and leftover == [])
        print("RESULT:", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
    except Exception as e:
        conn.rollback()
        print("ERROR:", repr(e))
        sys.exit(3)
    finally:
        # 无论如何都尝试 DROP 临时表，保证库干净（若上面已 DROP 则 IF EXISTS 无害）
        try:
            for t in FORM_TABLES:
                cur.execute("DROP TABLE IF EXISTS `%s`" % t)
        except Exception:
            pass
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
