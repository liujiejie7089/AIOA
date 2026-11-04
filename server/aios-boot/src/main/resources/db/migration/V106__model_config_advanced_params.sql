-- V106: 模型配置项扩充（管理端平台模型 + 用户端模型账号，两端字段同名同义）
--
-- 背景（2026-11-04）：原先两端只有 provider/base_url/model/api_key/temperature/max_context，
-- 采样与传输的关键参数（核采样、输出上限、重复抑制、超时、重试、流式）无法配置，
-- 换模型厂家发布的新模型时只能改代码。本迁移把「常用且实用」的一组参数补齐，
-- 两表使用**同名同语义**的列，便于维护与迁移（docs/72 §2 配置项矩阵）。
--
-- 取值与默认值（两端一致，后端强校验见 ModelConfigController / ModelCredentialService）：
--   temperature       0 ~ 2        默认 0.30  采样温度，越低越确定
--   top_p             0 ~ 1        默认 NULL  核采样；NULL = 不下发，沿用供应商默认
--   max_tokens        0 ~ 65536    默认 0     单次回复 token 上限；0 = 不下发（供应商默认）
--   max_context       0 ~ 1048576  默认 0     上下文窗口；>0 时 agent 按预算裁剪多轮历史
--   presence_penalty  -2 ~ 2       默认 0     话题新颖度惩罚（鼓励提及新内容）
--   frequency_penalty -2 ~ 2       默认 0     词频惩罚（抑制复读）
--   timeout_seconds   5 ~ 600      默认 120   单次上游请求超时
--   retry_attempts    1 ~ 5        默认 3     总尝试次数（含首次）；仅对可重试错误生效
--   stream_enabled    0/1          默认 1     是否流式；关掉后走非流式补全（兼容不支持的网关）

ALTER TABLE `model_config`
    ADD COLUMN `top_p`             DECIMAL(4,3) NULL     DEFAULT NULL COMMENT '核采样 top_p；NULL=不下发' AFTER `temperature`,
    ADD COLUMN `max_tokens`        INT          NOT NULL DEFAULT 0    COMMENT '单次回复 token 上限；0=不下发' AFTER `top_p`,
    ADD COLUMN `presence_penalty`  DECIMAL(3,2) NOT NULL DEFAULT 0.00 COMMENT '话题新颖度惩罚 -2~2' AFTER `max_tokens`,
    ADD COLUMN `frequency_penalty` DECIMAL(3,2) NOT NULL DEFAULT 0.00 COMMENT '词频惩罚 -2~2' AFTER `presence_penalty`,
    ADD COLUMN `timeout_seconds`   INT          NOT NULL DEFAULT 120  COMMENT '单次上游请求超时（秒）5~600' AFTER `max_context`,
    ADD COLUMN `retry_attempts`    INT          NOT NULL DEFAULT 3    COMMENT '总尝试次数（含首次）1~5' AFTER `timeout_seconds`,
    ADD COLUMN `stream_enabled`    TINYINT(1)   NOT NULL DEFAULT 1    COMMENT '是否流式输出 1=流式' AFTER `retry_attempts`;

ALTER TABLE `model_credential`
    ADD COLUMN `temperature`       DECIMAL(3,2) NOT NULL DEFAULT 0.30 COMMENT '采样温度 0~2' AFTER `model_name`,
    ADD COLUMN `top_p`             DECIMAL(4,3) NULL     DEFAULT NULL COMMENT '核采样；NULL=不下发' AFTER `temperature`,
    ADD COLUMN `max_tokens`        INT          NOT NULL DEFAULT 0    COMMENT '单次回复上限；0=不下发' AFTER `top_p`,
    ADD COLUMN `max_context`       INT          NOT NULL DEFAULT 0    COMMENT '上下文窗口；0=不限制' AFTER `max_tokens`,
    ADD COLUMN `presence_penalty`  DECIMAL(3,2) NOT NULL DEFAULT 0.00 COMMENT '话题新颖度惩罚 -2~2' AFTER `max_context`,
    ADD COLUMN `frequency_penalty` DECIMAL(3,2) NOT NULL DEFAULT 0.00 COMMENT '词频惩罚 -2~2' AFTER `presence_penalty`,
    ADD COLUMN `timeout_seconds`   INT          NOT NULL DEFAULT 120  COMMENT '单次上游请求超时（秒）' AFTER `frequency_penalty`,
    ADD COLUMN `retry_attempts`    INT          NOT NULL DEFAULT 3    COMMENT '总尝试次数（含首次）' AFTER `timeout_seconds`,
    ADD COLUMN `stream_enabled`    TINYINT(1)   NOT NULL DEFAULT 1    COMMENT '是否流式输出' AFTER `retry_attempts`;

-- 平台模型的配置快照：每次保存 / 启停 / 删除前写一份全量快照，用于「一键回滚到上一版」。
-- 快照存 JSON 全量（不含明文 Key：api_key 存密文原值，回滚时原样写回即可）。
CREATE TABLE IF NOT EXISTS `model_config_snapshot` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT,
    `reason`        VARCHAR(64)  NOT NULL DEFAULT 'SAVE' COMMENT 'SAVE / DELETE / STATUS / DEFAULT / ROLLBACK',
    `total`         INT          NOT NULL DEFAULT 0      COMMENT '快照内模型条数',
    `snapshot_json` LONGTEXT     NOT NULL                COMMENT 'model_config 全量快照（含密文 Key）',
    `operator_id`   BIGINT       NULL                    COMMENT '操作人',
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_mcs_created` (`created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '平台模型配置快照（回滚用）';
