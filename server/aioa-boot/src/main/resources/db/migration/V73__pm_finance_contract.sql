-- V73：项目管理模块（PM）批次 4 —— 经费 / 合同 / 收付款 / 里程碑
--
-- 依据：docs/40 §6.3（V73 段）+ docs/43（关键词落地设计）。
-- 本文件落地：pm_expense（项目经费流水，追加式账目）/ pm_contract + pm_contract_payment（合同与收付款）
--   + pm_milestone + pm_milestone_task（里程碑与任务关联）。
-- 批次 2（任务状态机/父子任务）已在 V71 有表，无需迁移；「项目数字人分配 / 项目上下文控制」在 V74。
--
-- ★ 用户口径落地（「经费……不能修改」）：
--   经费流水是**追加式账目（append-only）**——服务层**不提供 update 端点**，
--   写错只能**红冲**（新增一条反向流水，`reversal_of` 指向被冲销行），原行永不改、永不删。
--   `direction`/`category`/`amount`/`occurred_at` 一经写入即事实，修正靠反向行，可完整审计。
--   「分摊」= `alloc_ratio`（分摊比例 %，NULL=不涉及）；「各项目成本」= 按 project_id 聚合；
--   「不固定/增长」= 多行随时间累积，不设单值字段。
--
-- ★ 三条既有约定照抄（见 V71 顶部说明）：tenant_id；软删 deleted_at + alive（唯一键末位带 alive）；
--   生成列 alive 不映射实体；utf8mb4/InnoDB/DATETIME(6)。

-- ---------------------------------------------------------------------------
-- 1. 项目经费流水（追加式账目；方向 IN/OUT，分类覆盖合同款/人工/采购/差旅/其他）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_expense` (
    `id`                  BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`           BIGINT        NOT NULL,
    `project_id`          BIGINT        NOT NULL,
    `direction`           VARCHAR(8)    NOT NULL COMMENT 'IN 收入 / OUT 支出',
    `category`            VARCHAR(32)   NOT NULL
        COMMENT 'CONTRACT 合同款 / LABOR 人工（人员费用）/ PURCHASE 采购 / TRAVEL 差旅 / OTHER 其他',
    `amount`              DECIMAL(18,2) NOT NULL,
    `alloc_ratio`         DECIMAL(5,2)  NULL COMMENT '分摊比例(%)，NULL=全额计入本项目（不分摊）',
    `occurred_at`         DATE          NOT NULL COMMENT '发生日期（费用明细的时间维度）',
    `contract_payment_id` BIGINT        NULL COMMENT '来源：合同收付款确认后自动生成（BR-09）；非合同行为 NULL',
    `voucher_file_id`     BIGINT        NULL COMMENT '凭证 sys_file.id',
    `reversal_of`         BIGINT        NULL COMMENT '红冲：指向被冲销的流水 id（本行是反向行，非 NULL）',
    `remark`              VARCHAR(512)  NULL,
    `created_by`          BIGINT        NULL,
    `created_at`          DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`          DATETIME(6)   NULL,
    `deleted_at`          DATETIME(6)   NULL,
    `alive`               TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    KEY `idx_pm_expense_project` (`tenant_id`, `project_id`, `occurred_at`),
    KEY `idx_pm_expense_payment` (`contract_payment_id`),
    KEY `idx_pm_expense_reversal` (`reversal_of`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目经费收支流水（追加式，修正靠红冲）';

-- ---------------------------------------------------------------------------
-- 2. 项目合同（采购 = OUT 付款合同；收款 = IN 收款合同）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_contract` (
    `id`            BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT        NOT NULL,
    `project_id`    BIGINT        NOT NULL,
    `contract_no`   VARCHAR(64)   NOT NULL,
    `name`          VARCHAR(256)  NOT NULL,
    `direction`     VARCHAR(8)    NOT NULL COMMENT 'IN 收款合同（我方开票）/ OUT 付款合同（采购）',
    `category`      VARCHAR(16)   NOT NULL DEFAULT 'PURCHASE'
        COMMENT 'PURCHASE 采购 / SALES 销售收款 / SERVICE 服务 / OTHER 其他',
    `party_name`    VARCHAR(256)  NOT NULL COMMENT '对方单位',
    `amount`        DECIMAL(18,2) NOT NULL DEFAULT 0,
    `status`        VARCHAR(16)   NOT NULL DEFAULT 'DRAFT'
        COMMENT 'DRAFT 草稿 / PENDING_APPROVAL 审批中 / SIGNED 已签 / EXECUTING 履行中 / CLOSED 已结 / TERMINATED 已终止',
    `approval_order_id` BIGINT    NULL COMMENT '复用审批引擎（biz_type=PM_CONTRACT）',
    `signed_at`     DATE          NULL,
    `start_date`    DATE          NULL,
    `end_date`      DATE          NULL,
    `file_id`       BIGINT        NULL COMMENT '合同扫描件 sys_file.id',
    `created_by`    BIGINT        NULL,
    `created_at`    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6)   NULL,
    `deleted_at`    DATETIME(6)   NULL,
    `alive`         TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_contract_no` (`tenant_id`, `contract_no`, `alive`),
    KEY `idx_pm_contract_project` (`project_id`, `status`),
    KEY `idx_pm_contract_direction` (`tenant_id`, `direction`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目合同（采购/收款）';

-- ---------------------------------------------------------------------------
-- 3. 合同收付款明细（计划 / 实收实付）；确认后在**同事务**生成 pm_expense（BR-09）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_contract_payment` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT        NOT NULL,
    `contract_id`     BIGINT        NOT NULL,
    `seq`             INT           NOT NULL COMMENT '第几期（合同内自增）',
    `plan_amount`     DECIMAL(18,2) NOT NULL COMMENT '计划金额',
    `plan_date`       DATE          NULL COMMENT '计划收付款日',
    `actual_amount`   DECIMAL(18,2) NOT NULL DEFAULT 0,
    `actual_date`     DATE          NULL,
    `status`          VARCHAR(16)   NOT NULL DEFAULT 'PLANNED'
        COMMENT 'PLANNED 计划 / CONFIRMED 已确认 / REVERSED 已红冲',
    `milestone_id`    BIGINT        NULL COMMENT '若为里程碑付款条件，指向 pm_milestone',
    `voucher_file_id` BIGINT        NULL,
    `created_at`      DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`      DATETIME(6)   NULL,
    `deleted_at`      DATETIME(6)   NULL,
    `alive`           TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_contract_payment` (`contract_id`, `seq`, `alive`),
    KEY `idx_pm_payment_plan` (`tenant_id`, `plan_date`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '合同收付款明细（计划/实收）';

-- ---------------------------------------------------------------------------
-- 4. 项目里程碑（可挂合同、可关联任务）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_milestone` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL,
    `project_id`    BIGINT       NOT NULL,
    `contract_id`   BIGINT       NULL COMMENT '关联合同（付款节点型里程碑）',
    `name`          VARCHAR(160) NOT NULL,
    `plan_date`     DATE         NOT NULL,
    `actual_date`   DATE         NULL,
    `status`        VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
        COMMENT 'PENDING 待达成 / ACHIEVED 已达成 / DELAYED 已逾期 / CANCELED 已取消',
    `forced_by`     BIGINT       NULL COMMENT '关联任务未全完成时强制达成者（BR-13）',
    `forced_reason` VARCHAR(255) NULL,
    `created_by`    BIGINT       NULL,
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6)  NULL,
    `deleted_at`    DATETIME(6)  NULL,
    `alive`         TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    KEY `idx_pm_milestone_project` (`tenant_id`, `project_id`, `plan_date`),
    KEY `idx_pm_milestone_contract` (`contract_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目里程碑（可挂合同、可关联任务）';

-- ---------------------------------------------------------------------------
-- 5. 里程碑 ↔ 任务 关联（M:N）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_milestone_task` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT      NOT NULL,
    `milestone_id` BIGINT      NOT NULL,
    `task_id`      BIGINT      NOT NULL,
    `created_at`   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `deleted_at`   DATETIME(6) NULL,
    `alive`        TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_milestone_task` (`milestone_id`, `task_id`, `alive`),
    KEY `idx_pm_milestone_task_task` (`task_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '里程碑 ↔ 任务 关联（M:N）';

-- ---------------------------------------------------------------------------
-- 6. 权限码 —— 本文件**有意不播种** pm:budget:manage / pm:contract:manage。
--    纪律（见 V71 顶部）：只为**已实现能力**播种权限码，否则它会出现在「可申请权限」
--    清单里、用户申请到却无任何端点认它（能力事实上不可用）。
--    批次 4 的经费/合同端点落地时，随其实现在**当次**迁移里补这两个码。
-- ---------------------------------------------------------------------------
