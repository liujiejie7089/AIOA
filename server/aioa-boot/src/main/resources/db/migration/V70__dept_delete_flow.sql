-- V70：删除类审批流补齐「部门删除」（DEPT_DELETE）的租户级默认流程
--
-- 背景：V69 已为机构 / 租户删除播种了默认流程，但四层里的**部门**那一层当时漏了 ——
-- 而 `DELETE /api/v1/org/departments/{id}` 原本是**直接删**（只有级联前置校验，没有审核闸门）。
-- 需求原文是「**任何**一层级的首次删除操作都需要经过上一级审核后方可执行」，
-- 只给机构和租户加审核、把部门留着直删是明显的半成品：越往下越松，而部门恰恰是日常最常删的一层。
--
-- ★ 为什么不能省（不配流程会静默指错审批人，与 V69 同一条理由）：
--   ApprovalFlowService.expandNodes 在「该 bizType 查不到 ACTIVE 流程定义」时会把 nodes 兜底成
--   单节点 DEFAULT_APPROVER_TYPE（= ORG_ADMIN）。对部门删除而言这个兜底尤其危险：
--   若申请人本人就是机构管理员，兜底会把审批人指派成**申请人自己**（自己审自己），
--   而 expandNodes 的通用分支**不做**自审防护（自审防护只在 superiorLadder 里）。
--
-- 语义：APPLICANT_SUPERIOR + levels=1 = 只取「申请人的上一级」这一个梯级
--   部门负责人申请 → 机构管理员；机构管理员申请 → 租户管理员；租户管理员申请 → 平台管理员
--
-- 幂等：LEFT JOIN 判重，只补缺、不覆盖。
-- 新租户入驻由 ApprovalFlowProvisioner 自动播种（同一份 steps_json，两处口径必须一致）。

INSERT INTO approval_flow_def (tenant_id, institution_id, biz_type, name, steps_json,
                               status, remark, created_at, created_by)
SELECT t.id, 0, 'DEPT_DELETE', '租户默认部门删除审批流（上一级审批）',
       '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1}]',
       'ACTIVE', '租户级默认流程：部门无子部门无员工方可申请，经上一级批准后删除（V70 播种）',
       NOW(6), 0
FROM sys_tenant t
LEFT JOIN approval_flow_def d
       ON d.tenant_id = t.id AND d.institution_id = 0 AND d.biz_type = 'DEPT_DELETE'
WHERE t.deleted_at IS NULL AND t.id <> 0 AND d.id IS NULL;
