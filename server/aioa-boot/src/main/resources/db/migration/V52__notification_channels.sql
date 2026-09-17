-- ===========================================================================
-- V52 · 统一消息中心与多通道触达
-- ===========================================================================
-- 需求：在既有「站内单一通道」(notification 表) 之上，新增可配置的多通道触达
--   （邮件 / 短信 / 移动推送），并与站内信统一「分发 → 投递 → 偏好」模型。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V51，故本文件为 V52。
--
-- 设计要点：
--   · 写通知的两处（aioa-resource NotificationService、aioa-org ApprovalFlowService）
--     仍只落库站内信（不改既有行为），再发布 NotificationRequested 领域事件；
--     aioa-resource 监听事件做「异步分发」，模块间以 aioa-common 事件解耦
--     （沿用 TenantProvisionedEvent 的先例，aioa-org 与 aioa-resource 互不依赖）。
--   · 非站内通道一律走「可配置 HTTP 网关」(java.net.http.HttpClient)，不引入任何
--     新依赖（沙箱无外网，且本项目 Boot 3.3.5 与本地 mail starter 版本不兼容）。
--   · INAPP 恒可用（站内信），其余通道默认未启用；本迁移**不播种任何租户行**，
--     管理员在界面开启并填网关配置后才生效。
--   · notification_delivery 记录「每条通知 × 每个通道」的投递结果，便于排障与重试。
--   · notification_preference 记录用户级别的通道偏好（按 type 精确匹配，再回落默认行）。
--
-- 风格严格沿用 V48 / V51：反引号、列 COMMENT、ENGINE=InnoDB DEFAULT CHARSET=utf8mb4。
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. notification_channel_config · 每租户每通道的启用开关与网关配置
-- ---------------------------------------------------------------------------
-- config_json：网关配置（如 {url, token, from}），原样保存未知键以保证无损往返。
-- 管理员「打开-保存」不能丢配置。INAPP 永不入库（恒可用，无需配置）。
CREATE TABLE IF NOT EXISTS `notification_channel_config` (
    `id`           BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT        NOT NULL COMMENT '所属租户',
    `channel_code` VARCHAR(32)   NOT NULL COMMENT '通道码：INAPP/EMAIL/SMS/PUSH',
    `enabled`      TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '1=已启用该通道',
    `config_json`  TEXT          NULL COMMENT '网关配置 JSON（未知键原样保留）',
    `created_by`   BIGINT        NULL COMMENT '创建人（sys_user.id）',
    `created_at`   DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_by`   BIGINT        NULL COMMENT '最近更新人（sys_user.id）',
    `updated_at`   DATETIME(6)   NULL,
    UNIQUE KEY `uk_channel_config_tenant` (`tenant_id`, `channel_code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '每租户通知通道配置（启用开关 + 网关参数）';

-- ---------------------------------------------------------------------------
-- 2. notification_delivery · 单条通知 × 单通道的投递记录
-- ---------------------------------------------------------------------------
-- status：SENT（投递成功）/ FAILED（异常）/ SKIPPED（无收件地址，已知限制如实记录）。
-- notification_id 可空：机构侧历史通知在拿不到自增 id 时也能登记一条投递（不丢可观测性）。
-- attempts：重试次数 +1；last_error 截断到 512；sent_at 成功时写入。
CREATE TABLE IF NOT EXISTS `notification_delivery` (
    `id`            BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT        NOT NULL COMMENT '所属租户',
    `notification_id` BIGINT      NULL COMMENT '关联站内通知 id（INAPP 落库后回填；机构侧可能为 NULL）',
    `channel_code`  VARCHAR(32)   NOT NULL COMMENT '投递所用通道码',
    `status`        VARCHAR(16)   NOT NULL COMMENT 'SENT/FAILED/SKIPPED',
    `attempts`      INT           NOT NULL DEFAULT 1 COMMENT '投递/重试次数',
    `last_error`    VARCHAR(512)  NULL COMMENT '失败或跳过原因（截断 512）',
    `sent_at`       DATETIME(6)   NULL COMMENT '成功投递时间',
    `created_by`    BIGINT        NULL COMMENT '创建人（sys_user.id）',
    `created_at`    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_by`    BIGINT        NULL COMMENT '最近更新人（sys_user.id）',
    `updated_at`    DATETIME(6)   NULL,
    KEY `idx_delivery_notification` (`notification_id`),
    KEY `idx_delivery_tenant_status` (`tenant_id`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '通知投递记录（每通知每通道一行）';

-- ---------------------------------------------------------------------------
-- 3. notification_preference · 用户级通道偏好
-- ---------------------------------------------------------------------------
-- type 为 NULL 表示「该用户的默认偏好」；精确匹配 type 优先于默认行。
-- channels：逗号分隔的通道码（如 "INAPP,EMAIL"）；NULL 表示沿用租户默认（全部启用通道）。
CREATE TABLE IF NOT EXISTS `notification_preference` (
    `id`           BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT        NOT NULL COMMENT '所属租户',
    `user_id`      BIGINT        NOT NULL COMMENT '所属用户（sys_user.id）',
    `type`         VARCHAR(32)   NULL COMMENT '通知类型；NULL=该用户默认偏好',
    `channels`     VARCHAR(255)  NULL COMMENT '逗号分隔通道码；NULL=沿用租户默认',
    `created_by`   BIGINT        NULL COMMENT '创建人（sys_user.id）',
    `created_at`   DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_by`   BIGINT        NULL COMMENT '最近更新人（sys_user.id）',
    `updated_at`   DATETIME(6)   NULL,
    UNIQUE KEY `uk_preference_tenant_user` (`tenant_id`, `user_id`, `type`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '用户级通知通道偏好';
