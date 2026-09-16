-- 权限审批与组织关联改造 · 批次一（数据回填部分）
--
-- 目标：把「谁是部门负责人」的三套口径收敛为一套权威事实源（详见 V41 顶部说明与 docs/23）。
--   口径 A（业务）org_member.job_title 含「负责人」  → 27 人
--   口径 B（引擎）org_department.leader_user_id 非空 → 8 / 39 个部门
--   口径 C（权限）ROLE_DEPT_LEADER 持有者           → 3 人
-- 收敛后：职务（duty_code=DEPT_PRINCIPAL）成为唯一权威源，B 补空对齐 A，C 补齐对齐 A。
--
-- 纪律（与 V26 / V39 播种器一致）：**只补空、不覆盖**。
--   已显式配置的 leader_user_id、已有的角色行一律保留 —— 迁移不能推翻管理员的显式设定。

-- ---------------------------------------------------------------------------
-- ① 口径 A → 职务：把「负责人」这个业务口径落到机器可读的 duty_code
--    27 人的 job_title 形如「算法部负责人 / 办公室负责人 / 销售一部负责人」，
--    统一登记为 DEPT_PRINCIPAL（部门正职）。job_title 保留不动（展示文案）。
-- ---------------------------------------------------------------------------
UPDATE `org_member`
SET `duty_code` = 'DEPT_PRINCIPAL', `updated_at` = NOW(6)
WHERE `deleted_at` IS NULL
  AND `status` = 'ACTIVE'
  AND `duty_code` IS NULL
  AND `job_title` LIKE '%负责人%';

-- ---------------------------------------------------------------------------
-- ② 口径 A → 口径 B：为「有正职但 leader_user_id 为空」的部门补上负责人
--    引擎解析「部门负责人」一级时只读 leader_user_id，这条回填直接决定
--    「一级审批」能否落到真正的部门负责人身上（而不是静默兜底给机构管理员）。
--    取该部门内 id 最小的正职身份，保证同部门多人持正职时结果稳定可预期。
-- ---------------------------------------------------------------------------
UPDATE `org_department` d
    JOIN (
        -- 别名不能叫 lead / rank 等：MySQL 8 里 LEAD 是窗口函数关键字，会直接语法报错
        SELECT m.`department_id`,
               SUBSTRING_INDEX(GROUP_CONCAT(CONCAT(m.`user_id`, '|', m.`name`) ORDER BY m.`id`), ',', 1) AS leadinfo
        FROM `org_member` m
        WHERE m.`deleted_at` IS NULL
          AND m.`status` = 'ACTIVE'
          AND m.`department_id` > 0
          AND m.`duty_code` = 'DEPT_PRINCIPAL'
        GROUP BY m.`department_id`
    ) p ON p.`department_id` = d.`id`
SET d.`leader_user_id` = SUBSTRING_INDEX(p.leadinfo, '|', 1),
    d.`leader_name`    = SUBSTRING_INDEX(p.leadinfo, '|', -1),
    d.`updated_at`     = NOW(6)
WHERE d.`deleted_at` IS NULL
  AND d.`leader_user_id` IS NULL;

-- ---------------------------------------------------------------------------
-- ③ 口径 A → 口径 C：为所有部门正职补授 ROLE_DEPT_LEADER
--    此前只有 3 人持该角色，而部门负责人这一层在权限体系里的全部能力
--    （worker:manage 等）都挂在它上面 —— 3/27 意味着 24 人「有职无权」。
--
--    注：这会改变以「档位统计」为断言的既有套件（如 e2e_admin_personnel_scope
--    的 C3/C4/E7：机构 30 将由「机构管理员 1 + 普通成员 3」变成
--    「机构管理员 1 + 部门负责人 1 + 普通成员 2」）。这是数据口径被修正后的
--    正确结果，套件期望值同批更新 —— **不为转绿放宽断言**。
-- ---------------------------------------------------------------------------
INSERT INTO `sys_user_role` (`tenant_id`, `user_id`, `role_id`, `created_at`)
SELECT DISTINCT 0,
                m.`user_id`,
                (SELECT r.`id` FROM `sys_role` r
                  WHERE r.`role_code` = 'ROLE_DEPT_LEADER' AND r.`deleted_at` IS NULL LIMIT 1),
                NOW(6)
FROM `org_member` m
WHERE m.`deleted_at` IS NULL
  AND m.`status` = 'ACTIVE'
  AND m.`user_id` > 0
  AND m.`duty_code` = 'DEPT_PRINCIPAL'
  AND NOT EXISTS (
    SELECT 1 FROM `sys_user_role` ur
    WHERE ur.`user_id` = m.`user_id`
      AND ur.`role_id` = (SELECT r2.`id` FROM `sys_role` r2
                           WHERE r2.`role_code` = 'ROLE_DEPT_LEADER' AND r2.`deleted_at` IS NULL LIMIT 1)
      AND ur.`deleted_at` IS NULL
  );

-- ---------------------------------------------------------------------------
-- ④ 权限申请流程：整链递推 → 一级审批 + 知会
--
-- 用户诉求：普通用户申请权限，「由部门负责人进行上一级审批即可」。
-- 引擎新增 levels 参数（缺省 = 整链，向后兼容）：
--   levels = 1  → 只取申请人上级链的第一个有效梯级
--     普通成员   → 部门负责人
--     部门负责人 → 机构管理员（企业管理员）
--     机构管理员 → 租户管理员
--     租户管理员 → 平台管理员
--
-- 一级审批的副作用是机构管理员「收不到」成员申请（V39 正是为解决它而把链拉长的）。
-- 按 O2OA 的「待阅」把「要审批」与「要知晓」拆开：cc=[ORG_ADMIN] 生成知会节点，
-- 不阻塞流转、只进「抄送我的」并推通知 → **审批要快，知情要全**。
--
-- 只改「租户级默认流」（institution_id = 0）：机构若单独配了流程，那是管理员的显式选择，不覆盖。
-- ---------------------------------------------------------------------------
UPDATE `approval_flow_def`
SET `steps_json` = '[{"seq": 1, "approver_type": "APPLICANT_SUPERIOR", "levels": 1, "cc": ["ORG_ADMIN"]}]',
    `name`       = '租户默认权限申请审批流（部门负责人一级审批 + 抄送企业管理员）',
    `remark`     = 'V42：改为按申请人层级向上 1 级（levels=1）；机构管理员改以「知会」方式可见（cc=ORG_ADMIN），不阻塞流转',
    `updated_at` = NOW(6)
WHERE `biz_type` = 'PERMISSION_GRANT'
  AND `institution_id` = 0
  AND `status` = 'ACTIVE'
  AND `deleted_at` IS NULL;
