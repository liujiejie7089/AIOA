-- ===========================================================================
-- V43 · 二期主体字段 + 三期待阅已读态（纯加列，历史行按默认值继续可用）
-- ===========================================================================
-- 背景（docs/25 PRD §3.1 E-01 / §3.2 C-03，docs/26 架构 §3.1）：
--   二期「以部门名义发起审批单」需要单据能区分「个人主体 / 部门主体」；
--   三期「待阅已读态」需要知会条目能记录已读时间。
-- 纪律：本迁移**只加列**，不改任何既有列；全部新列均可缺省，
--   使历史行与一期接口调用**逐字等价**（applicant_type 默认 USER、cc_read_at 默认 NULL）。
--
-- ⚠️ 落地前必须先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V42，故本文件为 V43。
-- ⚠️ 本仓 alive 约定：alive TINYINT GENERATED ALWAYS AS (IF(deleted_at IS NULL,1,NULL)) VIRTUAL，
--    仅用于配合唯一键让软删行不占位；本次加列**不需要新建唯一键**，也不新增 alive。
-- ===========================================================================

-- ① approval_order：单据主体（二期 E-01）
--    applicant_type 默认 'USER' → 全部历史行与一期等价；
--    applicant_department_id 仅 applicant_type='DEPARTMENT' 时有值。
ALTER TABLE `approval_order`
    ADD COLUMN `applicant_type` VARCHAR(16) NOT NULL DEFAULT 'USER'
        COMMENT '申请主体：USER 个人 / DEPARTMENT 部门' AFTER `applicant_name`,
    ADD COLUMN `applicant_department_id` BIGINT NULL
        COMMENT '部门申请时的主体部门 id（applicant_type=DEPARTMENT 时非空）' AFTER `applicant_type`,
    ADD KEY `idx_approval_order_applicant` (`applicant_type`, `applicant_department_id`);

-- ② permission_grant：授权单主体（二期 E-08 分账所需）
--    个人「(user_id, code)」与部门「(department_id, code)」是两把幂等键，
--    若不在授权单上留主体标记，两种申请在库中形态完全相同、无法分账。
ALTER TABLE `permission_grant`
    ADD COLUMN `applicant_type` VARCHAR(16) NOT NULL DEFAULT 'USER'
        COMMENT '申请主体：USER 个人 / DEPARTMENT 部门' AFTER `applicant_name`,
    ADD KEY `idx_permission_grant_applicant`
        (`applicant_type`, `department_id`, `permission_code`, `status`);

-- ③ approval_task：待阅已读时间（三期 C-03）
--    NULL = 未读；仅 task_role='CC' 行有意义，APPROVE 行恒 NULL。
--    旧 CC 行迁移后天然 cc_read_at=NULL（未读），与一期前端「未读知会」表现一致。
ALTER TABLE `approval_task`
    ADD COLUMN `cc_read_at` DATETIME(6) NULL
        COMMENT '知会已读时间；NULL=未读。仅 task_role=CC 行有值' AFTER `task_role`,
    ADD KEY `idx_approval_task_cc_read` (`approver_id`, `task_role`, `cc_read_at`);
