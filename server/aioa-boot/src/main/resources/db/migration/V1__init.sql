-- ============================================================================
-- AIOA M1 初始化 DDL（MySQL 8）
-- 约定：所有业务表均含 id / tenant_id / created_at / updated_at / created_by / deleted_at
--       日志类表（sys_login_log、tool_invocation_log）只保留少量审计列
-- 注意：MySQL 保留字 status / action / before / after 已用反引号转义；
--       jsonb → JSON；timestamptz → DATETIME(6)；identity → AUTO_INCREMENT
-- ============================================================================

-- 租户 ---------------------------------------------------------------------
CREATE TABLE `sys_tenant` (
    `id`          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`   BIGINT       NOT NULL DEFAULT 0,
    `code`        VARCHAR(64)  NOT NULL UNIQUE,
    `name`        VARCHAR(128) NOT NULL,
    `status`      VARCHAR(16)  NOT NULL DEFAULT 'ENABLED',
    `created_at`  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  DATETIME(6),
    `created_by`  BIGINT,
    `deleted_at`  DATETIME(6)
);

-- 用户 / 角色 / 权限 --------------------------------------------------------
CREATE TABLE `sys_user` (
    `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0,
    `username`      VARCHAR(64)  NOT NULL UNIQUE,
    `password_hash` VARCHAR(128),
    `nickname`      VARCHAR(64),
    `avatar`        VARCHAR(512),
    `mobile`        VARCHAR(32),
    `email`         VARCHAR(128),
    `status`        VARCHAR(16)  NOT NULL DEFAULT 'ENABLED',
    `last_login_at` DATETIME(6),
    `auth_type`     VARCHAR(16)  NOT NULL DEFAULT 'local',
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME(6),
    `created_by`    BIGINT,
    `deleted_at`    DATETIME(6)
);

CREATE TABLE `sys_role` (
    `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  BIGINT      NOT NULL DEFAULT 0,
    `role_code`  VARCHAR(64) NOT NULL UNIQUE,
    `name`       VARCHAR(128) NOT NULL,
    `type`       VARCHAR(32),
    `data_scope` VARCHAR(32),
    `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME(6),
    `created_by` BIGINT,
    `deleted_at` DATETIME(6)
);

CREATE TABLE `sys_permission` (
    `id`        BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` BIGINT      NOT NULL DEFAULT 0,
    `perm_code` VARCHAR(128) NOT NULL UNIQUE,
    `name`      VARCHAR(128) NOT NULL,
    `type`      VARCHAR(32),
    `parent_id` BIGINT,
    `sort`      INT         NOT NULL DEFAULT 0,
    `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME(6),
    `created_by` BIGINT,
    `deleted_at` DATETIME(6)
);

CREATE TABLE `sys_user_role` (
    `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  BIGINT      NOT NULL DEFAULT 0,
    `user_id`    BIGINT      NOT NULL,
    `role_id`    BIGINT      NOT NULL,
    `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME(6),
    `created_by` BIGINT,
    `deleted_at` DATETIME(6),
    CONSTRAINT `uk_sys_user_role` UNIQUE (`user_id`, `role_id`)
);

CREATE TABLE `sys_role_permission` (
    `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  BIGINT      NOT NULL DEFAULT 0,
    `role_id`    BIGINT      NOT NULL,
    `perm_id`    BIGINT      NOT NULL,
    `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME(6),
    `created_by` BIGINT,
    `deleted_at` DATETIME(6),
    CONSTRAINT `uk_sys_role_permission` UNIQUE (`role_id`, `perm_id`)
);

CREATE TABLE `sys_login_log` (
    `id`          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`   BIGINT      NOT NULL DEFAULT 0,
    `user_id`     BIGINT,
    `ip`          VARCHAR(64),
    `ua`          VARCHAR(512),
    `result`      VARCHAR(16),
    `fail_reason` VARCHAR(256),
    `login_at`    DATETIME(6),
    `created_at`  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 应用注册表 ---------------------------------------------------------------
CREATE TABLE `app_registry` (
    `id`             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL DEFAULT 0,
    `app_code`       VARCHAR(64)  NOT NULL UNIQUE,
    `name`           VARCHAR(128) NOT NULL,
    `entry_url`      VARCHAR(512),
    `route_prefix`   VARCHAR(128),
    `host_type`      VARCHAR(16),
    `icon`           VARCHAR(128),
    `permission_code` VARCHAR(128),
    `enabled`        TINYINT(1)   NOT NULL DEFAULT 1,
    `props`          JSON         NULL,
    `sort`           INT          NOT NULL DEFAULT 0,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`     DATETIME(6),
    `created_by`     BIGINT,
    `deleted_at`     DATETIME(6)
);

-- 会话 / 消息 / 运行 -------------------------------------------------------
CREATE TABLE `chat_conversation` (
    `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0,
    `user_id`       BIGINT       NOT NULL,
    `title`         VARCHAR(256),
    `agent_code`    VARCHAR(64),
    `app_code`      VARCHAR(64),
    `model_ref`     VARCHAR(64),
    `summary`       TEXT,
    `context_turns` INT          NOT NULL DEFAULT 10,
    `msg_count`     BIGINT       NOT NULL DEFAULT 0,
    `status`        VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE',
    `last_msg_at`   DATETIME(6),
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME(6),
    `created_by`    BIGINT,
    `deleted_at`    DATETIME(6)
);

CREATE TABLE `chat_message` (
    `id`               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`        BIGINT      NOT NULL DEFAULT 0,
    `conversation_id`  BIGINT      NOT NULL,
    `run_id`           VARCHAR(64),
    `role`             VARCHAR(16) NOT NULL,
    `content`          TEXT,
    `content_type`     VARCHAR(16) NOT NULL DEFAULT 'text',
    `tokens`           INT,
    `context_snapshot` JSON        NULL,
    `citations`        JSON        NULL,
    `tool_calls`       JSON        NULL,
    `status`           VARCHAR(16),
    `seq`              BIGINT      NOT NULL DEFAULT 0,
    `created_at`       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`       DATETIME(6),
    `created_by`       BIGINT,
    `deleted_at`       DATETIME(6)
);
CREATE INDEX `idx_chat_message_conv_seq` ON `chat_message` (`conversation_id`, `seq`);

CREATE TABLE `agent_run` (
    `id`              BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT      NOT NULL DEFAULT 0,
    `run_id`          VARCHAR(64) NOT NULL UNIQUE,
    `conversation_id` BIGINT,
    `user_id`         BIGINT,
    `status`          VARCHAR(16) NOT NULL,
    `plan`            JSON        NULL,
    `current_step`    INT,
    `error`           TEXT,
    `tokens_in`       INT         NOT NULL DEFAULT 0,
    `tokens_out`      INT         NOT NULL DEFAULT 0,
    `started_at`      DATETIME(6),
    `ended_at`        DATETIME(6),
    `duration_ms`     BIGINT,
    `created_at`      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME(6),
    `created_by`      BIGINT,
    `deleted_at`      DATETIME(6)
);
CREATE INDEX `idx_agent_run_conversation` ON `agent_run` (`conversation_id`);

CREATE TABLE `agent_run_step` (
    `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT      NOT NULL DEFAULT 0,
    `run_id`        VARCHAR(64) NOT NULL,
    `step_seq`      INT,
    `step_type`     VARCHAR(32),
    `agent_code`    VARCHAR(64),
    `tool_code`     VARCHAR(64),
    `input_masked`  JSON        NULL,
    `output_digest` VARCHAR(128),
    `status`        VARCHAR(16),
    `duration_ms`   BIGINT,
    `created_at`    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME(6),
    `created_by`    BIGINT,
    `deleted_at`    DATETIME(6)
);

-- Agent / 工具 / 模型 ------------------------------------------------------
CREATE TABLE `agent_definition` (
    `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT      NOT NULL DEFAULT 0,
    `agent_code`    VARCHAR(64) NOT NULL UNIQUE,
    `name`          VARCHAR(128) NOT NULL,
    `type`          VARCHAR(16),
    `domain`        VARCHAR(64),
    `system_prompt` TEXT,
    `model_ref`     VARCHAR(64),
    `context_turns` INT         NOT NULL DEFAULT 10,
    `max_steps`     INT         NOT NULL DEFAULT 8,
    `enabled`       TINYINT(1)  NOT NULL DEFAULT 1,
    `description`   TEXT,
    `created_at`    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME(6),
    `created_by`    BIGINT,
    `deleted_at`    DATETIME(6)
);

CREATE TABLE `tool_system` (
    `id`              BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT       NOT NULL DEFAULT 0,
    `system_code`     VARCHAR(64)  NOT NULL UNIQUE,
    `name`            VARCHAR(128) NOT NULL,
    `base_url`        VARCHAR(512),
    `health_url`      VARCHAR(512),
    `auth_type`       VARCHAR(32),
    `auth_ref`        VARCHAR(256),
    `timeout_ms`      INT,
    `circuit_breaker` JSON        NULL,
    `status`          VARCHAR(16),
    `created_at`      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME(6),
    `created_by`      BIGINT,
    `deleted_at`      DATETIME(6)
);

CREATE TABLE `tool_definition` (
    `id`                   BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`            BIGINT       NOT NULL DEFAULT 0,
    `tool_code`            VARCHAR(128) NOT NULL,
    `version`              VARCHAR(32)  NOT NULL DEFAULT '1.0.0',
    `name`                 VARCHAR(128),
    `description`          TEXT,
    `domain`               VARCHAR(64),
    `system_code`          VARCHAR(64),
    `endpoint`             VARCHAR(512),
    `http_method`          VARCHAR(16),
    `input_schema`         JSON        NULL,
    `output_schema`        JSON        NULL,
    `risk_level`           VARCHAR(16),
    `requires_approval`    TINYINT(1)   NOT NULL DEFAULT 0,
    `idempotency_required` TINYINT(1)   NOT NULL DEFAULT 0,
    `timeout_ms`           INT,
    `retry_policy`         JSON        NULL,
    `rate_limit`           VARCHAR(64),
    `auth_type`            VARCHAR(32),
    `auth_ref`             VARCHAR(256),
    `param_mapping`        JSON        NULL,
    `response_jmespath`    VARCHAR(512),
    `max_bytes`            BIGINT,
    `status`                VARCHAR(16),
    `owner`                VARCHAR(64),
    `created_at`           DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`           DATETIME(6),
    `created_by`           BIGINT,
    `deleted_at`           DATETIME(6),
    CONSTRAINT `uk_tool_definition` UNIQUE (`tool_code`, `version`)
);

CREATE TABLE `tool_permission` (
    `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
    `tool_code`  VARCHAR(128) NOT NULL,
    `role_code`  VARCHAR(64)  NOT NULL,
    `effect`     VARCHAR(8)   NOT NULL DEFAULT 'ALLOW',
    `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME(6),
    `created_by` BIGINT,
    `deleted_at` DATETIME(6),
    CONSTRAINT `uk_tool_permission` UNIQUE (`tool_code`, `role_code`)
);

CREATE TABLE `tool_invocation_log` (
    `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0,
    `trace_id`      VARCHAR(64),
    `run_id`        VARCHAR(64),
    `step_id`       BIGINT,
    `tool_code`     VARCHAR(128),
    `version`       VARCHAR(32),
    `user_id`       BIGINT,
    `args_masked`   JSON        NULL,
    `result_digest` VARCHAR(128),
    `result_size`   BIGINT,
    `http_status`   INT,
    `duration_ms`   BIGINT,
    `approval_id`   VARCHAR(64),
    `error_code`    VARCHAR(64),
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX `idx_tool_invocation_log_code_time` ON `tool_invocation_log` (`tool_code`, `created_at`);

-- 审计 / 模型供应商 --------------------------------------------------------
CREATE TABLE `audit_log` (
    `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT      NOT NULL DEFAULT 0,
    `user_id`       BIGINT,
    `action`        VARCHAR(64),
    `resource_type` VARCHAR(64),
    `resource_id`   VARCHAR(64),
    `detail`        JSON        NULL,
    `before`        JSON        NULL,
    `after`         JSON        NULL,
    `ip`            VARCHAR(64),
    `ua`            VARCHAR(512),
    `result`        VARCHAR(16),
    `trace_id`      VARCHAR(64),
    `prev_hash`     VARCHAR(128),
    `hash`          VARCHAR(128),
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME(6),
    `created_by`    BIGINT,
    `deleted_at`    DATETIME(6)
);
CREATE INDEX `idx_audit_log_created_at` ON `audit_log` (`created_at`);

CREATE TABLE `model_provider` (
    `id`          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`   BIGINT       NOT NULL DEFAULT 0,
    `name`        VARCHAR(64)  NOT NULL UNIQUE,
    `type`        VARCHAR(32),
    `base_url`    VARCHAR(512),
    `models`      JSON         NULL,
    `api_key_env` VARCHAR(128),
    `enabled`     TINYINT(1)   NOT NULL DEFAULT 1,
    `created_at`  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  DATETIME(6),
    `created_by`  BIGINT,
    `deleted_at`  DATETIME(6)
);
