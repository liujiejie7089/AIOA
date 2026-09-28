-- V69：删除类审批流（机构删除 / 租户删除）的租户级默认流程
--
-- 背景（需求原文）：「新增级联删除功能：删除部门前必须先删除该部门下的所有成员；删除机构前必须先
-- 删除该机构下的所有部门；删除租户前必须先删除该租户下的所有部门。此外，任何一层级的首次删除操作
-- 都需要经过上一级审核后方可执行。」
--
-- 本迁移只解决「流程定义」这一半：删除动作必须经上一级批准才执行，因此必须为这两个 bizType
-- 播种租户级默认流。
--
-- ★ 为什么不能省（不配流程会静默指错审批人）：
--   ApprovalFlowService.expandNodes 在「该 bizType 查不到 ACTIVE 流程定义」时，会把 nodes 兜底成
--   单节点 DEFAULT_APPROVER_TYPE（= ORG_ADMIN）。对删除类单据来说，那意味着「申请删除租户」
--   会被派给机构管理员而不是平台管理员 —— 兜底把配置缺陷伪装成「能用」，正是 pitfalls 反复警告的形态。
--
-- 语义：APPLICANT_SUPERIOR + levels=1 = 只取「申请人的上一级」这一个梯级（与 PERMISSION_GRANT 同口径）
--   机构删除：申请人=机构管理员 → 租户管理员
--   租户删除：申请人=租户管理员 → 平台管理员
--
-- 幂等：LEFT JOIN 判重，只补缺、不覆盖（租户管理员改过的流程不会被塞回去）。
-- 新租户入驻由 ApprovalFlowProvisioner 自动播种（同一份 steps_json，两处口径必须一致）。

-- 机构删除
INSERT INTO approval_flow_def (tenant_id, institution_id, biz_type, name, steps_json,
                               status, remark, created_at, created_by)
SELECT t.id, 0, 'INSTITUTION_DELETE', '租户默认机构删除审批流（上一级审批）',
       '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1}]',
       'ACTIVE', '租户级默认流程：机构无部门无员工方可申请，经上一级（租户管理员）批准后删除（V69 播种）',
       NOW(6), 0
FROM sys_tenant t
LEFT JOIN approval_flow_def d
       ON d.tenant_id = t.id AND d.institution_id = 0 AND d.biz_type = 'INSTITUTION_DELETE'
WHERE t.deleted_at IS NULL AND t.id <> 0 AND d.id IS NULL;

-- 租户删除
INSERT INTO approval_flow_def (tenant_id, institution_id, biz_type, name, steps_json,
                               status, remark, created_at, created_by)
SELECT t.id, 0, 'TENANT_DELETE', '租户默认租户删除审批流（上一级审批）',
       '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1}]',
       'ACTIVE', '租户级默认流程：租户无机构无部门无员工方可申请，经平台管理员批准后删除并冻结其账号（V69 播种）',
       NOW(6), 0
FROM sys_tenant t
LEFT JOIN approval_flow_def d
       ON d.tenant_id = t.id AND d.institution_id = 0 AND d.biz_type = 'TENANT_DELETE'
WHERE t.deleted_at IS NULL AND t.id <> 0 AND d.id IS NULL;
