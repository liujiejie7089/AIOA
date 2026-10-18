-- V9: 商业闭环最小版——词元包商品 + 支付订单（FR-G4：下单 → 支付 → 额度实时到账 → 订单可查）
-- 微信支付为二期接入，本期以 MOCK 通道演示全链路（PaymentChannel 适配接口预留）。

CREATE TABLE IF NOT EXISTS quota_package (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_code  VARCHAR(50)  NOT NULL COMMENT '商品编码',
    package_name  VARCHAR(100) NOT NULL COMMENT '商品名称',
    tokens        BIGINT       NOT NULL COMMENT '词元数',
    price_cents   INT          NOT NULL COMMENT '价格（分）',
    status        VARCHAR(20)  NOT NULL DEFAULT 'ONSALE' COMMENT 'ONSALE/OFFSALE',
    sort          INT          NOT NULL DEFAULT 0,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NULL,
    created_by    BIGINT       NULL,
    UNIQUE KEY uk_package_code (package_code)
) ENGINE = InnoDB COMMENT '词元包商品';

CREATE TABLE IF NOT EXISTS payment_order (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_no     VARCHAR(64)  NOT NULL COMMENT '订单号（幂等键）',
    tenant_id    BIGINT       NOT NULL DEFAULT 0,
    user_id      BIGINT       NOT NULL COMMENT '下单用户',
    package_id   BIGINT       NOT NULL,
    package_name VARCHAR(100) NOT NULL,
    tokens       BIGINT       NOT NULL COMMENT '应付词元数',
    amount_cents INT          NOT NULL COMMENT '订单金额（分）',
    status       VARCHAR(20)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/PAID/CANCELLED',
    pay_channel  VARCHAR(20)  NULL COMMENT 'MOCK/WECHAT',
    pay_time     DATETIME     NULL,
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME     NULL,
    created_by   BIGINT       NULL,
    UNIQUE KEY uk_order_no (order_no)
) ENGINE = InnoDB COMMENT '支付订单';

INSERT INTO quota_package (package_code, package_name, tokens, price_cents, status, sort, created_by) VALUES
('TRIAL_100K',  '体验词元包 · 10万词元',  100000,  1000,  'ONSALE', 1, 0),
('TEAM_600K',   '团队词元包 · 60万词元',  600000,  5000,  'ONSALE', 2, 0),
('ENT_1300K',   '企业词元包 · 130万词元', 1300000, 10000, 'ONSALE', 3, 0);
