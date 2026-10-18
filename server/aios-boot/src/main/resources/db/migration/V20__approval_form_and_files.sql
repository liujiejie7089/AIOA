-- ============================================================================
-- AIOA V20 请假审批闭环：审批单结构化表单 + 附件 + 通用文件上传
--   approval_order：追加 form_data（结构化表单 JSON）、attachment（附件 JSON 数组）
--   sys_file：通用文件上传落库（请假证明等附件存储，预留可替换为对象存储）
-- ============================================================================

ALTER TABLE `approval_order`
    ADD COLUMN `form_data` TEXT NULL COMMENT '结构化表单(JSON)，如请假{leaveType,start,end,reason}',
    ADD COLUMN `attachment` TEXT NULL COMMENT '附件(JSON数组：{name,url})';

CREATE TABLE `sys_file` (
    `id`             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL DEFAULT 0,
    `user_id`        BIGINT       NOT NULL DEFAULT 0,
    `original_name`  VARCHAR(255) COMMENT '原始文件名',
    `stored_name`    VARCHAR(255) COMMENT '存储文件名(UUID)',
    `url`            VARCHAR(512) COMMENT '访问路径 /api/v1/files/{id}',
    `size`           BIGINT       COMMENT '字节数',
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6),
    `deleted_at`     DATETIME(6),
    CONSTRAINT `uk_sys_file` UNIQUE (`tenant_id`, `id`)
);

CREATE INDEX `idx_sys_file_tenant` ON `sys_file` (`tenant_id`, `created_at`);
