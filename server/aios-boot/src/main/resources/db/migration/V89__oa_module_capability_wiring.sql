-- V89 · OA 43 模块能力接线（工具绑定 + 审批流补建）
--
-- 背景（对应 docs/57 全链路体检）：
--   43 个模块的表单（form_template 516 行）与数字人（agent_worker 516 行）都已就绪，
--   但 worker_capability 这一层**没有接上任何东西**，导致「表单 → 能力 → 工具 → 审批流」整条链空转：
--     · tool_names_json  516/516 为空   → 数字人不知道自己能调什么工具
--     · approval_biz_type 504/516 为 NULL → 不知道提交后走哪条审批流
--     · approval_flow_def 只有 LEAVE + 管理类 → 报销/用印/出差等提交了也没有路由
--
-- 本迁移做三件事（**只回填、不覆盖已有的人工配置**）：
--   ① 为每个模块的能力补上工具清单（tool_names_json）
--   ② 为「申请→批准」类模块补上审批业务类型（approval_biz_type）
--   ③ 为现有租户补建这些业务类型的默认审批流（approval_flow_def），口径与
--      ApprovalFlowProvisioner.DEFAULTS 保持一致（本文件新增的条目也会同步进该常量）
--
-- 幂等：① ② 只改「当前为空」的行；③ 用 NOT EXISTS 判断，重复执行不会插重。

-- ---------------------------------------------------------------------------
-- ① + ②：能力表接线
-- ---------------------------------------------------------------------------

-- 审批类模块：能查待办、能查我发起的，部分可查额度
UPDATE worker_capability
   SET tool_names_json = '["list_todo_approvals","list_my_approvals"]'
 WHERE alive = 1
   AND (tool_names_json IS NULL OR tool_names_json = '' OR tool_names_json = '[]')
   AND form_code IN ('seal_apply', 'vehicle_apply', 'archive_borrow', 'attendance_appeal',
                     'train_signup', 'recruit_req', 'integration_req', 'meeting_book',
                     'project_create', 'hr_register', 'union_apply', 'party_apply');

UPDATE worker_capability
   SET tool_names_json = '["list_todo_approvals","list_my_approvals","get_my_quota"]'
 WHERE alive = 1
   AND (tool_names_json IS NULL OR tool_names_json = '' OR tool_names_json = '[]')
   AND form_code IN ('expense_form', 'travel_form', 'asset_apply', 'purchase_req', 'finance_apply');

UPDATE worker_capability
   SET tool_names_json = '["list_todo_approvals","list_my_approvals","search_kb_documents"]'
 WHERE alive = 1
   AND (tool_names_json IS NULL OR tool_names_json = '' OR tool_names_json = '[]')
   AND form_code IN ('contract_draft', 'security_apply');

-- 文档/知识类：以检索为主
UPDATE worker_capability
   SET tool_names_json = '["search_kb_documents","list_my_approvals"]'
 WHERE alive = 1
   AND (tool_names_json IS NULL OR tool_names_json = '' OR tool_names_json = '[]')
   AND form_code IN ('doc_draft', 'doc_upload', 'knowledge_upload', 'publish_article',
                     'notice_publish', 'analytics_board', 'crm_add');

-- 其余纯记录类模块：至少能回答「我提交过什么」
UPDATE worker_capability
   SET tool_names_json = '["list_my_approvals"]'
 WHERE alive = 1
   AND (tool_names_json IS NULL OR tool_names_json = '' OR tool_names_json = '[]');

-- 审批业务类型：仅「申请 → 批准」类模块有路由，其余保持 NULL（不需要审批）
UPDATE worker_capability SET approval_biz_type = 'EXPENSE'
 WHERE alive = 1 AND form_code = 'expense_form' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'SEAL'
 WHERE alive = 1 AND form_code = 'seal_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'TRAVEL'
 WHERE alive = 1 AND form_code = 'travel_form' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'PURCHASE'
 WHERE alive = 1 AND form_code = 'purchase_req' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'VEHICLE'
 WHERE alive = 1 AND form_code = 'vehicle_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'ASSET'
 WHERE alive = 1 AND form_code = 'asset_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'CONTRACT'
 WHERE alive = 1 AND form_code = 'contract_draft' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'ARCHIVE_BORROW'
 WHERE alive = 1 AND form_code = 'archive_borrow' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'ATTENDANCE_APPEAL'
 WHERE alive = 1 AND form_code = 'attendance_appeal' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'TRAIN_SIGNUP'
 WHERE alive = 1 AND form_code = 'train_signup' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'RECRUIT_REQ'
 WHERE alive = 1 AND form_code = 'recruit_req' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'FINANCE_APPLY'
 WHERE alive = 1 AND form_code = 'finance_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'SECURITY_APPLY'
 WHERE alive = 1 AND form_code = 'security_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'INTEGRATION_REQ'
 WHERE alive = 1 AND form_code = 'integration_req' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'MEETING_BOOK'
 WHERE alive = 1 AND form_code = 'meeting_book' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'PROJECT_CREATE'
 WHERE alive = 1 AND form_code = 'project_create' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'HR_REGISTER'
 WHERE alive = 1 AND form_code = 'hr_register' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'UNION_APPLY'
 WHERE alive = 1 AND form_code = 'union_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');
UPDATE worker_capability SET approval_biz_type = 'PARTY_APPLY'
 WHERE alive = 1 AND form_code = 'party_apply' AND (approval_biz_type IS NULL OR approval_biz_type = '');

-- ---------------------------------------------------------------------------
-- ③：为现有租户补建员工侧默认审批流
--     口径与 ApprovalFlowProvisioner.DEFAULTS 对齐：
--       · 一般申请：部门负责人一级审批，抄送企业管理员（可见可督办，不阻塞）
--       · 涉钱/涉章/涉合同：部门负责人 → 企业管理员 两级
--       · 权限类：申请人上一级 → 企业管理员（与 PERMISSION_GRANT 同口径）
-- ---------------------------------------------------------------------------

INSERT INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark, created_at, created_by)
SELECT t.tenant_id,
       0,
       s.biz_type,
       s.name,
       s.steps_json,
       'ACTIVE',
       '租户级默认流程：43 模块能力接线补建（V89）',
       NOW(6),
       0
  FROM (SELECT DISTINCT tenant_id FROM approval_flow_def WHERE tenant_id > 0) t
  JOIN (
        -- 涉钱 / 涉章 / 涉合同：两级审批
        SELECT 'EXPENSE' AS biz_type, '租户默认费用报销审批流（部门负责人 → 企业管理员）' AS name,
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]' AS steps_json
        UNION ALL SELECT 'PURCHASE', '租户默认采购审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'CONTRACT', '租户默认合同审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'FINANCE_APPLY', '租户默认财务审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'SEAL', '租户默认用印审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'ASSET', '租户默认资产领用审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        -- 一般申请：一级审批 + 抄送
        UNION ALL SELECT 'TRAVEL', '租户默认出差审批流（部门负责人，抄送企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'VEHICLE', '租户默认用车审批流（部门负责人，抄送企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'ARCHIVE_BORROW', '租户默认档案借阅审批流（部门负责人，抄送企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'ATTENDANCE_APPEAL', '租户默认考勤申诉审批流（部门负责人，抄送企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'TRAIN_SIGNUP', '租户默认培训报名审批流（部门负责人，抄送企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'RECRUIT_REQ', '租户默认招聘需求审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'INTEGRATION_REQ', '租户默认系统集成审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'MEETING_BOOK', '租户默认会议预定审批流（部门负责人）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'PROJECT_CREATE', '租户默认项目立项审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'HR_REGISTER', '租户默认人事审批流（部门负责人 → 企业管理员）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
        UNION ALL SELECT 'UNION_APPLY', '租户默认工会审批流（部门负责人）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        UNION ALL SELECT 'PARTY_APPLY', '租户默认党务审批流（部门负责人）',
               '[{"seq": 1, "approver_type": "DEPT_LEADER", "cc": ["ORG_ADMIN"]}]'
        -- 权限类：上一级 → 企业管理员（与 PERMISSION_GRANT 同口径）
        UNION ALL SELECT 'SECURITY_APPLY', '租户默认安全与权限审批流（上一级 → 企业管理员）',
               '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1, "cc": ["ORG_ADMIN"]}, {"seq": 2, "approver_type": "ORG_ADMIN"}]'
       ) s
 WHERE NOT EXISTS (
        SELECT 1 FROM approval_flow_def d
         WHERE d.tenant_id = t.tenant_id
           AND d.institution_id = 0
           AND d.biz_type = s.biz_type
       );
