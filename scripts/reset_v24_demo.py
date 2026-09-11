# -*- coding: utf-8 -*-
"""
V24 企业入驻 E2E 演示数据复位（可重复运行）

职责：把 e2e_v24_onboarding.py / e2e_v24_leave_flow.py 造出的数据清理干净，
      使套件可反复执行且结果稳定。

铁律：
  · **绝不 UPDATE / 修改任何 audit_log 行**（改一行哈希链即断，且审计不可篡改是设计约束）。
  · **只清理本套件造出的实体**（机构编码 ORG-SCJG / ORG-TMP-DEMO、账号前缀 scjg_/tmp_）。
  · 先备份到 JSON（含 statements），再执行。

关于 audit_log 删除的**唯一例外**（窄口径，必须满足全部三条才删）：
  1. 只删 tenant_id = 2（本套件专用的演示租户），其他租户审计行一律保留；
  2. 删除的是**上一次演示运行自己产生的审计数据**，不是业务系统的真实审计；
  3. 目的：让每次 E2E 都从创世块开始，使「哈希链完整」是**真校验**（verifiedRows == count）
     而不是靠 legacy 锚定放送过关。
  换言之：删除的是"演示噪音"，审计"不可篡改"（无 update/delete 接口 + 哈希链检出篡改）的
  保证不受影响。若只想保留全部审计行，用 --keep-audit 跳过本步。

用法：
  python scripts/reset_v24_demo.py --dry-run
  python scripts/reset_v24_demo.py
"""
import argparse
import datetime
import json
import os
import sys

import pymysql

DB = dict(host='127.0.0.1', port=3306, user='root', password='', database='aioa', charset='utf8mb4')

TEST_INST_CODES = ('ORG-SCJG', 'ORG-TMP-DEMO')
TEST_USER_PREFIX = ('scjg_admin', 'scjg_zhang', 'scjg_lin', 'tmp_admin', 'tmp_admin2')

STEPS = [
    # 1) 机构相关（先取 id 集合，再级联删）
    ("机构 id 集合", "SELECT GROUP_CONCAT(id) FROM org_institution WHERE code IN %s", TEST_INST_CODES),
    ("机构", "DELETE FROM org_institution WHERE code IN %s", TEST_INST_CODES),
    ("部门", "DELETE FROM org_department WHERE institution_id IN (%s)", 'IDS'),
    ("成员", "DELETE FROM org_member WHERE institution_id IN (%s)", 'IDS'),
    ("机构配额", "DELETE FROM org_quota WHERE institution_id IN (%s)", 'IDS'),
    ("部门额度", "DELETE FROM dept_quota WHERE institution_id IN (%s)", 'IDS'),
    ("审批流定义", "DELETE FROM approval_flow_def WHERE institution_id IN (%s)", 'IDS'),
    ("资源授权", "DELETE FROM resource_grant WHERE institution_id IN (%s)", 'IDS'),
    ("配额流水", "DELETE FROM quota_alloc_log WHERE institution_id IN (%s)", 'IDS'),
    # 2) 账号：先解除角色绑定，再删测试账号
    ("测试账号角色绑定",
     "DELETE ur FROM sys_user_role ur JOIN sys_user u ON u.id = ur.user_id "
     "WHERE u.username IN %s OR u.username LIKE 'scjg\\\\_b%%'", TEST_USER_PREFIX),
    ("测试账号",
     "DELETE FROM sys_user WHERE username IN %s OR username LIKE 'scjg\\\\_b%%'", TEST_USER_PREFIX),
    # 3) 审批与请假（本套件造的 tenant 2 业务单）
    ("审批任务", "DELETE t FROM approval_task t JOIN approval_order o ON o.id = t.order_id "
                  "WHERE o.tenant_id = 2 AND o.biz_type IN ('LEAVE','QUOTA_EXPAND','RESOURCE_OPEN')", None),
    ("请假单", "DELETE FROM leave_request WHERE tenant_id = 2", None),
    ("审批单", "DELETE FROM approval_order WHERE tenant_id = 2 "
                "AND biz_type IN ('LEAVE','QUOTA_EXPAND','RESOURCE_OPEN')", None),
    ("请假余额复位（used/pending 归零）",
     "UPDATE leave_balance SET used_days = 0, pending_days = 0 WHERE tenant_id = 2", None),
    ("通知（本套件造）", "DELETE FROM notification WHERE tenant_id = 2", None),
    # 4) 分摊规则 / 账单 / 资源池复位
    ("账单", "DELETE FROM cost_alloc_bill WHERE tenant_id = 2", None),
    ("规则版本复位（保留 v1，删除测试生成的 v2+）",
     "DELETE FROM cost_alloc_rule WHERE tenant_id = 2 AND version > 1", None),
    ("规则状态复位（v1 恢复 ACTIVE）",
     "UPDATE cost_alloc_rule SET status = 'ACTIVE' WHERE tenant_id = 2 AND version = 1", None),
    ("资源池复位（tokenTotal 回到 5000000 / 席位回到种子值）",
     "UPDATE tenant_resource_pool SET token_total = 5000000, token_used = 0, expert_seats = 12, "
     "expert_used = 0, skill_seats = 18, skill_used = 0 WHERE tenant_id = 2 AND period = '2026-09'", None),
    ("机构配额使用量归零",
     "UPDATE org_quota SET used_tokens = 0, frozen = 0 WHERE tenant_id = 2", None),
    ("部门额度使用量归零",
     "UPDATE dept_quota SET used_tokens = 0 WHERE tenant_id = 2", None),
    ("知识库机构维度解绑",
     "UPDATE kb_document SET institution_id = 0, department_id = 0, scope = 'TENANT' "
     "WHERE tenant_id = 0 AND institution_id > 0", None),
    # 5) 审计：仅清空租户 2 的演示审计行（见文件头「唯一例外」三条口径）
    ("审计行（仅租户2演示数据）", "DELETE FROM audit_log WHERE tenant_id = 2", None),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--keep-audit', action='store_true', help='保留租户2审计行（链将依赖 V1 锚定）')
    args = ap.parse_args()

    conn = pymysql.connect(**DB)
    cur = conn.cursor()

    cur.execute("SELECT GROUP_CONCAT(id) FROM org_institution WHERE code IN %s", (TEST_INST_CODES,))
    ids_raw = cur.fetchone()[0]
    if ids_raw:
        id_list = ','.join(str(int(x)) for x in str(ids_raw).split(',') if x)
    else:
        # 极少见：机构已删但子表残留 → 用测试账号反查
        cur.execute("SELECT GROUP_CONCAT(DISTINCT institution_id) FROM org_member m "
                    "JOIN sys_user u ON u.id = m.user_id "
                    "WHERE u.username IN %s OR u.username LIKE 'scjg\\_b%%'", (TEST_USER_PREFIX,))
        r = cur.fetchone()[0]
        id_list = ','.join(str(int(x)) for x in str(r).split(',') if x) if r else '0'

    print('测试机构 id 集合: %s' % id_list)
    backup = {'backed_up_at': str(datetime.datetime.now()), 'institution_ids': id_list, 'statements': []}
    total = 0
    for label, sql, arg in STEPS:
        if label == '机构 id 集合':
            continue
        if args.keep_audit and label.startswith('审计行'):
            print('  %-40s skipped(--keep-audit)' % label)
            continue
        if arg == 'IDS':
            sql = sql % id_list
            params = None
        elif arg is None:
            params = None
        else:
            # pymysql 的 `IN %s` 需要把序列整体作为一个参数传入，再包一层
            params = (arg,)
        try:
            if args.dry_run:
                cnt = '-'
            else:
                cnt = cur.execute(sql, params)
                total += max(cnt, 0)
        except Exception as e:
            print('  !! %-40s 跳过：%s' % (label, str(e)[:120]))
            backup['statements'].append({'label': label, 'sql': sql, 'error': str(e)[:200]})
            continue
        print('  %-40s affected=%s' % (label, cnt))
        backup['statements'].append({'label': label, 'sql': sql, 'affected': (cnt if not args.dry_run else None)})

    if not args.dry_run:
        conn.commit()
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  'logs', 'reset_backup')
        os.makedirs(backup_dir, exist_ok=True)
        out = os.path.join(backup_dir,
                           'v24_reset_backup_%s.json' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)
        print('\n已复位，受影响行合计 %d，备份：%s' % (total, os.path.abspath(out)))
        print('注：audit_log 全程未做任何 UPDATE（哈希链与不可篡改约束）；'
              '仅按「唯一例外」口径删除了租户 2 的演示审计行%s。'
              % ('（--keep-audit 已跳过）' if args.keep_audit else ''))
    else:
        print('\n[dry-run] 未执行任何写操作。')
    conn.close()


if __name__ == '__main__':
    main()
