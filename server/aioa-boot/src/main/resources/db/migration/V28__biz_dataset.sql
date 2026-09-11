-- V28 企业模拟业务数据集（方案 P3 / C3）
-- 贯通「客户 → 销售订单 → 合同 → 库存/发货 → 收款 → 业绩」完整业务流程，
-- 供数据分析师专家做真实取数与聚合分析。数据由 scripts/seed_biz_dataset.py 生成。

CREATE TABLE IF NOT EXISTS biz_customer (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT       NOT NULL DEFAULT 0,
    name          VARCHAR(128) NOT NULL COMMENT '客户名称',
    industry      VARCHAR(64)  NULL COMMENT '所属行业',
    region        VARCHAR(64)  NULL COMMENT '所在区域',
    level         VARCHAR(16)  NULL COMMENT '客户等级：A/B/C/D',
    credit_status VARCHAR(16)  NULL COMMENT '信用状态：NORMAL/RISK/BLOCKED',
    created_at    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_biz_customer_tenant (tenant_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '客户主数据';

CREATE TABLE IF NOT EXISTS biz_product (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT        NOT NULL DEFAULT 0,
    sku           VARCHAR(64)   NOT NULL COMMENT '产品编码',
    name          VARCHAR(128)  NOT NULL COMMENT '产品名称',
    category      VARCHAR(64)   NULL COMMENT '品类',
    unit_price    DECIMAL(14,2) NULL COMMENT '单价',
    cost          DECIMAL(14,2) NULL COMMENT '成本价',
    created_at    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_biz_product_tenant (tenant_id),
    UNIQUE KEY uk_biz_product_sku (tenant_id, sku)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '产品主数据';

CREATE TABLE IF NOT EXISTS biz_sales_order (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT        NOT NULL DEFAULT 0,
    order_no      VARCHAR(64)   NOT NULL COMMENT '订单号',
    customer_id   BIGINT        NOT NULL COMMENT '客户ID',
    product_id    BIGINT        NOT NULL COMMENT '产品ID',
    quantity      INT           NOT NULL DEFAULT 0 COMMENT '数量',
    amount        DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '金额',
    status        VARCHAR(16)   NOT NULL DEFAULT 'CREATED' COMMENT '状态：CREATED/CONFIRMED/SHIPPED/DONE/CANCELLED',
    ordered_at    DATETIME(6)   NOT NULL COMMENT '下单时间',
    delivered_at  DATETIME(6)   NULL COMMENT '发货时间',
    created_at    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_biz_sales_customer (tenant_id, customer_id),
    KEY idx_biz_sales_product (tenant_id, product_id),
    KEY idx_biz_sales_date (tenant_id, ordered_at),
    UNIQUE KEY uk_biz_sales_no (tenant_id, order_no)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '销售订单';

CREATE TABLE IF NOT EXISTS biz_contract (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT        NOT NULL DEFAULT 0,
    contract_no   VARCHAR(64)   NOT NULL COMMENT '合同编号',
    customer_id   BIGINT        NOT NULL COMMENT '客户ID',
    amount        DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '合同金额',
    status        VARCHAR(16)   NOT NULL DEFAULT 'DRAFT' COMMENT '状态：DRAFT/SIGNED/EXECUTING/CLOSED/TERMINATED',
    signed_at     DATETIME(6)   NULL COMMENT '签订时间',
    expires_at    DATETIME(6)   NULL COMMENT '到期时间',
    created_at    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_biz_contract_customer (tenant_id, customer_id),
    UNIQUE KEY uk_biz_contract_no (tenant_id, contract_no)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '销售合同';

CREATE TABLE IF NOT EXISTS biz_inventory (
    id            BIGINT      NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT      NOT NULL DEFAULT 0,
    product_id    BIGINT      NOT NULL COMMENT '产品ID',
    warehouse     VARCHAR(64) NULL COMMENT '仓库',
    quantity      INT         NOT NULL DEFAULT 0 COMMENT '库存数量',
    safety_stock  INT         NOT NULL DEFAULT 0 COMMENT '安全库存',
    updated_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_biz_inventory_product (tenant_id, product_id),
    UNIQUE KEY uk_biz_inventory (tenant_id, product_id, warehouse)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '库存';

CREATE TABLE IF NOT EXISTS biz_payment (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    tenant_id     BIGINT        NOT NULL DEFAULT 0,
    payment_no    VARCHAR(64)   NOT NULL COMMENT '收款单号',
    order_id      BIGINT        NULL COMMENT '关联订单ID',
    customer_id   BIGINT        NOT NULL COMMENT '客户ID',
    amount        DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '收款金额',
    method        VARCHAR(16)   NULL COMMENT '收款方式：TRANSFER/BILL/CASH',
    paid_at       DATETIME(6)   NOT NULL COMMENT '收款时间',
    created_at    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_biz_payment_customer (tenant_id, customer_id),
    KEY idx_biz_payment_date (tenant_id, paid_at),
    UNIQUE KEY uk_biz_payment_no (tenant_id, payment_no)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '收款记录';
