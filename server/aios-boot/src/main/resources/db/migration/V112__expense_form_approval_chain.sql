-- V112 · 费用报销改走审批流（docs/88 全链路测试确认的「假审批」缺陷）
--
-- 背景：用户发起费用报销后，用户端「我的申请」无记录、管理端收不到审批申请。
--   2026-11-17 全链路真机测试（docs/88）确认根因：
--     · form_template 里 code='expense_form' 的 submit_policy 一直是 'LEDGER'
--       （提交即 DONE，不生成审批单），且 biz_type 为 NULL。
--     · FormSubmissionService.submit 在 LEDGER 分支只写 form_submission，不调
--       ApprovalFlowService.submit，因此没有 approval_order / approval_task。
--     · 而用户端「我的申请」读 /workflow/mine、管理端待办读 /workflow/tasks?scope=todo，
--       两者都以审批单为数据源 ⇒ 两端都看不到，更谈不上状态流转与通知。
--
-- 改法（与 V93 通知公告完全同型，只动 expense_form 这一条业务）：
--   ① 把 expense_form 的 submit_policy 改为 'APPROVAL'，biz_type 设为 'EXPENSE'。
--      APPROVAL 分支会调 ApprovalFlowService.submit，后者要求 bizType 非空。
--   ② 为「库里实际存在 expense_form 模板」的每个租户（含平台租户 0）补种一条
--      默认审批流（部门负责人 → 企业管理员，抄送企业管理员），
--      与 tenant≥1 已有的 EXPENSE 流口径一致。tenant=0 此前**没有** EXPENSE 流，
--      不补的话 zhangsan（tenant=0）提交会因找不到流程定义而静默降级成单级 ORG_ADMIN。
--
-- 幂等：① 只改 submit_policy <> 'APPROVAL' 或 biz_type 为空的行；② 用 NOT EXISTS 防重。

-- ---------------------------------------------------------------------------
-- ① 表单模板：策略 + 业务类型
-- ---------------------------------------------------------------------------
UPDATE form_template
   SET submit_policy = 'APPROVAL',
       biz_type      = 'EXPENSE',
       updated_at    = NOW(6)
 WHERE code = 'expense_form'
   AND (submit_policy <> 'APPROVAL' OR biz_type IS NULL OR biz_type = '');

-- ---------------------------------------------------------------------------
-- ② 为每个有 expense_form 模板的租户补种默认审批流
-- ---------------------------------------------------------------------------
INSERT INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark, created_at, created_by)
SELECT t.tenant_id,
       0,
       'EXPENSE',
       '租户默认费用报销审批流（部门负责人 → 企业管理员）',
       '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]',
       'ACTIVE',
       '费用报销默认审批流：V112 补种（含平台租户 0）',
       NOW(6),
       0
  FROM (SELECT DISTINCT tenant_id FROM form_template WHERE code = 'expense_form') t
 WHERE NOT EXISTS (
        SELECT 1 FROM approval_flow_def d
         WHERE d.tenant_id = t.tenant_id
           AND d.institution_id = 0
           AND d.biz_type = 'EXPENSE'
       );
