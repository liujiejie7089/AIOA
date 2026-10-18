-- V14 知识库正文与切片：FR-F1 上传 / FR-F2 入库三态 / FR-F3 检索引用
-- kb_document 增加正文与可见范围；切片表支撑检索命中与原文片段溯源（FR-D5）。

ALTER TABLE `kb_document`
    ADD COLUMN `content`      LONGTEXT     NULL COMMENT '资料正文（上传时携带，用于切片入库与检索）',
    ADD COLUMN `scope`        VARCHAR(16)  NOT NULL DEFAULT 'PERSONAL' COMMENT 'PERSONAL 个人 / TENANT 租户共享',
    ADD COLUMN `chunk_count`  INT          NOT NULL DEFAULT 0 COMMENT '切片数量',
    ADD COLUMN `error_msg`    VARCHAR(512) NULL COMMENT '入库失败原因',
    ADD COLUMN `indexed_at`   DATETIME(6)  NULL COMMENT '入库完成时间';

CREATE TABLE IF NOT EXISTS `kb_chunk` (
                                           `id`          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                           `tenant_id`   BIGINT      NOT NULL DEFAULT 0,
                                           `doc_id`      BIGINT      NOT NULL,
                                           `user_id`     BIGINT      NOT NULL DEFAULT 0,
                                           `chunk_index` INT         NOT NULL DEFAULT 0,
                                           `content`     TEXT        NOT NULL,
                                           `created_at`  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                           `deleted_at`  DATETIME(6)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '知识库切片：检索与引用溯源的最小单元';

CREATE INDEX `idx_kb_chunk_doc` ON `kb_chunk` (`doc_id`, `chunk_index`);
CREATE INDEX `idx_kb_chunk_tenant` ON `kb_chunk` (`tenant_id`, `user_id`);

-- 演示资料：政务办事指引（上传后已入库，供检索与引用溯源演示）
INSERT INTO `kb_document` (`tenant_id`, `user_id`, `doc_name`, `icon`, `state`, `size_bytes`, `scope`,
                           `content`, `chunk_count`, `indexed_at`, `created_at`, `created_by`)
VALUES (0, 1, '政务办事指引.txt', 'doc', 'OK', 512, 'TENANT',
        '住房公积金提取：职工连续足额缴存满 3 个月，可凭本人身份证、银行卡与购房或租房证明材料，在市民之家二楼公积金窗口办理，也可通过小程序线上申请，审核通过后 3 个工作日内到账。\n灵活就业人员参保：持本人身份证与居住证到户籍地或居住地街道便民服务中心办理参保登记，次月起按月缴费，缴费基数可在全市平均工资的 60% 至 300% 之间自主选择。\n企业开办一网通办：通过政务服务网企业开办专区一次性提交名称、设立登记、印章刻制、发票申领与社保开户，全流程 0.5 个工作日办结，营业执照可邮寄送达。',
        3, NOW(6), NOW(6), 1);

INSERT INTO `kb_chunk` (`tenant_id`, `doc_id`, `user_id`, `chunk_index`, `content`)
SELECT 0, d.id, 1, 0,
       '住房公积金提取：职工连续足额缴存满 3 个月，可凭本人身份证、银行卡与购房或租房证明材料，在市民之家二楼公积金窗口办理，也可通过小程序线上申请，审核通过后 3 个工作日内到账。'
FROM `kb_document` d WHERE d.doc_name = '政务办事指引.txt' LIMIT 1;

INSERT INTO `kb_chunk` (`tenant_id`, `doc_id`, `user_id`, `chunk_index`, `content`)
SELECT 0, d.id, 1, 1,
       '灵活就业人员参保：持本人身份证与居住证到户籍地或居住地街道便民服务中心办理参保登记，次月起按月缴费，缴费基数可在全市平均工资的 60% 至 300% 之间自主选择。'
FROM `kb_document` d WHERE d.doc_name = '政务办事指引.txt' LIMIT 1;

INSERT INTO `kb_chunk` (`tenant_id`, `doc_id`, `user_id`, `chunk_index`, `content`)
SELECT 0, d.id, 1, 2,
       '企业开办一网通办：通过政务服务网企业开办专区一次性提交名称、设立登记、印章刻制、发票申领与社保开户，全流程 0.5 个工作日办结，营业执照可邮寄送达。'
FROM `kb_document` d WHERE d.doc_name = '政务办事指引.txt' LIMIT 1;
