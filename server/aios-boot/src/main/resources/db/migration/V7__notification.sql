-- ============================================================================
-- AIOA V7 站内通知（审批事件驱动）
--   notification：submit → 通知租户全部管理员「有待审单」；
--                 decide → 通知发起人「通过/驳回 + 审批意见」。
--   read_at 为空 = 未读；前端「待办」卡展示未读并支持单条/全部标记已读。
-- ============================================================================

CREATE TABLE `notification` (
                                `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
                                `user_id`    BIGINT       NOT NULL DEFAULT 0 COMMENT '接收人',
                                `type`       VARCHAR(32)  NOT NULL DEFAULT 'APPROVAL' COMMENT 'APPROVAL / SYSTEM',
                                `title`      VARCHAR(256),
                                `content`    VARCHAR(1024),
                                `ref_id`     BIGINT       COMMENT '关联审批单 id（可空）',
                                `read_at`    DATETIME(6)  COMMENT '为空=未读',
                                `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                `updated_at` DATETIME(6),
                                `created_by` BIGINT,
                                `deleted_at` DATETIME(6),
                                CONSTRAINT `uk_notification` UNIQUE (`tenant_id`, `id`)
);

CREATE INDEX `idx_notification_user_read` ON `notification` (`tenant_id`, `user_id`, `read_at`, `created_at`);
