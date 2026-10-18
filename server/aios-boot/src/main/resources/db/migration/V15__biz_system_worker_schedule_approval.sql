-- V15 业务系统接入 + 数字员工定时任务 + 审批发起人
-- 1) biz_system：管理端注册/维护业务系统（接口地址、认证方式、密钥、接口文档）
-- 2) agent_worker 增加调度字段；agent_worker_run 记录每次真实执行
-- 3) approval_order 增加发起人姓名（管理端审批中心展示）

CREATE TABLE IF NOT EXISTS `biz_system` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`   BIGINT       NOT NULL DEFAULT 0,
    `system_code` VARCHAR(64)  NOT NULL COMMENT '系统编码（租户内唯一）',
    `name`        VARCHAR(128) NOT NULL COMMENT '系统名称',
    `description` VARCHAR(512) NULL COMMENT '系统说明',
    `base_url`    VARCHAR(512) NULL COMMENT '接口根地址',
    `auth_type`   VARCHAR(16)  NOT NULL DEFAULT 'NONE' COMMENT 'NONE / API_KEY / BASIC / BEARER',
    `auth_config` TEXT         NULL COMMENT '认证配置 JSON（密钥等，接口返回时掩码）',
    `doc_url`     VARCHAR(512) NULL COMMENT '接口文档链接',
    `doc_content` MEDIUMTEXT   NULL COMMENT '接口文档内容（Markdown/文本）',
    `status`      VARCHAR(16)  NOT NULL DEFAULT 'ENABLED' COMMENT 'ENABLED / DISABLED',
    `created_by`  BIGINT       NULL,
    `created_at`  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`  DATETIME(6)  NULL,
    `deleted_at`  DATETIME(6)  NULL,
    UNIQUE KEY `uk_biz_system_code` (`tenant_id`, `system_code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '已接入的业务系统注册与配置';

ALTER TABLE `agent_worker`
    ADD COLUMN `schedule_time` VARCHAR(5) NULL COMMENT '每日执行时刻 HH:mm（如 08:00），空=不定时',
    ADD COLUMN `task_prompt`   TEXT      NULL COMMENT '到点执行的任务内容（交给模型真实执行）',
    ADD COLUMN `last_run_at`   DATETIME(6) NULL COMMENT '最近一次定时执行时间';

CREATE TABLE IF NOT EXISTS `agent_worker_run` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT       NOT NULL DEFAULT 0,
    `worker_id`    BIGINT       NOT NULL,
    `worker_name`  VARCHAR(128) NULL,
    `trigger_type` VARCHAR(16)  NOT NULL DEFAULT 'SCHEDULE' COMMENT 'SCHEDULE 定时 / MANUAL 手动',
    `status`       VARCHAR(16)  NOT NULL DEFAULT 'SUCCESS' COMMENT 'SUCCESS / FAILED',
    `output`       TEXT         NULL COMMENT '执行产出（模型真实生成）',
    `error_msg`    VARCHAR(512) NULL,
    `model`        VARCHAR(128) NULL COMMENT '执行所用模型',
    `duration_ms`  BIGINT       NOT NULL DEFAULT 0,
    `started_at`   DATETIME(6)  NOT NULL,
    `finished_at`  DATETIME(6)  NULL,
    `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `deleted_at`   DATETIME(6)  NULL,
    KEY `idx_worker_run_worker` (`worker_id`, `started_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '数字员工执行记录（真实运行留痕）';

ALTER TABLE `approval_order`
    ADD COLUMN `applicant_name` VARCHAR(64) NULL COMMENT '发起人姓名（提交时快照）';

-- 存量数据回填发起人姓名
UPDATE `approval_order` o
    LEFT JOIN `sys_user` u ON o.`user_id` = u.`id`
SET o.`applicant_name` = COALESCE(u.`nickname`, u.`username`, CONCAT('用户#', o.`user_id`))
WHERE o.`applicant_name` IS NULL AND o.`deleted_at` IS NULL;
