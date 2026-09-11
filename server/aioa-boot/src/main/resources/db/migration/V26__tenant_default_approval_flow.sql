-- 租户级默认审批流（institution_id = 0）
--
-- 背景：审批流定义只配到了具体机构（此前仅机构 1 有 QUOTA_EXPAND / RESOURCE_OPEN）。
--       新机构入驻后若没有对应 biz_type 的定义，ApprovalFlowService 会兜底成
--       「单级 ORG_ADMIN」—— 意味着 30 万词元扩容、模型资源开通这类有实质影响的申请，
--       只要企业管理员一人同意即生效，静默绕过了租户管理员这道关（控制缺陷）。
--
-- 处理：为每个租户补一套 institution_id = 0 的默认流。
--       解析优先级：机构专属定义 > 租户级默认 > 内置单级兜底。
--       这样新机构一入驻就自动具备标准的二级审批，不会再静默降级。
INSERT IGNORE INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark)
SELECT t.id,
       0,
       d.biz_type,
       d.name,
       CAST(d.steps_json AS JSON),
       'ACTIVE',
       '租户级默认流程：机构未单独配置时自动生效（V26）'
FROM sys_tenant t
         JOIN (
    SELECT 'LEAVE'          AS biz_type,
           '租户默认请假审批流（部门负责人 → 企业管理员，≤3 天跳级）' AS name,
           '[{"seq": 1, "approver_type": "DEPT_LEADER"}, {"seq": 2, "approver_type": "ORG_ADMIN", "threshold_days": 3}]' AS steps_json
    UNION ALL
    SELECT 'QUOTA_EXPAND',
           '租户默认额度扩容审批流（企业管理员 → 租户管理员）',
           '[{"seq": 1, "approver_type": "ORG_ADMIN"}, {"seq": 2, "approver_type": "TENANT_ADMIN"}]'
    UNION ALL
    SELECT 'RESOURCE_OPEN',
           '租户默认资源开通审批流（企业管理员 → 租户管理员）',
           '[{"seq": 1, "approver_type": "ORG_ADMIN"}, {"seq": 2, "approver_type": "TENANT_ADMIN"}]'
) d;
