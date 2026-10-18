-- V37 权限申请审批流（PERMISSION_GRANT）租户默认定义
--
-- 需求①明写「本地存档 → 部门审批 → 返回结果」：
--   第 1 级固定 DEPT_LEADER（部门审批）
--   第 2 级固定 TENANT_ADMIN（权限发放属租户级治理动作，与 approval:leave 的授权角色集合
--   PermissionCatalog.TENANT_ADMINS 一致）
--
-- 沿用 V26 模式：institution_id = 0 为租户级默认；机构可再建专属定义覆盖。
-- 部门未设负责人时，ApprovalFlowService.expandNodes 既有兜底会自动改由企业管理员审批
-- 并把原因写进 task.note，无需额外代码。
INSERT IGNORE INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark)
SELECT t.id,
       0,
       'PERMISSION_GRANT',
       '租户默认权限申请审批流（部门负责人 → 租户管理员）',
       CAST('[{"seq": 1, "approver_type": "DEPT_LEADER"}, {"seq": 2, "approver_type": "TENANT_ADMIN"}]' AS JSON),
       'ACTIVE',
       '权限申请默认流程：部门审批后由租户管理员发放（V37）'
FROM sys_tenant t;
