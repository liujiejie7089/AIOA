-- V61: 管理端「手动添加模型」
--   1) 模型表扩展：大模型类型 / API Key（加密存储，前端只回掩码）/ 温度 / 最大上下文长度
--   2) 新增 MiniMax 预设并设为系统默认模型（默认模型由 DeepSeek 改为 MiniMax）
--
-- 说明：
--   - api_key 存的是密文（AES，密钥取 AIOA_MODEL_KEY_ENC_KEY，回退 AIOA_GITEE_TOKEN_ENC_KEY）；
--     列表接口只返回掩码，明文仅在推送 agent 热加载时解密后走内网传输。
--   - 环境变量（MINIMAX_API_KEY 等）仍是凭据的推荐来源；管理端填写的 Key 优先级更高。
--   - max_context = 0 表示「不限制」（保持历史行为不变），>0 时 agent 按字符预算裁剪多轮历史。
ALTER TABLE `model_config`
    ADD COLUMN `provider_type` VARCHAR(32) NOT NULL DEFAULT 'custom' COMMENT '大模型类型（minimax/deepseek/dashscope/vllm/ollama/custom）' AFTER `provider_key`,
    ADD COLUMN `api_key`       TEXT        NULL     COMMENT 'API Key 密文（AES；为空表示走环境变量）',
    ADD COLUMN `temperature`   DECIMAL(3,2) NOT NULL DEFAULT 0.30 COMMENT '采样温度',
    ADD COLUMN `max_context`   INT         NOT NULL DEFAULT 0    COMMENT '最大上下文长度（token）；0=不限制';

-- 既有内置行补类型（与 provider_key 同名）
UPDATE `model_config`
   SET `provider_type` = `provider_key`
 WHERE `provider_key` IN ('deepseek', 'dashscope', 'vllm', 'ollama', 'echo');

-- MiniMax 预设（INSERT IGNORE：provider_key 唯一键，已存在则跳过）
INSERT IGNORE INTO `model_config`
    (`provider_key`, `name`, `provider_type`, `base_url`, `model_name`, `api_key_env`,
     `enabled`, `is_default`, `sort`, `temperature`, `max_context`)
VALUES
    ('minimax', 'MiniMax', 'minimax', 'https://api.minimax.chat/v1', 'MiniMax-Text-01',
     'MINIMAX_API_KEY', 1, 0, 0, 0.30, 200000);

-- 默认模型切换为 MiniMax（有且仅有一行 is_default=1）
UPDATE `model_config`
   SET `is_default` = (`provider_key` = 'minimax');
