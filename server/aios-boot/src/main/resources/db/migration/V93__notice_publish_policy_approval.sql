-- V93 · 通知公告提交改走审批流
--
-- 背景（用户明确要求「后台要收到审批/申请」）：
--   form_template 里 code='notice_publish' 的 submit_policy 一直是 'LEDGER'
--   （提交即 DONE，不生成审批单），且 biz_type 为 NULL。
--
-- 改法（只动 notice_publish 这一条业务，不影响其它表单）：
--   ① 把 notice_publish 的 submit_policy 改为 'APPROVAL'；
--      同时把 biz_type 设为 'NOTICE_PUBLISH' ——
--      FormSubmissionService.submit 在 APPROVAL 分支会调 ApprovalFlowService.submit，
--      后者要求 bizType 非空（否则直接抛「bizType 不能为空」），原 biz_type=NULL 会导致提交失败。
--   ② 为「库里实际存在 notice_publish 模板」的每一个租户（含平台租户 0）补种一条
--      默认审批流（企业管理员一级审批，approver_type='ORG_ADMIN'），
--      口径与 V89/V92 的租户默认流对齐。若运行时某租户未命中显式流，
--      审批引擎会退化成 DEFAULT_APPROVER_TYPE 单节点（仍不会失败）；
--      这里显式种流，保证通知公告审批稳定路由到企业管理员。
--
-- 幂等：① 只改 submit_policy <> 'APPROVAL' 的行；② 用 NOT EXISTS 防重。

-- ---------------------------------------------------------------------------
-- ① 表单模板：策略 + 业务类型
-- ---------------------------------------------------------------------------
UPDATE form_template
   SET submit_policy = 'APPROVAL',
       biz_type      = 'NOTICE_PUBLISH',
       updated_at    = NOW(6)
 WHERE code = 'notice_publish'
   AND submit_policy <> 'APPROVAL';

-- ---------------------------------------------------------------------------
-- ② 为每个有 notice_publish 模板的租户补种默认审批流
-- ---------------------------------------------------------------------------
INSERT INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark, created_at, created_by)
SELECT t.tenant_id,
       0,
       'NOTICE_PUBLISH',
       '租户默认通知公告审批流（企业管理员）',
       '[{"seq": 1, "approver_type": "ORG_ADMIN"}]',
       'ACTIVE',
       '通知公告默认审批流：V93 补种',
       NOW(6),
       0
  FROM (SELECT DISTINCT tenant_id FROM form_template WHERE code = 'notice_publish') t
 WHERE NOT EXISTS (
        SELECT 1 FROM approval_flow_def d
         WHERE d.tenant_id = t.tenant_id
           AND d.institution_id = 0
           AND d.biz_type = 'NOTICE_PUBLISH'
       );
