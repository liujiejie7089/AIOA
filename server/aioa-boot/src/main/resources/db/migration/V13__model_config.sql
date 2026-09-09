-- V13: 模型配置表（管理端「模型管理」：新增/编辑/启停/默认模型），保存后推送 agent 热加载
CREATE TABLE IF NOT EXISTS `model_config` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `provider_key` VARCHAR(32)  NOT NULL UNIQUE COMMENT '供应商标识（model_ref）',
    `name`         VARCHAR(64)  NOT NULL COMMENT '显示名',
    `base_url`     VARCHAR(255) NOT NULL COMMENT 'OpenAI 兼容根路径',
    `model_name`   VARCHAR(128) NOT NULL COMMENT '请求体 model 名',
    `api_key_env`  VARCHAR(64)  NOT NULL COMMENT 'API Key 环境变量名',
    `enabled`      TINYINT(1)   NOT NULL DEFAULT 1,
    `is_default`   TINYINT(1)   NOT NULL DEFAULT 0,
    `sort`         INT          NOT NULL DEFAULT 0,
    `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`   DATETIME(6)  NULL,
    `created_by`   BIGINT       NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

INSERT INTO `model_config`
    (`provider_key`, `name`, `base_url`, `model_name`, `api_key_env`, `enabled`, `is_default`, `sort`)
VALUES
    ('deepseek',  'DeepSeek',        'https://api.deepseek.com',                          'deepseek-chat',         'DEEPSEEK_API_KEY',  1, 1, 1),
    ('dashscope', '阿里云百炼',       'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus',             'DASHSCOPE_API_KEY', 1, 0, 2),
    ('vllm',      'vLLM 私有部署',    'http://127.0.0.1:8001/v1',                          'Qwen2.5-7B-Instruct',   'VLLM_API_KEY',      0, 0, 3),
    ('ollama',    'Ollama 本地',      'http://127.0.0.1:11434/v1',                         'qwen2.5:7b',            'OLLAMA_API_KEY',    0, 0, 4),
    ('echo',      '回声（演示兜底）',  'internal://echo',                                   'echo',                  'ECHO_API_KEY',      1, 0, 9);
