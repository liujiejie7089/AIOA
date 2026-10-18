-- V34 租户管理员创建内容需上一级审核
--
-- 需求（多角色全流程 · 权限下发链路）：租户管理员创建的内容（数字员工 / 专家）不能自行生效，
-- 必须经上一级（平台管理员）审核通过后才能对成员可见、可运行。
--
-- 设计取舍：
--   · 用独立的 audit_status 列，而不是复用 agent_worker.status —— 后者是「运行态」
--     （运行中 / 待配置 / 已停用），与「审核态」正交，混用会让调度器把待审内容当故障处理。
--   · 存量数据一律置为 APPROVED：本开关是新增约束，不应让历史数据瞬间变成「未过审」。
--   · 只对「租户管理员」生效（平台管理员自建不受限），见 ContentReviewService#needsReview。
--
-- 另：开关本身放在 sys_config（approval.tenant.content），便于按运营阶段灰度或临时放开，
-- 不必改代码重新发版。

ALTER TABLE `agent_worker`
    ADD COLUMN `audit_status` VARCHAR(16)  NOT NULL DEFAULT 'APPROVED' COMMENT '审核态：PENDING 待审 / APPROVED 已通过 / REJECTED 已驳回' AFTER `status`,
    ADD COLUMN `audit_note`   VARCHAR(255) NULL COMMENT '审核意见（驳回时必填，回显给创建者）' AFTER `audit_status`,
    ADD COLUMN `reviewed_by`  BIGINT       NULL COMMENT '审核人 user_id' AFTER `audit_note`,
    ADD COLUMN `reviewed_at`  DATETIME(6)  NULL COMMENT '审核时间' AFTER `reviewed_by`;

ALTER TABLE `ai_expert`
    ADD COLUMN `audit_status` VARCHAR(16)  NOT NULL DEFAULT 'APPROVED' COMMENT '审核态：PENDING 待审 / APPROVED 已通过 / REJECTED 已驳回' AFTER `visible_scope`,
    ADD COLUMN `audit_note`   VARCHAR(255) NULL COMMENT '审核意见' AFTER `audit_status`,
    ADD COLUMN `reviewed_by`  BIGINT       NULL COMMENT '审核人 user_id' AFTER `audit_note`,
    ADD COLUMN `reviewed_at`  DATETIME(6)  NULL COMMENT '审核时间' AFTER `reviewed_by`;

-- 存量一律视为已通过
UPDATE `agent_worker` SET `audit_status` = 'APPROVED' WHERE `audit_status` IS NULL OR `audit_status` = '';
UPDATE `ai_expert`    SET `audit_status` = 'APPROVED' WHERE `audit_status` IS NULL OR `audit_status` = '';

-- 平台开关：默认开启「租户管理员创建内容需上一级审核」
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`,
     `description`, `unit`, `default_value`, `editable`, `sort_no`)
VALUES
    (0, 'approval.tenant.content', 'true', 'BOOL', 'AUDIT', '租户内容需上级审核',
     '开启后，租户管理员创建的数字员工 / 专家进入待审核，需平台管理员通过后生效；关闭则创建即生效。',
     '', 'true', 1, 50)
ON DUPLICATE KEY UPDATE `updated_at` = NOW(6);
