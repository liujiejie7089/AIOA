-- ---------------------------------------------------------------------------
-- V47 · 未开工项数据收口（F3-2 / D-8 / G-1 / G-3）
--
-- 本轮四件事都是「只填空值、不覆盖显式配置」的回填，逐段说明依据与边界：
--
--  1. F3-2 机构级流程定义的默认知会补齐
--     V44 只回填了**租户级**（institution_id=0）流程的默认 cc，机构级（institution_id>0）
--     的 5 条早于 V44 的种子没有 cc —— 于是「机构自己配了请假流」的租户反而丢了知会。
--     本节按业务类型把租户级同一口径的 cc 补进机构级定义。
--
--  2. D-8 新租户假种字典补齐
--     leave_type 原只由 V24 一次性播种，V24 之后入驻的租户（5~9）假种表为空 →
--     LeaveService 按 leave_type_code 查不到假种 → 直接拒单，用户端假种下拉也是空的。
--     本节为「整张假种表为空」的业务租户补标准六条；已有假种的租户一律不动
--     （已配置过的租户，缺哪个是选择而非遗漏）。数值与租户 2 的现行配置逐字对齐。
--     * 本节的运行期对应物是 LeaveTypeProvisioner（入驻事件监听）。
--
--  3. G-3 在职成员职务覆盖率
--     职务字典（V41）落地后，只有 job_title 含「负责人」的 27 人落了 duty_code；
--     其余 94 名在职成员 duty_code 为空 → 四期的 DEPT_DUTY / UNIT_DUTY 在这些部门
--     永远解析不到人。本节按「可判定则落码、不可判定落 STAFF」补齐：
--       · 副职（孙丽华 · 政务大厅管理科副科长）→ DEPT_DEPUTY
--       · 其余 → STAFF
--     **刻意不动** job_title 含「负责人」的行 —— 既有套件 A1/A2 断言
--     「负责人 = 27 人且与 DEPT_PRINCIPAL 零差异」，本节既不加也不减。
--     **刻意不给局长/总经理落 ORG_LEADER**：那会把「机构负责人」这件事从
--     leader_user_id 口径搬进职务口径，影响 ledDepartments 求值（套件 A2-7 有断言），
--     收益（一个演示职务码）远小于风险。与 A2-5「负责人判定只认 DEPT_PRINCIPAL」同一纪律。
--
--  4. G-1 部门负责人补位
--     tenant 3「医政科」有成员（周海涛 · 局长 · 机构管理员）却无负责人 →
--     部门成员的审批链首节点解析不到人。补其正职。
--     其余 3 个有成员无正职的部门（14 综合收费组 / 21 政务大厅管理科 / 31 项目管理部）
--     成员分别是工作人员 / 副科长 / 项目经理，**均非可判定的正职**，按
--     「不硬造负责人」纪律保持为空 —— 管理端 org-structure 页对空负责人已显示
--     「未设置」，是显式状态而非缺数据。
--     另有 3 个零成员部门（13 / 15 / 16）无可指派对象，同样保持为空。
--
--  5. 附带核实、**不改数据**的两项（结论见 docs/28 §2.10）：
--     · D-5/6/7 非残留：tenant 4（教育局）是完整演示租户，其 leave_type / leave_balance /
--       org_department 均被在册成员与请假单引用，属有效数据；tenant 2 的 6 条 X-1
--       「越权建部门」已 correctly 软删（deleted_at 非空 = 审计留痕，不是残留）；
--     · G-2 非缺陷：5 组同名昵称经 seed 源逐条核对，均为「同一人身兼多职」
--       （租户管理员同时是下级机构管理员 / 部门负责人），不是两个人重名。
-- ---------------------------------------------------------------------------


-- === 1. F3-2 机构级流程定义补齐默认知会（与租户级 V44 同口径） =============

UPDATE approval_flow_def
SET steps_json = JSON_SET(steps_json, '$[0].cc', JSON_ARRAY('ORG_ADMIN'))
WHERE deleted_at IS NULL
  AND biz_type = 'LEAVE'
  AND JSON_CONTAINS_PATH(steps_json, 'one', '$[0].cc') = 0;

UPDATE approval_flow_def
SET steps_json = JSON_SET(steps_json, '$[0].cc', JSON_ARRAY('ORG_ADMIN'))
WHERE deleted_at IS NULL
  AND biz_type = 'PERMISSION_GRANT'
  AND JSON_CONTAINS_PATH(steps_json, 'one', '$[0].cc') = 0;

UPDATE approval_flow_def
SET steps_json = JSON_SET(steps_json, '$[0].cc', JSON_ARRAY('TENANT_ADMIN'))
WHERE deleted_at IS NULL
  AND biz_type = 'QUOTA_EXPAND'
  AND JSON_CONTAINS_PATH(steps_json, 'one', '$[0].cc') = 0;

UPDATE approval_flow_def
SET steps_json = JSON_SET(steps_json, '$[0].cc', JSON_ARRAY('TENANT_ADMIN'))
WHERE deleted_at IS NULL
  AND biz_type = 'RESOURCE_OPEN'
  AND JSON_CONTAINS_PATH(steps_json, 'one', '$[0].cc') = 0;


-- === 2. D-8 无假种配置的业务租户补标准六条 ================================
-- 数值口径的来源是租户 2 的现行配置（年假 10 天 / 病假 15 天 / 事假 0 天不占额度…），
-- 与 LeaveTypeProvisioner 的常量逐字一致 —— 改一处必须同步改另一处。

INSERT INTO leave_type
    (tenant_id, code, name, unit, quota_days_per_year, need_proof,
     advance_days, max_consecutive_days, paid, sort, status, created_at, created_by)
SELECT t.tenant_id, s.code, s.name, s.unit, s.quota, s.need_proof,
       s.advance_days, s.max_cons, s.paid, s.sort, 'ENABLED', NOW(6), 0
FROM (
    SELECT DISTINCT tenant_id FROM approval_flow_def WHERE tenant_id <> 0
    UNION
    SELECT DISTINCT tenant_id FROM sys_tenant WHERE tenant_id <> 0 AND deleted_at IS NULL
) t
CROSS JOIN (
              SELECT 'ANNUAL'    AS code, '年假' AS name, 'WORKDAY' AS unit, 10.0 AS quota, 0 AS need_proof, 3 AS advance_days, 15.0 AS max_cons, 1 AS paid, 10 AS sort
    UNION ALL SELECT 'SICK',           '病假',           'WORKDAY',          15.0,           1,               0,                30.0,            1,          20
    UNION ALL SELECT 'CASUAL',         '事假',           'WORKDAY',           0.0,           0,               1,                10.0,            0,          30
    UNION ALL SELECT 'MARRIAGE',       '婚假',           'DAY',               3.0,           1,               7,                 3.0,            1,          40
    UNION ALL SELECT 'MATERNITY',      '产假',           'DAY',              98.0,           1,              30,                98.0,            1,          50
    UNION ALL SELECT 'COMP',           '调休',           'WORKDAY',           5.0,           0,               0,                 5.0,            1,          60
) s
WHERE NOT EXISTS (SELECT 1 FROM leave_type lt WHERE lt.tenant_id = t.tenant_id);


-- === 3. G-3 在职成员职务覆盖率（不触碰「负责人」行） ======================

-- 副职：政务大厅管理科 · 孙丽华（副科长）—— 部门内有且只有一个可判定的副职
UPDATE org_member
SET duty_code = 'DEPT_DEPUTY', updated_at = NOW(6)
WHERE deleted_at IS NULL
  AND status = 'ACTIVE'
  AND (duty_code IS NULL OR duty_code = '')
  AND department_id = 21
  AND name = '孙丽华';

-- 其余不可判定的在职成员落 STAFF（can_approve=0：既可被统计口径覆盖，
-- 又不会被任何「按职务取审批人」的流程误取）
UPDATE org_member
SET duty_code = 'STAFF', updated_at = NOW(6)
WHERE deleted_at IS NULL
  AND status = 'ACTIVE'
  AND (duty_code IS NULL OR duty_code = '')
  AND (job_title IS NULL OR job_title NOT LIKE '%负责人%');


-- === 4. G-1 部门负责人补位 ================================================

-- tenant 3 · 医政科：周海涛（局长 / 机构管理员）为该部门唯一有职权者
UPDATE org_department
SET leader_user_id = 15, leader_name = '周海涛', updated_at = NOW(6)
WHERE id = 40
  AND deleted_at IS NULL
  AND (leader_user_id IS NULL OR leader_user_id = 0);
