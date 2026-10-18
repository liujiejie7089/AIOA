-- 权限审批与组织关联改造 · 批次一（DDL 部分）
--
-- 对标 O2OA（docs/23）的核心结论：我们缺的是 O2OA 的「职务（Duty）」这一层中间层。
-- 现状实测（本机 aioa 库）同一件事有三套互不一致的口径：
--   · org_member.job_title 标「负责人」的 27 人（自由文本，引擎不读）
--   · org_department.leader_user_id 配了的仅 8 / 39 个部门（引擎唯一读的）
--   · 真正持有 ROLE_DEPT_LEADER 的仅 3 人（权限体系读的）
-- 三口径分裂 → 「谁是部门负责人」不可靠 → 审批链与部门管理能力都挂在不牢的地基上。
--
-- 本迁移只做结构准备（加表 / 加列），数据收敛见 V42。全部为**加列**，不改动任何既有列，
-- 老行按默认值继续可用（task_role 默认 APPROVE，与改造前行为逐字等价）。
--
-- 唯一键约定沿用 V24：`alive` 虚拟列 = IF(deleted_at IS NULL, 1, NULL)，
-- 已删除行 alive=NULL 不参与唯一约束（可重建）。实体类**不要**映射 alive。

-- ---------------------------------------------------------------------------
-- ① 职务字典 org_duty —— 复刻 O2OA 的 Duty（租户级，可多人同职务）
--
-- 为什么需要它：O2OA 让流程按「职务 + 所属组织」动态求值处理人，
-- 于是「人员调整只需改职务的人员映射，流程定义无需改动」。
-- 我们此前用自由文本 job_title 顶替这一层，导致流程无法按职务求值。
--
-- duty_rank：同部门多人持同一职务时取第一个（正职 1 优先于副职 2）；
-- can_approve：该职务是否可作为审批人（普通成员 0，不参与审批）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `org_duty` (
    `id`         BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  BIGINT       NOT NULL COMMENT '所属租户（职务字典是租户级，跨机构共享）',
    `code`       VARCHAR(32)  NOT NULL COMMENT '职务码：DEPT_PRINCIPAL / DEPT_DEPUTY / ORG_LEADER / STAFF',
    `name`       VARCHAR(64)  NOT NULL COMMENT '职务名：部门正职 / 部门副职 / 机构负责人 / 普通成员',
    `duty_rank`  INT          NOT NULL DEFAULT 1 COMMENT '同部门排序：越小越优先（正职 1 / 副职 2）',
    `can_approve` TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '是否可作为审批人',
    `scope`      VARCHAR(16)  NOT NULL DEFAULT 'DEPT' COMMENT '职务作用组织层级：ORG / DEPT',
    `status`     VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE',
    `remark`     VARCHAR(255) NULL,
    `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at` DATETIME(6)  NULL,
    `created_by` BIGINT       NULL,
    `deleted_at` DATETIME(6)  NULL,
    `alive`      TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_org_duty_code` (`tenant_id`, `code`, `alive`),
    KEY `idx_org_duty_tenant` (`tenant_id`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '职务字典（对标 O2OA Duty）';

-- 为已存在的每个租户播种基础职务（新租户由入驻播种器补齐，见 DutyProvisioner）。
INSERT IGNORE INTO `org_duty` (`tenant_id`, `code`, `name`, `duty_rank`, `can_approve`, `scope`, `status`, `remark`)
SELECT t.id, d.code, d.name, d.duty_rank, d.can_approve, d.scope, 'ACTIVE', 'V41 基础职务字典'
FROM `sys_tenant` t
         JOIN (
    SELECT 'DEPT_PRINCIPAL' AS code, '部门正职' AS name, 1 AS duty_rank, 1 AS can_approve, 'DEPT' AS scope
    UNION ALL SELECT 'DEPT_DEPUTY', '部门副职', 2, 1, 'DEPT'
    UNION ALL SELECT 'ORG_LEADER', '机构负责人', 0, 1, 'ORG'
    UNION ALL SELECT 'STAFF', '普通成员', 9, 0, 'DEPT'
) d
WHERE t.deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- ② org_member 增「职务 + 身份」两列
--
-- duty_code：机器可读的职务口径（引擎 / 权限据此求值）；
--            job_title **保留不动**，继续作展示文案 —— 两者并存，避免一次性推翻既有数据。
-- is_primary：复刻 O2OA 的 Identity（主身份）。org_member 本身已是「人 × 机构」的关系行，
--             补上该列即可表达兼职 / 借调（一人在多机构各持一个身份）。
-- ---------------------------------------------------------------------------
ALTER TABLE `org_member`
    ADD COLUMN `duty_code`  VARCHAR(32) NULL COMMENT '职务码（对应 org_duty.code）；NULL = 未登记' AFTER `job_title`,
    ADD COLUMN `is_primary` TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '主身份（一人多机构时唯一的那个）' AFTER `duty_code`,
    ADD KEY `idx_org_member_duty` (`department_id`, `duty_code`);

-- ---------------------------------------------------------------------------
-- ③ approval_task 增「知会 / 审批」角色列
--
-- 一级审批的副作用：机构管理员不再出现在链上，成员申请他「收不到」——
-- 这正是 V39 要解决的问题。按 O2OA 的「待阅」做法把「要审批」与「要知晓」拆开：
--   task_role = APPROVE（默认，参与流转、阻塞推进，进「待我处理」）
--   task_role = CC     （抄送/待阅，**不阻塞**推进，只进「抄送我的」并推通知）
-- 默认值 APPROVE 使全部历史行与改造前行为逐字等价。
-- ---------------------------------------------------------------------------
ALTER TABLE `approval_task`
    ADD COLUMN `task_role` VARCHAR(16) NOT NULL DEFAULT 'APPROVE'
        COMMENT 'APPROVE 审批节点 / CC 知会节点（不阻塞流转）' AFTER `approver_name`,
    ADD KEY `idx_approval_task_role` (`approver_id`, `task_role`, `status`);
