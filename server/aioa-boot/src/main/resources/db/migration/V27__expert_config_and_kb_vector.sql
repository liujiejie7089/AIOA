-- V27 多租户专家知识库：配置内核 + 向量化 + 入库流水线
-- 1) 专家配置与覆盖（GLOBAL < TENANT < INSTITUTION < DEPT < USER 逐级 merge）
CREATE TABLE IF NOT EXISTS expert_config (
    id           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    tenant_id    BIGINT       NOT NULL DEFAULT 0 COMMENT '租户ID（GLOBAL 层为 0）',
    scope_type   VARCHAR(20)  NOT NULL COMMENT '作用域：GLOBAL/TENANT/INSTITUTION/DEPT/USER',
    scope_id     BIGINT       NOT NULL DEFAULT 0 COMMENT '作用域ID（GLOBAL/TENANT 层为 0）',
    expert_key   VARCHAR(64)  NOT NULL COMMENT '专家标识；* 表示全局默认',
    config_json  JSON         NOT NULL COMMENT '配置JSON（enabled/visibleScope/kbScope/model/temperature/topK/threshold/retrievalMode/tools/sort）',
    created_at   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    created_by   BIGINT       NULL,
    deleted_at   DATETIME(6)  NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_expert_config (tenant_id, scope_type, scope_id, expert_key),
    KEY idx_expert_config_tenant (tenant_id, expert_key)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '专家配置与覆盖规则';

-- 2) 切片向量化：embedding 以 BLOB 存储 float32 数组（小端）
ALTER TABLE kb_chunk
    ADD COLUMN embedding          BLOB        NULL COMMENT '向量（float32 序列）',
    ADD COLUMN embedding_provider VARCHAR(32) NULL COMMENT '向量化provider：local/bge-small-zh',
    ADD COLUMN embedding_dims     INT         NULL COMMENT '向量维度',
    ADD COLUMN embedding_at       DATETIME(6) NULL COMMENT '向量化时间';

-- 3) 文档入库流水线：阶段 / 进度 / 重试 / 切分参数
ALTER TABLE kb_document
    ADD COLUMN stage         VARCHAR(20) NULL COMMENT '流水线阶段：PARSING/CHUNKING/EMBEDDING/OK',
    ADD COLUMN progress      INT         NOT NULL DEFAULT 0 COMMENT '进度 0-100',
    ADD COLUMN retry_count   INT         NOT NULL DEFAULT 0 COMMENT '失败重试次数',
    ADD COLUMN chunk_size    INT         NULL COMMENT '本次入库使用的切分块大小',
    ADD COLUMN chunk_overlap INT         NULL COMMENT '本次入库使用的切分重叠';

-- 4) 专家模板化：分类 / 版本 / 来源模板 / 可见范围 / 知识库范围 / 默认启用
ALTER TABLE ai_expert
    ADD COLUMN category            VARCHAR(32) NULL COMMENT '领域分类：LEGAL/LABOR/CONTRACT/IP/COMPLIANCE/TAX/DATA',
    ADD COLUMN template_version    VARCHAR(16) NULL COMMENT '模板版本',
    ADD COLUMN source_template_id  BIGINT      NULL COMMENT '来源模板ID（租户副本指向全局模板）',
    ADD COLUMN visible_scope       VARCHAR(64) NULL COMMENT '可见范围：ALL/TENANT/INSTITUTION/DEPT/USER',
    ADD COLUMN kb_scope            VARCHAR(255) NULL COMMENT '知识库范围：ALL 或 逗号分隔的文档ID',
    ADD COLUMN default_enabled     TINYINT     NOT NULL DEFAULT 0 COMMENT '新用户默认启用';
