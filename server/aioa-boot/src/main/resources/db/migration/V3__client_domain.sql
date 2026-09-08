-- ============================================================================
-- AIOA V3 用户端业务域 DDL（MySQL 8）
--   补齐用户端（小程序/H5）所需但 M1 未建模的 5 类实体：
--     1) ai_expert          专家（首页/专家页卡片 + 推荐问题）
--     2) ai_skill           技能（技能宫格 + 动态表单 schema）
--     3) kb_document        知识库资料（我的知识库文件清单）
--     4) tenant_quota       词元额度（剩余/已用/免费额度）
--     5) token_ledger       词元账本流水（用量账单，与平台账本一致）
--     6) client_activity_log 用户端操作记录
-- 约定同 V1：id / tenant_id / created_at / updated_at / created_by / deleted_at
-- ============================================================================

-- 专家 ---------------------------------------------------------------------
CREATE TABLE `ai_expert` (
                             `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                             `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
                             `expert_key` VARCHAR(64)  NOT NULL,
                             `name`       VARCHAR(128) NOT NULL,
                             `icon`       VARCHAR(32),
                             `summary`    VARCHAR(512),
                             `intro`      TEXT,
                             `tags`       JSON         NULL COMMENT '标签数组，如 ["政策问答","申报指引"]',
                             `recs`       JSON         NULL COMMENT '推荐问题数组',
                             `agent_code` VARCHAR(64)  COMMENT '绑定的 agent_definition.agent_code',
                             `enabled`    TINYINT(1)   NOT NULL DEFAULT 1,
                             `sort`       INT          NOT NULL DEFAULT 0,
                             `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                             `updated_at` DATETIME(6),
                             `created_by` BIGINT,
                             `deleted_at` DATETIME(6),
                             CONSTRAINT `uk_ai_expert` UNIQUE (`tenant_id`, `expert_key`)
);

-- 技能 ---------------------------------------------------------------------
CREATE TABLE `ai_skill` (
                            `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                            `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
                            `skill_name` VARCHAR(128) NOT NULL,
                            `icon`       VARCHAR(32),
                            `est_tokens` INT          NOT NULL DEFAULT 0 COMMENT '预估词元消耗',
                            `fields`     JSON         NULL COMMENT '动态表单 schema 数组',
                            `expert_key` VARCHAR(64)  COMMENT '归属专家（可空=通用技能）',
                            `enabled`    TINYINT(1)   NOT NULL DEFAULT 1,
                            `sort`       INT          NOT NULL DEFAULT 0,
                            `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                            `updated_at` DATETIME(6),
                            `created_by` BIGINT,
                            `deleted_at` DATETIME(6),
                            CONSTRAINT `uk_ai_skill` UNIQUE (`tenant_id`, `skill_name`)
);

-- 知识库资料 ---------------------------------------------------------------
CREATE TABLE `kb_document` (
                               `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                               `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
                               `user_id`    BIGINT       NOT NULL DEFAULT 0,
                               `doc_name`   VARCHAR(512) NOT NULL,
                               `icon`       VARCHAR(32),
                               `state`      VARCHAR(16)  NOT NULL DEFAULT 'WAIT' COMMENT 'OK 已入库 / WAIT 解析中 / FAILED 失败',
                               `size_bytes` BIGINT,
                               `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                               `updated_at` DATETIME(6),
                               `created_by` BIGINT,
                               `deleted_at` DATETIME(6)
);
CREATE INDEX `idx_kb_document_user` ON `kb_document` (`tenant_id`, `user_id`, `created_at`);

-- 词元额度 -----------------------------------------------------------------
CREATE TABLE `tenant_quota` (
                                `id`           BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                `tenant_id`    BIGINT      NOT NULL DEFAULT 0,
                                `user_id`      BIGINT      NOT NULL DEFAULT 0 COMMENT '0=租户共享额度',
                                `quota_tokens` BIGINT      NOT NULL DEFAULT 100000,
                                `used_tokens`  BIGINT      NOT NULL DEFAULT 0,
                                `free_tokens`  BIGINT      NOT NULL DEFAULT 0 COMMENT '赠送额度',
                                `created_at`   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                `updated_at`   DATETIME(6),
                                `created_by`   BIGINT,
                                `deleted_at`   DATETIME(6),
                                CONSTRAINT `uk_tenant_quota` UNIQUE (`tenant_id`, `user_id`)
);

-- 词元账本流水 -------------------------------------------------------------
CREATE TABLE `token_ledger` (
                                `id`                BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                `tenant_id`         BIGINT       NOT NULL DEFAULT 0,
                                `user_id`           BIGINT       NOT NULL DEFAULT 0,
                                `run_id`            VARCHAR(64)  COMMENT '幂等键：一次 run 只记一笔',
                                `biz_type`          VARCHAR(32)  NOT NULL DEFAULT 'CHAT' COMMENT 'CHAT 会话 / SKILL 技能 / KB 入库 / PURCHASE 购买 / REFUND 退回',
                                `biz_title`         VARCHAR(256),
                                `prompt_tokens`     INT          NOT NULL DEFAULT 0,
                                `completion_tokens` INT          NOT NULL DEFAULT 0,
                                `total_tokens`      INT          NOT NULL DEFAULT 0,
                                `balance_after`     BIGINT       NOT NULL DEFAULT 0 COMMENT '记账后剩余额度',
                                `created_at`        DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                `updated_at`        DATETIME(6),
                                `created_by`        BIGINT,
                                `deleted_at`        DATETIME(6),
                                CONSTRAINT `uk_token_ledger_run` UNIQUE (`run_id`)
);
CREATE INDEX `idx_token_ledger_user_time` ON `token_ledger` (`tenant_id`, `user_id`, `created_at`);

-- 用户端操作记录 -----------------------------------------------------------
CREATE TABLE `client_activity_log` (
                                       `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                       `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
                                       `user_id`    BIGINT       NOT NULL DEFAULT 0,
                                       `action`     VARCHAR(256) NOT NULL COMMENT '展示文案，如 09-05 14:20 发起会话（政策咨询专家）之外的动作主体',
                                       `status`     VARCHAR(16)  NOT NULL DEFAULT 'ok' COMMENT 'ok / warn / fail',
                                       `label`      VARCHAR(64)  NOT NULL DEFAULT '成功',
                                       `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                       `updated_at` DATETIME(6),
                                       `created_by` BIGINT,
                                       `deleted_at` DATETIME(6)
);
CREATE INDEX `idx_client_activity_user_time` ON `client_activity_log` (`tenant_id`, `user_id`, `created_at`);
