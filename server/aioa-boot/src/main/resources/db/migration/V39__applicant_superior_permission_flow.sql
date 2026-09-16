-- 权限申请改为「按申请人层级逐级上报」+ 补齐 tenant 9 的组织与流程配置
--
-- 背景（完整分析见 docs/21）：
--   1) 租户 9 的 PERMISSION_GRANT 流程原为固定两级 [DEPT_LEADER, TENANT_ADMIN]，
--      模板里**没有 ORG_ADMIN 节点** → 企业管理员被结构性跳过。实测：把算法部负责人
--      配置齐全后，审批链变成「部门负责人 → 租户管理员」，机构管理员完全不在链上。
--   2) 算法部 / 工程部的 leader_user_id 为空，导致「部门负责人」一级解析不到，
--      引擎的兜底会把该级改派给机构管理员 —— 看上去「有时能收到」，实为偶然。
--   3) tenant 9 建于 V26 之后，因此没有 V26 播种的三条租户级默认流程（只有
--      PERMISSION_GRANT 一条），请假 / 额度扩容 / 资源开通链路直接不可用。
--
-- 引擎侧已支持 APPLICANT_SUPERIOR（见 ApprovalFlowService.superiorLadder）：
--   一个 step 展开为整条上级链「部门负责人 → 企业管理员 → 租户管理员 → 平台管理员」，
--   并从**申请人自身的上一级**起算，且跳过「审批人 == 申请人」的节点（自审防护）。
--
-- 本迁移只改 tenant 9（用户场景所在租户）。其它租户仍走各自的显式模板，
-- 行为完全不变 —— 避免既有审批链（如 tenant 2 的 部门负责人→企业管理员）被改写。

-- ---------------------------------------------------------------------------
-- ① 权限申请流程：固定两级 → 按申请人层级递推
-- ---------------------------------------------------------------------------
UPDATE approval_flow_def
SET steps_json = '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR"}]',
    name       = '租户默认权限申请审批流（按申请人层级逐级上报）',
    remark     = 'V39：由固定两级改为按申请人组织层级递推（部门负责人→企业管理员→租户管理员），自带自审防护',
    updated_at = NOW(6)
WHERE tenant_id = 9
  AND institution_id = 0
  AND biz_type = 'PERMISSION_GRANT'
  AND deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- ② 补齐研发中心（机构 29）的部门负责人
--    leader_user_id 是审批链解析「部门负责人」一级的**唯一**依据；
--    仅靠 org_member.job_title 写着「算法部负责人」是不生效的。
-- ---------------------------------------------------------------------------
UPDATE org_department
SET leader_user_id = 3144, leader_name = '祁野', updated_at = NOW(6)
WHERE id = 101 AND leader_user_id IS NULL;

UPDATE org_department
SET leader_user_id = 3148, leader_name = '路遥', updated_at = NOW(6)
WHERE id = 102 AND leader_user_id IS NULL;

-- ---------------------------------------------------------------------------
-- ③ 给这两位部门负责人补授 ROLE_DEPT_LEADER
--    此前三人（祁野/路遥/简宁）都只有 ROLE_MEMBER，
--    「部门负责人」这一层在权限体系里等于不存在（无法管理本部门数字员工）。
--    注：市场部的 scxsyb_ldr(3152) 未在此处补授 —— 它会改变机构 30 的人员档位
--    统计（e2e_admin_personnel_scope 的 C3/C4 断言 MEMBER==3），
--    待该套件期望值同步后再单独处理。
-- ---------------------------------------------------------------------------
INSERT INTO sys_user_role (tenant_id, user_id, role_id, created_at)
SELECT 0, u.id, 5, NOW(6)
FROM sys_user u
WHERE u.id IN (3144, 3148)
  AND u.deleted_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM sys_user_role ur
      WHERE ur.user_id = u.id AND ur.role_id = 5 AND ur.deleted_at IS NULL
  );

-- ---------------------------------------------------------------------------
-- ④ 补齐 tenant 9 缺失的租户级默认流程
--    V26 只覆盖了「当时已存在」的租户；tenant 9 是之后由演示数据脚本建的，
--    因此一直没有这三条默认流。用与 V26 相同的写法补齐。
--    真正的根治见 docs/21 §5：新租户**入驻时**就应播种，而不是靠一次性迁移。
-- ---------------------------------------------------------------------------
INSERT IGNORE INTO approval_flow_def
    (tenant_id, institution_id, biz_type, name, steps_json, status, remark)
SELECT 9,
       0,
       d.biz_type,
       d.name,
       CAST(d.steps_json AS JSON),
       'ACTIVE',
       '租户级默认流程：补齐 V26 之后新建的租户（V39）'
FROM (
         SELECT 'LEAVE'                                                                            AS biz_type,
                '租户默认请假审批流（部门负责人 → 企业管理员，≤3 天跳级）'                          AS name,
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
