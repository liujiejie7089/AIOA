-- 模型账号（凭证）与共享授权 + 账本计费归属（2026-11-03，docs/71）。
--
-- 要解决的问题：原账本的 user_id 一个字段同时表示「谁在用」和「扣谁的额度」。
-- 允许 A 用 B 注册的账号后，这两个语义必然分离，必须拆开：
--   bearer_user_id  实际使用者（发起对话的人）
--   charge_user_id  平台侧承担者（PERSONAL = 账号持有人；COMPANY = 0 表示公司池）
-- 另加 company_charged 标注「这笔用量是否由公司收费」，供统计与对账使用。
--
-- 为什么 company_charged 允许 NULL：历史账本不知道当时用的是谁的账号，
-- 补 0 等于谎报「个人自付」。NULL = 未标注，统计里单列一档，诚实且可追溯。
--
-- user_id 列保留不动，语义冻结为「账本归属人」（= bearer），
-- 既有查询 / 导出 / 前端账单页不回归。

CREATE TABLE IF NOT EXISTS `model_credential` (
  `id`             BIGINT       NOT NULL AUTO_INCREMENT,
  `tenant_id`      BIGINT       NOT NULL DEFAULT 0 COMMENT '所属租户（个人账号也挂租户，保证统计与越权边界）',
  `owner_type`     VARCHAR(16)  NOT NULL DEFAULT 'PERSONAL' COMMENT 'PERSONAL 自行注册 / COMPANY 公司提供',
  `owner_user_id`  BIGINT       NULL     COMMENT 'PERSONAL 必填：注册人 = 主账号持有人 = 共享时的承担人；COMPANY 为 NULL',
  `provider_key`   VARCHAR(64)  NOT NULL COMMENT '与 agent provider 注册表对齐：deepseek/dashscope/vllm/ollama/minimax',
  `provider_type`  VARCHAR(32)  NOT NULL DEFAULT 'openai_compatible',
  `name`           VARCHAR(64)  NOT NULL COMMENT '展示名，如「我的 DeepSeek」',
  `base_url`       VARCHAR(255) NULL     COMMENT '空 = 回退 provider 注册表',
  `model_name`     VARCHAR(128) NULL     COMMENT '空 = 回退 provider 注册表',
  `api_key_cipher` VARCHAR(512) NOT NULL COMMENT 'SecretCodec 密文（enc: 前缀）；任何接口都不回传明文',
  `key_hint`       VARCHAR(64)  NULL     COMMENT '掩码 sk-****3f9a，仅用于辨认是哪把 Key',
  `share_enabled`  TINYINT      NOT NULL DEFAULT 0 COMMENT '是否允许邀请同事共用',
  `status`         VARCHAR(16)  NOT NULL DEFAULT 'ENABLED',
  `remark`         VARCHAR(255) NULL,
  `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `created_by`     BIGINT       NULL,
  `updated_at`     DATETIME(6)  NULL,
  `updated_by`     BIGINT       NULL,
  `deleted_at`     DATETIME(6)  NULL,
  PRIMARY KEY (`id`),
  -- 同一个人可以为同一个 provider 建多把 Key（「个人」「团队报销」），但名字不能重。
  -- 带上 deleted_at 是为了软删后能重建同名账号（MySQL 里 NULL 不参与唯一冲突，正合此意）。
  UNIQUE KEY `uk_credential_owner_name` (`tenant_id`, `owner_user_id`, `provider_key`, `name`, `deleted_at`),
  KEY `idx_credential_owner` (`tenant_id`, `owner_type`, `owner_user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型账号（凭证）：个人自行注册 / 公司提供';

CREATE TABLE IF NOT EXISTS `credential_share` (
  `id`               BIGINT      NOT NULL AUTO_INCREMENT,
  `tenant_id`        BIGINT      NOT NULL DEFAULT 0,
  `credential_id`    BIGINT      NOT NULL,
  `owner_user_id`    BIGINT      NOT NULL COMMENT '邀请者（冗余 model_credential.owner_user_id，便于按人查）',
  `grantee_user_id`  BIGINT      NOT NULL COMMENT '被邀请的同事',
  `grantee_name`     VARCHAR(64) NULL     COMMENT '冗余姓名，列表免 join',
  `status`           VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT 'PENDING 已邀未接受 / ACTIVE / REVOKED / EXPIRED',
  `invite_code`      VARCHAR(16) NULL     COMMENT '邀请码，便于口头 / IM 传递',
  `quota_tokens`     BIGINT      NOT NULL DEFAULT 0 COMMENT '该子账号的共享上限，0 = 不限',
  `used_tokens`      BIGINT      NOT NULL DEFAULT 0 COMMENT '已用量（加速上限判断；账本仍是唯一事实源）',
  `expires_at`       DATETIME(6) NULL,
  `accepted_at`      DATETIME(6) NULL,
  `revoked_at`       DATETIME(6) NULL,
  `created_at`       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `created_by`       BIGINT      NULL,
  `updated_at`       DATETIME(6) NULL,
  `deleted_at`       DATETIME(6) NULL,
  PRIMARY KEY (`id`),
  -- 撤销后再次邀请复用同一行（改状态、清 revoked_at），否则唯一键会挡住「撤销后再邀请」。
  UNIQUE KEY `uk_share_credential_grantee` (`credential_id`, `grantee_user_id`),
  KEY `idx_share_grantee` (`tenant_id`, `grantee_user_id`, `status`),
  KEY `idx_share_owner` (`tenant_id`, `owner_user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型账号共享授权：主账号 → 子账号';

-- 账本扩列：把「使用者」与「付费人」拆开，并标注是否公司收费。
ALTER TABLE `token_ledger`
  ADD COLUMN `credential_id`     BIGINT      NULL COMMENT '本次用的哪个账号；NULL = 走平台默认通道' AFTER `user_id`,
  ADD COLUMN `bearer_user_id`    BIGINT      NULL COMMENT '实际使用者（发起对话的人）' AFTER `credential_id`,
  ADD COLUMN `charge_user_id`    BIGINT      NULL COMMENT '平台侧承担者：PERSONAL=账号持有人；COMPANY=0 表示公司池' AFTER `bearer_user_id`,
  ADD COLUMN `charge_owner_type` VARCHAR(16) NULL COMMENT 'PERSONAL / COMPANY；NULL = 历史未标注' AFTER `charge_user_id`,
  ADD COLUMN `company_charged`   TINYINT     NULL COMMENT '1 公司收费 / 0 个人自付 / NULL 未标注' AFTER `charge_owner_type`,
  ADD COLUMN `provider_key`      VARCHAR(64) NULL AFTER `company_charged`,
  ADD COLUMN `model_name`        VARCHAR(128) NULL AFTER `provider_key`,
  ADD KEY `idx_ledger_charge` (`tenant_id`, `charge_user_id`, `created_at`),
  ADD KEY `idx_ledger_credential` (`credential_id`, `created_at`);

-- 历史行回填：只填「使用者」这一列（它恒等于 user_id），其余一律留 NULL。
-- 不回填 charge/company_charged —— 这些东西当年压根没记录，编一个值就是造假。
UPDATE `token_ledger` SET `bearer_user_id` = `user_id` WHERE `bearer_user_id` IS NULL;
