-- V85 · 表单定义域（docs/52 P1/P4 契约）
-- 四张表：form_template（定义，单一活行）/ form_template_version（版本快照）/
--        form_submission（填写数据真源）/ worker_capability（数字人能力声明）
-- 约定照既有表：utf8mb4、DATETIME(6)、软删 deleted_at + 生成列 alive（唯一键末位带 alive 保证「活行唯一」）、
-- 索引命名 uk_<表> / idx_<表>_<列>。**不用 IF NOT EXISTS**（与 V74/V83 一致，Flyway 顺序执行）。

CREATE TABLE `form_template` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `tenant_id`      BIGINT       NOT NULL COMMENT '租户；0=平台默认模板',
    `institution_id` BIGINT       NULL COMMENT '机构（可空=租户级）',
    `code`           VARCHAR(64)  NOT NULL COMMENT '表单码，数字人与工具用它引用，如 leave_request',
    `name`           VARCHAR(128) NOT NULL COMMENT '中文名',
    `module_code`    VARCHAR(64)  NULL COMMENT '归属功能模块稳定码，如 leave / expense',
    `biz_type`       VARCHAR(64)  NULL COMMENT '提交后进审批的 bizType；空=不走审批',
    `schema_json`    JSON         NOT NULL COMMENT 'JSON Schema Draft 2020-12（渲染/校验/LLM 参数三处同源）',
    `layout_json`    JSON         NULL COMMENT '分组/栅格/顺序；空=按 schema 顺序',
    `submit_policy`  VARCHAR(32)  NOT NULL DEFAULT 'LEDGER' COMMENT 'LEDGER / APPROVAL / RESUME，可组合如 APPROVAL+RESUME',
    `receipt_json`   JSON         NULL COMMENT '声明式回执（标题模板/展示字段/按钮组）',
    `version`        INT          NOT NULL DEFAULT 1 COMMENT '当前生效版本号，每次更新 +1',
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE / DISABLED',
    `created_by`     BIGINT       NULL COMMENT '创建人',
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
    `updated_at`     DATETIME(6)  NULL COMMENT '更新时间',
    `deleted_at`     DATETIME(6)  NULL COMMENT '软删时间',
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL COMMENT '活行标记（唯一键用）',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_form_template` (`tenant_id`, `code`, `alive`),
    KEY `idx_form_template_module` (`tenant_id`, `module_code`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '表单定义（code 在租户内唯一，版本快照见 form_template_version）';

CREATE TABLE `form_template_version` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `template_id` BIGINT      NOT NULL COMMENT 'form_template.id',
    `version`     INT         NOT NULL COMMENT '版本号（从 1 递增，永不覆盖）',
    `schema_json` JSON        NOT NULL COMMENT '该版本 schema 快照',
    `layout_json` JSON        NULL COMMENT '该版本 layout 快照',
    `receipt_json` JSON       NULL COMMENT '该版本回执快照',
    `created_by`  BIGINT      NULL COMMENT '操作人',
    `created_at`  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_form_template_version` (`template_id`, `version`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '表单定义版本快照（改定义必留旧版）';

CREATE TABLE `form_submission` (
    `id`                BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `tenant_id`         BIGINT       NOT NULL COMMENT '租户',
    `template_id`       BIGINT       NOT NULL COMMENT 'form_template.id',
    `template_version`  INT          NOT NULL COMMENT '提交时使用的版本号（口径追溯）',
    `code`              VARCHAR(64)  NOT NULL COMMENT '表单码（冗余，便于按码查询）',
    `biz_type`          VARCHAR(64)  NULL COMMENT '审批 bizType（走审批时）',
    `biz_id`            BIGINT       NULL COMMENT '业务对象 id（审批单/业务表）',
    `applicant_id`      BIGINT       NOT NULL COMMENT '提交人',
    `data_json`         JSON         NOT NULL COMMENT '填写数据（唯一真源）',
    `status`            VARCHAR(16)  NOT NULL COMMENT 'DRAFT/SUBMITTED/APPROVING/APPROVED/REJECTED/DONE/CANCELED',
    `approval_order_id` BIGINT       NULL COMMENT '审批单 id（APPROVAL 分流后回写）',
    `conversation_id`   BIGINT       NULL COMMENT '来源会话（对话内提交）',
    `run_id`            VARCHAR(64)  NULL COMMENT '来源 run（对话内提交）',
    `submitted_at`      DATETIME(6)  NULL COMMENT '提交时间',
    `updated_at`        DATETIME(6)  NULL COMMENT '更新时间',
    `deleted_at`        DATETIME(6)  NULL COMMENT '软删时间',
    `alive`             TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL COMMENT '活行标记',
    PRIMARY KEY (`id`),
    KEY `idx_form_submission_applicant` (`tenant_id`, `applicant_id`, `id`),
    KEY `idx_form_submission_code` (`tenant_id`, `code`, `id`),
    KEY `idx_form_submission_approval` (`approval_order_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '表单填写数据（唯一真源；approval_order.form_data 只存引用+快照）';

CREATE TABLE `worker_capability` (
    `id`                BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `tenant_id`         BIGINT       NOT NULL COMMENT '租户；0=平台模板',
    `worker_id`         BIGINT       NOT NULL COMMENT 'agent_worker.id',
    `task_code`         VARCHAR(64)  NOT NULL COMMENT '任务稳定码，如 leave_request / expense_claim',
    `task_name`         VARCHAR(128) NOT NULL COMMENT '任务中文名',
    `form_code`         VARCHAR(64)  NOT NULL COMMENT '办理时使用的表单码',
    `tool_names_json`   JSON         NULL COMMENT '办这件事需要的工具名数组',
    `approval_biz_type` VARCHAR(64)  NULL COMMENT '提交后走的审批 bizType；空=不审批',
    `sort`              INT          NOT NULL DEFAULT 0 COMMENT '展示排序',
    `enabled`           TINYINT      NOT NULL DEFAULT 1 COMMENT '是否启用',
    `created_at`        DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
    `updated_at`        DATETIME(6)  NULL COMMENT '更新时间',
    `deleted_at`        DATETIME(6)  NULL COMMENT '软删时间',
    `alive`             TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL COMMENT '活行标记',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_worker_capability` (`tenant_id`, `worker_id`, `task_code`, `alive`),
    KEY `idx_worker_capability_form` (`tenant_id`, `form_code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '数字人能力声明：任务→表单→工具→审批';
