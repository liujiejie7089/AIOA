-- V18 系统参数配置（管理端 5.2「系统参数配置」）
-- 面向租户管理员的运行期可调参数，覆盖会话、额度、知识库、安全合规四组；
-- 参数来源于《AIOA 客户端小程序 P0 需求规格说明书》《AIOA 技术方案》中明确写出的默认值/阈值。

CREATE TABLE IF NOT EXISTS `sys_config` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT       NOT NULL DEFAULT 0 COMMENT '租户 ID，0=平台默认',
    `config_key`   VARCHAR(64)  NOT NULL COMMENT '参数键（租户内唯一）',
    `config_value` VARCHAR(512) NOT NULL COMMENT '参数值（统一以字符串存储）',
    `value_type`   VARCHAR(16)  NOT NULL DEFAULT 'STRING' COMMENT 'INT / DECIMAL / BOOL / STRING / JSON',
    `group_code`   VARCHAR(32)  NOT NULL DEFAULT 'COMMON' COMMENT 'CONVERSATION / QUOTA / KNOWLEDGE / SECURITY / COMMON',
    `config_name`  VARCHAR(128) NOT NULL COMMENT '参数名称（中文）',
    `description`  VARCHAR(512) NULL COMMENT '参数说明',
    `unit`         VARCHAR(16)  NULL COMMENT '单位（轮/秒/%/MB/年 等）',
    `default_value` VARCHAR(512) NOT NULL COMMENT '出厂默认值（用于恢复默认）',
    `min_value`    DECIMAL(20,4) NULL COMMENT '数值型最小值（校验用）',
    `max_value`    DECIMAL(20,4) NULL COMMENT '数值型最大值（校验用）',
    `editable`     TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否允许管理端修改',
    `sort_no`      INT          NOT NULL DEFAULT 0,
    `created_by`   BIGINT       NULL,
    `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`   DATETIME(6)  NULL,
    `deleted_at`   DATETIME(6)  NULL,
    UNIQUE KEY `uk_sys_config_key` (`tenant_id`, `config_key`),
    KEY `idx_sys_config_group` (`tenant_id`, `group_code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '系统参数配置（管理端运行期可调参数）';

-- 租户 1（示例租户）种子参数；其余租户首次读取时由后端自动克隆平台默认（tenant_id=0）
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`, `description`, `unit`, `default_value`, `min_value`, `max_value`, `editable`, `sort_no`)
VALUES
    -- 会话与模型
    (1, 'chat.context_rounds',      '10',    'INT',     'CONVERSATION', '单会话上下文轮数上限', '同一会话保留的上下文轮数，超出后自动摘要压缩（P0 FR-D2）', '轮',  '10',    1,     100,  1, 10),
    (1, 'chat.first_token_ms',      '2000',  'INT',     'CONVERSATION', '首字延迟目标',         '流式输出端到端首字延迟门禁，超出记为体验不达标（P0 FR-D1）', '毫秒', '2000',  500,   10000, 1, 20),
    (1, 'chat.max_steps',           '8',     'INT',     'CONVERSATION', '智能体最大推理步数',   '单轮任务主循环最大步数，超出强制收束（架构设计 5）',          '步',  '8',     1,     32,   1, 30),
    (1, 'chat.default_model_route', 'auto',  'STRING',  'CONVERSATION', '默认模型路由',         'auto=平台智能路由；亦可指定已上架模型的 providerKey（P0 FR-D4）', '',    'auto',  NULL,  NULL, 1, 40),
    -- 额度与计费
    (1, 'quota.low_balance_percent', '20',   'DECIMAL', 'QUOTA',        '额度低余额提醒阈值',   '剩余额度占比低于该值时卡片变色提醒（P0 FR-G1）',              '%',   '20',    0,     100,  1, 10),
    (1, 'quota.daily_free_tokens',   '20000','INT',     'QUOTA',        '每人每日免费词元',     '普通用户每日发放的免费词元数，次日零点重置（P0 FR-B2）',      '词元','20000', 0,     10000000, 1, 20),
    (1, 'quota.alert_enabled',       'true', 'BOOL',    'QUOTA',        '额度提醒开关',         '关闭后用户端不再展示低余额变色与提示',                       '',    'true',  NULL,  NULL, 1, 30),
    -- 知识库
    (1, 'kb.max_file_mb',            '50',   'INT',     'KNOWLEDGE',    '单文件上传上限',       '单个知识库/资料文件大小上限（P0 FR-F1）',                    'MB',  '50',    1,     2048, 1, 10),
    (1, 'kb.chunk_size',             '800',  'INT',     'KNOWLEDGE',    '切片长度',             'RAG 入库时单切片的目标字符数',                               '字符','800',   100,   4000, 1, 20),
    (1, 'kb.top_k',                  '5',    'INT',     'KNOWLEDGE',    '检索召回条数',         '问答检索时返回的切片条数（引用溯源条目上限）',               '条',  '5',     1,     20,   1, 30),
    (1, 'kb.citation_required',      'true', 'BOOL',    'KNOWLEDGE',    '强制引用溯源',         '开启后引用知识库的回答必须附来源条目（P0 4.1 来源可追溯）',    '',    'true',  NULL,  NULL, 1, 40),
    -- 安全合规
    (1, 'security.content_double_check', 'true', 'BOOL', 'SECURITY',    '内容双审开关',         '输入与输出均过内容安全审核，命中敏感内容中止应答（P0 FR-H3）','',    'true',  NULL,  NULL, 1, 10),
    (1, 'security.audit_retention_years', '3',  'INT',  'SECURITY',    '留痕保存年限',         '台账与操作留痕最少保存年限，满足深度合成管理规定（P0 4.2）',  '年',  '3',     1,     30,   1, 20),
    (1, 'security.realname_required',    'true', 'BOOL', 'SECURITY',    '强制实名认证',         '开启后未实名用户不可发起会话（P0 FR-A 实名认证）',            '',    'true',  NULL,  NULL, 1, 30);
