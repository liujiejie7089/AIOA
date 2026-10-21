-- V92 · 补齐「漏播种」的租户级默认流程
--
-- 发现过程（docs/57 接线哨兵跑出来的真实缺口）：
--   租户 1 只有 V89 补建的 19 条员工侧流程 + 3 条删除类，**没有 LEAVE / PERMISSION_GRANT /
--   QUOTA_EXPAND / RESOURCE_OPEN**。这四条是 ApprovalFlowProvisioner 的老 DEFAULTS，
--   只在「新租户入驻事件」时播种 —— 租户 1 早于该机制（或当时播种失败），于是永远缺。
--
-- 后果并不轻微：ApprovalFlowService.expandNodes 在「该 bizType 没有 ACTIVE 流程定义」时
-- 会退化成单节点默认审批人（DEFAULT_APPROVER_TYPE = ORG_ADMIN）。也就是说租户 1 的请假单
-- **不会走「部门负责人 → 企业管理员」两级，而是被静默派给机构管理员单级审批**，
-- 与 docs/55 P0-4「新租户缺审批流静默退化」是同一类缺陷，只是发生在一个老租户身上。
--
-- 本迁移：为所有「有 worker_capability 的真实租户（tenant_id > 0）」补齐缺失的标准默认流程，
-- 口径与 ApprovalFlowProvisioner.DEFAULTS 完全一致；已存在的跳过，可重复执行。

INSERT INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark, created_at, created_by)
SELECT t.tenant_id, 0, s.biz_type, s.name, s.steps_json, 'ACTIVE',
       '租户级默认流程：漏播种补齐（V92）', NOW(6), 0
  FROM (SELECT DISTINCT tenant_id FROM worker_capability WHERE tenant_id > 0) t
  JOIN (
        SELECT 'PERMISSION_GRANT' AS biz_type,
               '租户默认权限申请审批流（部门负责人一级审批 + 抄送企业管理员）' AS name,
               '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1, "cc": ["ORG_ADMIN"]}]' AS steps_json
        UNION ALL SELECT 'LEAVE',
               '租户默认请假审批流（部门负责人 → 企业管理员，≤3 天跳级）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN", "threshold_days": 3}]'
        UNION ALL SELECT 'QUOTA_EXPAND',
               '租户默认额度扩容审批流（企业管理员 → 租户管理员）',
               '[{"seq": 1, "approver_type": "ORG_ADMIN", "cc": ["TENANT_ADMIN"]}, {"seq": 2, "approver_type": "TENANT_ADMIN"}]'
        UNION ALL SELECT 'RESOURCE_OPEN',
               '租户默认资源开通审批流（企业管理员 → 租户管理员）',
               '[{"seq": 1, "approver_type": "ORG_ADMIN", "cc": ["TENANT_ADMIN"]}, {"seq": 2, "approver_type": "TENANT_ADMIN"}]'
        UNION ALL SELECT 'DEPT_DELETE',
               '租户默认部门删除审批流（上一级审批）',
               '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1}]'
        UNION ALL SELECT 'INSTITUTION_DELETE',
               '租户默认机构删除审批流（上一级审批）',
               '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1}]'
        UNION ALL SELECT 'TENANT_DELETE',
               '租户默认租户删除审批流（上一级审批）',
               '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1}]'
       ) s
 WHERE NOT EXISTS (
        SELECT 1 FROM approval_flow_def d
         WHERE d.tenant_id = t.tenant_id
           AND d.institution_id = 0
           AND d.biz_type = s.biz_type
       );
