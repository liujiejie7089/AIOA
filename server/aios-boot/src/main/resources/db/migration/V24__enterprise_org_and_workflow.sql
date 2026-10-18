-- ============================================================================
-- V24 企业入驻全流程：多租户组织域 + 四级配额链路 + 费用分摊 + 资源授权
--      + 两级审计 + 多级审批流 + 请假流程（假种 / 余额 / 校验 / 扣减）
--
-- 依据：《AIOA 管理端需求规格说明书 V2.0》FR-A ~ FR-K（32 条，M 级 25 条）
-- 数据库：MySQL 8（一期）；隔离策略 = tenant_id 行级隔离 + institution_id 机构硬边界
--
-- 主体链：租户 → 机构 → 部门/团队 → 个人
--   · 租户（tenant）：计费与资源分配主体，对应 sys_tenant
--   · 机构（institution）：租户内具有法人资格的组织实体
--   · 部门（department）：机构内行政条线，树形，层级 ≤ 5
--   · 个人（member）：经 org_member 关联 sys_user，最小身份主体
--
-- 唯一键约定：沿用 V17 方案 —— `alive` 虚拟列 = IF(deleted_at IS NULL, 1, NULL)，
--   未删除行 alive=1 参与唯一约束（防重），已删除行 alive=NULL 不参与（可重注册）。
--   注意：`alive` 为生成列，实体类**不要**映射它。
--
-- 演示数据说明：本迁移为「企业入驻」演示建立两个租户
--   · tenant_id = 2 → 某某市某某区大数据管理局（入驻主链路演示租户）
--   · tenant_id = 3 → 某某市某某区卫生健康局（跨租户隔离验证）
--   tenant_id = 0（既有默认租户 / admin / zhangsan）**不做任何修改**，保证既有 E2E 零回归。
--   新增演示账号统一口令 **User@123**（复用 V6 zhangsan 的 BCrypt 哈希，强度 10）。
-- ============================================================================


-- ============================================================================
-- 一、组织域（FR-B 机构管理 / FR-G 组织机构管理）
-- ============================================================================

CREATE TABLE `org_institution` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `name`           VARCHAR(128) NOT NULL COMMENT '机构名称',
    `code`           VARCHAR(64)  NOT NULL COMMENT '机构编码（租户内唯一）',
    `org_type`       VARCHAR(32)  NOT NULL DEFAULT 'ENTERPRISE'
        COMMENT 'GOVERNMENT 政务机关 / ENTERPRISE 企业 / ASSOCIATION 社会团体',
    `credit_code`    VARCHAR(64)  NULL COMMENT '统一社会信用代码',
    `legal_person`   VARCHAR(64)  NULL COMMENT '法定代表人 / 单位负责人',
    `contact_mobile` VARCHAR(32)  NULL,
    `contact_email`  VARCHAR(128) NULL,
    `admin_user_id`  BIGINT       NULL COMMENT '企业管理员（FR-B2，唯一）',
    `admin_name`     VARCHAR(64)  NULL,
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE'
        COMMENT 'ACTIVE 正常 / SUSPENDED 停用 / CLOSED 已注销',
    `established_at` DATE         NULL COMMENT '成立日期',
    `onboard_step`   INT          NOT NULL DEFAULT 0 COMMENT '入驻进度 0~8，见入驻编排',
    `remark`         VARCHAR(512) NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `created_by`     BIGINT       NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_org_institution_code` (`tenant_id`, `code`, `alive`),
    KEY `idx_org_institution_tenant` (`tenant_id`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '机构（企业）';

CREATE TABLE `org_department` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL,
    `parent_id`      BIGINT       NOT NULL DEFAULT 0 COMMENT '父部门，0=根',
    `name`           VARCHAR(128) NOT NULL,
    `code`           VARCHAR(64)  NULL,
    `level`          INT          NOT NULL DEFAULT 1 COMMENT '层级 1~5（FR-G1 约束）',
    `path`           VARCHAR(255) NOT NULL DEFAULT '' COMMENT '物化路径 /1/3/7/，便于取子树',
    `leader_user_id` BIGINT       NULL COMMENT '部门负责人（审批 DEPT_LEADER 节点解析依据）',
    `leader_name`    VARCHAR(64)  NULL,
    `sort`           INT          NOT NULL DEFAULT 0,
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE',
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `created_by`     BIGINT       NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_org_department_code` (`tenant_id`, `institution_id`, `code`, `alive`),
    KEY `idx_org_department_parent` (`institution_id`, `parent_id`),
    KEY `idx_org_department_path` (`institution_id`, `path`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '部门（机构内行政条线，树形≤5层）';

CREATE TABLE `org_member` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL,
    `department_id`  BIGINT       NOT NULL DEFAULT 0,
    `user_id`        BIGINT       NOT NULL,
    `name`           VARCHAR(64)  NOT NULL,
    `mobile`         VARCHAR(32)  NULL,
    `email`          VARCHAR(128) NULL,
    `employee_no`    VARCHAR(64)  NULL COMMENT '工号',
    `job_title`      VARCHAR(64)  NULL COMMENT '职务',
    `is_org_admin`   TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否机构企业管理员',
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE / DISABLED 停用',
    `joined_at`      DATE         NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `created_by`     BIGINT       NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_org_member_user` (`tenant_id`, `institution_id`, `user_id`, `alive`),
    UNIQUE KEY `uk_org_member_no` (`tenant_id`, `institution_id`, `employee_no`, `alive`),
    KEY `idx_org_member_dept` (`institution_id`, `department_id`),
    KEY `idx_org_member_user` (`user_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '机构员工成员关系';


-- ============================================================================
-- 二、资源池与四级配额（FR-C 资源池与配额分配 / FR-H1 机构内二次分配）
-- ============================================================================

CREATE TABLE `tenant_resource_pool` (
    `id`              BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT      NOT NULL,
    `period`          VARCHAR(16) NOT NULL COMMENT '周期 YYYY-MM',
    `token_total`     BIGINT      NOT NULL DEFAULT 0 COMMENT '词元套餐总量',
    `token_used`      BIGINT      NOT NULL DEFAULT 0,
    `expert_seats`    INT         NOT NULL DEFAULT 0 COMMENT '专家订阅席位数',
    `expert_used`     INT         NOT NULL DEFAULT 0,
    `skill_seats`     INT         NOT NULL DEFAULT 0 COMMENT '技能订阅席位数',
    `skill_used`      INT         NOT NULL DEFAULT 0,
    `warn_threshold`  INT         NOT NULL DEFAULT 20 COMMENT '预警阈值百分比（FR-C3 默认20）',
    `unit_price`      DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '词元单价（分摊出账用）',
    `expire_at`       DATE        NULL,
    `status`          VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    `created_at`      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`      DATETIME(6) NULL,
    `created_by`      BIGINT      NULL,
    `deleted_at`      DATETIME(6) NULL,
    `alive`           TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_tenant_resource_pool` (`tenant_id`, `period`, `alive`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '租户资源池（FR-C1）';

CREATE TABLE `org_quota` (
    `id`              BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT      NOT NULL,
    `institution_id`  BIGINT      NOT NULL,
    `period`          VARCHAR(16) NOT NULL COMMENT '周期 YYYY-MM',
    `quota_tokens`    BIGINT      NOT NULL DEFAULT 0 COMMENT '机构配额上限（FR-C2）',
    `used_tokens`     BIGINT      NOT NULL DEFAULT 0,
    `free_tokens`     BIGINT      NOT NULL DEFAULT 0 COMMENT '赠送/加油包',
    `warn_threshold`  INT         NOT NULL DEFAULT 20,
    `frozen`          TINYINT(1)  NOT NULL DEFAULT 0
        COMMENT '配额耗尽自动冻结（FR-C3）：1=冻结，消耗性操作直接拒绝',
    `effective_from`  DATE        NULL,
    `effective_to`    DATE        NULL,
    `status`          VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    `created_at`      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`      DATETIME(6) NULL,
    `created_by`      BIGINT      NULL,
    `deleted_at`      DATETIME(6) NULL,
    `alive`           TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_org_quota` (`tenant_id`, `institution_id`, `period`, `alive`),
    KEY `idx_org_quota_inst` (`institution_id`, `period`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '机构配额（租户→机构分配）';

CREATE TABLE `dept_quota` (
    `id`             BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT      NOT NULL,
    `institution_id` BIGINT      NOT NULL,
    `department_id`  BIGINT      NOT NULL,
    `period`         VARCHAR(16) NOT NULL,
    `quota_tokens`   BIGINT      NOT NULL DEFAULT 0 COMMENT '部门额度（FR-H1 二次分配）',
    `used_tokens`    BIGINT      NOT NULL DEFAULT 0,
    `warn_threshold` INT         NOT NULL DEFAULT 20,
    `created_at`     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6) NULL,
    `created_by`     BIGINT      NULL,
    `deleted_at`     DATETIME(6) NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_dept_quota` (`tenant_id`, `department_id`, `period`, `alive`),
    KEY `idx_dept_quota_inst` (`institution_id`, `period`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '部门额度（机构→部门二次分配）';

CREATE TABLE `quota_alloc_log` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL DEFAULT 0,
    `scope_type`     VARCHAR(16)  NOT NULL COMMENT 'TENANT / ORG / DEPT / USER',
    `scope_id`       BIGINT       NOT NULL COMMENT '对应层级主体 id',
    `period`         VARCHAR(16)  NULL,
    `action`         VARCHAR(16)  NOT NULL
        COMMENT 'ALLOCATE 分配 / ADJUST 调整 / FREEZE 冻结 / UNFREEZE 解冻 / CONSUME 消耗',
    `before_tokens`  BIGINT       NOT NULL DEFAULT 0,
    `delta`          BIGINT       NOT NULL DEFAULT 0,
    `after_tokens`   BIGINT       NOT NULL DEFAULT 0,
    `reason`         VARCHAR(512) NULL,
    `operator_id`    BIGINT       NULL,
    `operator_name`  VARCHAR(64)  NULL,
    `operator_role`  VARCHAR(64)  NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '配额分配流水（贯穿四级链路，审计依据）';


-- ============================================================================
-- 三、费用分摊（FR-D）
-- ============================================================================

CREATE TABLE `cost_alloc_rule` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `name`           VARCHAR(128) NOT NULL,
    `rule_type`      VARCHAR(16)  NOT NULL
        COMMENT 'FIXED_RATIO 按机构固定比例 / USAGE 按实际用量实摊 / COST_CENTER 按成本中心归集',
    `period_type`    VARCHAR(16)  NOT NULL DEFAULT 'MONTH' COMMENT 'MONTH / QUARTER',
    `config_json`    JSON         NULL COMMENT '比例表 / 成本中心映射',
    `version`        INT          NOT NULL DEFAULT 1 COMMENT '规则版本号，变更次期生效并自增',
    `effective_from` DATE         NULL,
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE' COMMENT 'DRAFT / ACTIVE / RETIRED',
    `remark`         VARCHAR(512) NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `created_by`     BIGINT       NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_cost_alloc_rule` (`tenant_id`, `name`, `version`, `alive`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '费用分摊规则（FR-D1）';

CREATE TABLE `cost_alloc_bill` (
    `id`             BIGINT         NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT         NOT NULL,
    `rule_id`        BIGINT         NOT NULL,
    `rule_version`   INT            NOT NULL COMMENT '出账所用规则版本（账单即凭证）',
    `institution_id` BIGINT         NOT NULL,
    `period`         VARCHAR(16)    NOT NULL,
    `usage_tokens`   BIGINT         NOT NULL DEFAULT 0,
    `unit_price`     DECIMAL(18, 6) NOT NULL DEFAULT 0,
    `amount`         DECIMAL(18, 2) NOT NULL DEFAULT 0,
    `serial_no`      VARCHAR(64)    NOT NULL COMMENT '序时流水号，对齐财务对账与政务审计',
    `ledger_checked` TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '与平台账本逐笔核对通过标记',
    `generated_at`   DATETIME(6)    NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `created_by`     BIGINT         NULL,
    `deleted_at`     DATETIME(6)    NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_cost_alloc_bill` (`tenant_id`, `institution_id`, `period`, `rule_version`, `alive`),
    UNIQUE KEY `uk_cost_alloc_bill_serial` (`serial_no`, `alive`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '分摊账单（FR-D2）';


-- ============================================================================
-- 四、资源授权（FR-E）
-- ============================================================================

CREATE TABLE `resource_grant` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL,
    `res_type`       VARCHAR(16)  NOT NULL COMMENT 'EXPERT / SKILL / MODEL / KB',
    `res_id`         BIGINT       NOT NULL COMMENT '对应资源主键',
    `res_key`        VARCHAR(64)  NULL COMMENT '资源业务键（expert_key 等）',
    `res_name`       VARCHAR(128) NULL,
    `extra`          JSON         NULL COMMENT '差异化参数，如计费倍率 billing_ratio',
    `enabled`        TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '未授权/停用则成员端不可见（FR-E1）',
    `granted_by`     BIGINT       NULL,
    `granted_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_resource_grant` (`tenant_id`, `institution_id`, `res_type`, `res_id`, `alive`),
    KEY `idx_resource_grant_inst` (`institution_id`, `res_type`, `enabled`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '资源按机构授权（FR-E1/E2）';


-- ============================================================================
-- 五、两级审计（FR-F2 租户级 / FR-K2 机构级 / FR-A3 敏感操作留痕）
--
-- 注意：`audit_log` 已在 V1__init.sql 建立，且自带 prev_hash/hash 防篡改哈希链
--       （对应规格书「全量留痕、不可篡改」）。此处**不新建表**，只补齐两级审计
--       所需的机构维度与操作人展示字段，避免破坏既有哈希链写入逻辑。
-- ============================================================================

ALTER TABLE `audit_log`
    ADD COLUMN `institution_id` BIGINT      NOT NULL DEFAULT 0
        COMMENT '机构维度：0=租户级操作（FR-F2 / FR-K2 两级审计的隔离键）',
    ADD COLUMN `scope`          VARCHAR(16) NOT NULL DEFAULT 'TENANT'
        COMMENT 'TENANT 租户级 / ORG 机构级',
    ADD COLUMN `actor_name`     VARCHAR(64)  NULL COMMENT '操作人展示名（快照，避免关联查询）',
    ADD COLUMN `actor_role`     VARCHAR(64)  NULL COMMENT '操作时角色（ROLE_TENANT_ADMIN / ROLE_ORG_ADMIN …）',
    ADD COLUMN `summary`        VARCHAR(512) NULL COMMENT '一句话操作摘要，便于审计页直接展示';

ALTER TABLE `audit_log`
    ADD INDEX `idx_audit_log_tenant` (`tenant_id`, `created_at`),
    ADD INDEX `idx_audit_log_org` (`institution_id`, `created_at`);


-- ============================================================================
-- 五之二、机构知识库可见范围（FR-I1：机构知识库 + 按部门配置可见范围）
--   复用既有 kb_document(scope: PERSONAL/TENANT)，补齐机构维度与部门可见范围，
--   新增取值 ORG（机构库）/ DEPT（部门可见）。
-- ============================================================================

ALTER TABLE `kb_document`
    ADD COLUMN `institution_id` BIGINT NOT NULL DEFAULT 0
        COMMENT '所属机构：0=个人/租户共享库',
    ADD COLUMN `department_id`  BIGINT NOT NULL DEFAULT 0
        COMMENT '限定可见部门：0=机构内全员可见',
    ADD INDEX `idx_kb_document_org` (`institution_id`, `department_id`);


-- ============================================================================
-- 六、多级审批流（审批升级）
-- ============================================================================

CREATE TABLE `approval_flow_def` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL DEFAULT 0 COMMENT '0=租户通用模板',
    `biz_type`       VARCHAR(32)  NOT NULL
        COMMENT 'LEAVE 请假 / QUOTA_EXPAND 额度扩容 / RESOURCE_OPEN 资源开通',
    `name`           VARCHAR(128) NOT NULL,
    `steps_json`     JSON         NOT NULL
        COMMENT '[{seq,approver_type,approver_id,threshold_days}] 审批节点；approver_type=DEPT_LEADER/ORG_ADMIN/TENANT_ADMIN/SPECIFIC；threshold_days 表示「天数 ≤ 该值时跳过本节点」',
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE / DISABLED',
    `remark`         VARCHAR(512) NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `created_by`     BIGINT       NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_approval_flow_def` (`tenant_id`, `institution_id`, `biz_type`, `alive`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '审批流定义（按业务类型配置多级节点）';

CREATE TABLE `approval_task` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL,
    `order_id`       BIGINT       NOT NULL COMMENT '→ approval_order.id（单据主表）',
    `seq`            INT          NOT NULL COMMENT '节点序号，从 1 递增',
    `approver_type`  VARCHAR(32)  NOT NULL COMMENT 'DEPT_LEADER / ORG_ADMIN / TENANT_ADMIN / SPECIFIC',
    `approver_id`    BIGINT       NULL COMMENT '解析出的审批人 user_id',
    `approver_name`  VARCHAR(64)  NULL,
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
        COMMENT 'PENDING 待审 / APPROVED 通过 / REJECTED 驳回 / SKIPPED 跳过（阈值跳级或流程终止）',
    `note`           VARCHAR(512) NULL COMMENT '审批意见',
    `skip_reason`    VARCHAR(255) NULL,
    `decided_at`     DATETIME(6)  NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `deleted_at`     DATETIME(6)  NULL,
    KEY `idx_approval_task_order` (`order_id`, `seq`),
    KEY `idx_approval_task_approver` (`approver_id`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '审批任务（多级流转节点）';


-- ============================================================================
-- 七、请假流程（假种 / 余额 / 请假单）
-- ============================================================================
CREATE TABLE `leave_type` (
    `id`                   BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`            BIGINT       NOT NULL,
    `code`                 VARCHAR(32)  NOT NULL
        COMMENT 'ANNUAL 年假 / SICK 病假 / CASUAL 事假 / MARRIAGE 婚假 / MATERNITY 产假 / COMP 调休',
    `name`                 VARCHAR(64)  NOT NULL,
    `unit`                 VARCHAR(16)  NOT NULL DEFAULT 'DAY' COMMENT 'DAY 自然日 / WORKDAY 工作日',
    `quota_days_per_year`  DECIMAL(6,1) NOT NULL DEFAULT 0 COMMENT '年度额度（0=不限额）',
    `need_proof`           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否必须上传证明材料',
    `advance_days`         INT          NOT NULL DEFAULT 0 COMMENT '需提前申请的天数',
    `max_consecutive_days` DECIMAL(6,1) NOT NULL DEFAULT 0 COMMENT '单次最长连续天数（0=不限）',
    `paid`                 TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否带薪',
    `sort`                 INT          NOT NULL DEFAULT 0,
    `status`               VARCHAR(16)  NOT NULL DEFAULT 'ENABLED',
    `created_at`           DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`           DATETIME(6)  NULL,
    `created_by`           BIGINT       NULL,
    `deleted_at`           DATETIME(6)  NULL,
    `alive`                TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_leave_type` (`tenant_id`, `code`, `alive`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '假种配置';

CREATE TABLE `leave_balance` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT       NOT NULL,
    `institution_id`  BIGINT       NOT NULL,
    `user_id`         BIGINT       NOT NULL,
    `leave_type_code` VARCHAR(32)  NOT NULL,
    `year`            INT          NOT NULL,
    `total_days`      DECIMAL(6,1) NOT NULL DEFAULT 0,
    `used_days`       DECIMAL(6,1) NOT NULL DEFAULT 0 COMMENT '审批通过已扣减',
    `pending_days`    DECIMAL(6,1) NOT NULL DEFAULT 0 COMMENT '在途审批占用',
    `created_at`      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`      DATETIME(6)  NULL,
    `created_by`      BIGINT       NULL,
    `deleted_at`      DATETIME(6)  NULL,
    `alive`           TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_leave_balance` (`tenant_id`, `user_id`, `leave_type_code`, `year`, `alive`),
    KEY `idx_leave_balance_user` (`user_id`, `year`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '假期余额（可用 = total - used - pending）';

CREATE TABLE `leave_request` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `institution_id` BIGINT       NOT NULL,
    `department_id`  BIGINT       NOT NULL DEFAULT 0,
    `user_id`        BIGINT       NOT NULL,
    `applicant_name` VARCHAR(64)  NULL,
    `order_id`       BIGINT       NULL COMMENT '→ approval_order.id',
    `leave_type_code` VARCHAR(32) NOT NULL,
    `start_date`     DATE         NOT NULL,
    `end_date`       DATE         NOT NULL,
    `days`           DECIMAL(6,1) NOT NULL,
    `reason`         VARCHAR(512) NULL,
    `proof_file_id`  BIGINT       NULL COMMENT '证明材料（sys_file.id）',
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
        COMMENT 'PENDING 待审 / APPROVED 通过 / REJECTED 驳回 / CANCELED 已撤销',
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `created_by`     BIGINT       NULL,
    `deleted_at`     DATETIME(6)  NULL,
    KEY `idx_leave_request_user` (`user_id`, `created_at`),
    KEY `idx_leave_request_org` (`institution_id`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '请假单';


-- ============================================================================
-- 八、RBAC：新增两级管理员与部门负责人角色 + 权限项
-- ============================================================================

INSERT INTO `sys_role` (`tenant_id`, `role_code`, `name`, `type`, `data_scope`) VALUES
    (0, 'ROLE_TENANT_ADMIN', '租户管理员', 'BUSINESS', 'TENANT'),
    (0, 'ROLE_ORG_ADMIN',    '企业管理员', 'BUSINESS', 'ORG'),
    (0, 'ROLE_DEPT_LEADER',  '部门负责人', 'BUSINESS', 'DEPT'),
    (0, 'ROLE_MEMBER',       '机构成员',   'BUSINESS', 'SELF');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `sort`) VALUES
    (0, 'aioa:tenant:inst',      '机构管理',       'ADMIN', 70),
    (0, 'aioa:tenant:pool',      '资源池与配额',   'ADMIN', 71),
    (0, 'aioa:tenant:cost',      '费用分摊',       'ADMIN', 72),
    (0, 'aioa:tenant:grant',     '资源授权',       'ADMIN', 73),
    (0, 'aioa:tenant:audit',     '租户级审计',     'ADMIN', 74),
    (0, 'aioa:org:dept',         '部门管理',       'ADMIN', 80),
    (0, 'aioa:org:member',       '员工管理',       'ADMIN', 81),
    (0, 'aioa:org:quota',        '机构额度分配',   'ADMIN', 82),
    (0, 'aioa:org:kb',           '机构知识库',     'ADMIN', 83),
    (0, 'aioa:org:audit',        '机构审计',       'ADMIN', 84),
    (0, 'aioa:workflow:approve', '审批处理',       'API',   90),
    (0, 'aioa:leave:apply',      '请假申请',       'API',   91);

-- 租户管理员 → 租户端全部权限
INSERT INTO `sys_role_permission` (`tenant_id`, `role_id`, `perm_id`, `created_by`)
SELECT 0, r.id, p.id, 0 FROM `sys_role` r, `sys_permission` p
WHERE r.role_code = 'ROLE_TENANT_ADMIN' AND p.perm_code LIKE 'aioa:tenant:%';

-- 企业管理员 → 企业端全部权限
INSERT INTO `sys_role_permission` (`tenant_id`, `role_id`, `perm_id`, `created_by`)
SELECT 0, r.id, p.id, 0 FROM `sys_role` r, `sys_permission` p
WHERE r.role_code = 'ROLE_ORG_ADMIN' AND p.perm_code LIKE 'aioa:org:%';

-- 部门负责人 / 机构成员 → 审批与请假
INSERT INTO `sys_role_permission` (`tenant_id`, `role_id`, `perm_id`, `created_by`)
SELECT 0, r.id, p.id, 0 FROM `sys_role` r, `sys_permission` p
WHERE r.role_code IN ('ROLE_DEPT_LEADER', 'ROLE_MEMBER')
  AND p.perm_code IN ('aioa:workflow:approve', 'aioa:leave:apply');


-- ============================================================================
-- 九、入驻演示租户与账号
--   口令统一为 User@123（复用 V6 zhangsan 的 BCrypt 哈希）
-- ============================================================================

INSERT INTO `sys_tenant` (`id`, `tenant_id`, `code`, `name`, `status`) VALUES
    (2, 2, 'DSJ-DEMO', '某某市某某区大数据管理局', 'ENABLED'),
    (3, 3, 'WJJ-DEMO', '某某市某某区卫生健康局',   'ENABLED');

INSERT INTO `sys_user` (`tenant_id`, `username`, `password_hash`, `nickname`, `status`, `auth_type`, `created_by`) VALUES
    (2, 'dsj_admin',      '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '李国强', 'ENABLED', 'local', 0),
    (2, 'fagai_admin',    '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '王振华', 'ENABLED', 'local', 0),
    (2, 'shenpi_admin',   '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '陈婉如', 'ENABLED', 'local', 0),
    (2, 'chengtou_admin', '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '赵文博', 'ENABLED', 'local', 0),
    (2, 'fagai_liu',      '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '刘敏',   'ENABLED', 'local', 0),
    (2, 'fagai_li',       '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '李思远', 'ENABLED', 'local', 0),
    (2, 'fagai_chen',     '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '陈静怡', 'ENABLED', 'local', 0),
    (2, 'fagai_wu',       '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '吴俊杰', 'ENABLED', 'local', 0),
    (2, 'shenpi_zhou',    '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '周晓峰', 'ENABLED', 'local', 0),
    (2, 'shenpi_sun',     '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '孙丽华', 'ENABLED', 'local', 0),
    (2, 'chengtou_ma',    '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '马建军', 'ENABLED', 'local', 0),
    (2, 'chengtou_hu',    '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '胡文静', 'ENABLED', 'local', 0),
    (3, 'wjj_admin',      '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '周海涛', 'ENABLED', 'local', 0),
    (3, 'wjj_xu',         '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS', '徐雅琴', 'ENABLED', 'local', 0);

INSERT INTO `sys_user_role` (`tenant_id`, `user_id`, `role_id`, `created_by`)
SELECT 0, u.id, r.id, 0 FROM `sys_user` u, `sys_role` r
WHERE u.username = 'dsj_admin' AND r.role_code = 'ROLE_TENANT_ADMIN';

INSERT INTO `sys_user_role` (`tenant_id`, `user_id`, `role_id`, `created_by`)
SELECT 0, u.id, r.id, 0 FROM `sys_user` u, `sys_role` r
WHERE u.username IN ('fagai_admin', 'shenpi_admin', 'chengtou_admin', 'wjj_admin')
  AND r.role_code = 'ROLE_ORG_ADMIN';

INSERT INTO `sys_user_role` (`tenant_id`, `user_id`, `role_id`, `created_by`)
SELECT 0, u.id, r.id, 0 FROM `sys_user` u, `sys_role` r
WHERE u.username = 'fagai_liu' AND r.role_code = 'ROLE_DEPT_LEADER';

INSERT INTO `sys_user_role` (`tenant_id`, `user_id`, `role_id`, `created_by`)
SELECT 0, u.id, r.id, 0 FROM `sys_user` u, `sys_role` r
WHERE u.username IN ('fagai_li', 'fagai_chen', 'fagai_wu', 'shenpi_zhou', 'shenpi_sun',
                     'chengtou_ma', 'chengtou_hu', 'wjj_xu')
  AND r.role_code = 'ROLE_MEMBER';


-- ============================================================================
-- 十、入驻演示数据：机构 / 部门 / 员工
-- ============================================================================

-- 注：MySQL 的 VALUES 列表内不允许子查询，故统一用 INSERT ... SELECT ... UNION ALL
INSERT INTO `org_institution`
    (`id`, `tenant_id`, `name`, `code`, `org_type`, `credit_code`, `legal_person`, `contact_mobile`,
     `admin_user_id`, `admin_name`, `status`, `established_at`, `onboard_step`, `remark`)
SELECT 1, 2, '某某区发展和改革局', 'ORG-FAGAI', 'GOVERNMENT', '11330102MB1234567A', '王振华', '0571-8801****',
       u.id, '王振华', 'ACTIVE', '1978-06-15', 8,
       '区级发展改革主管部门，承担规划编制、价格管理与项目审批职能'
FROM `sys_user` u WHERE u.username = 'fagai_admin'
UNION ALL
SELECT 2, 2, '某某区行政审批局', 'ORG-SHENPI', 'GOVERNMENT', '11330102MB7654321B', '陈婉如', '0571-8802****',
       u.id, '陈婉如', 'ACTIVE', '2016-03-01', 6,
       '承担区级行政审批与政务服务事项集中办理'
FROM `sys_user` u WHERE u.username = 'shenpi_admin'
UNION ALL
SELECT 3, 2, '某某区城市建设投资集团有限公司', 'ORG-CHENGTOU', 'ENTERPRISE', '91330102MA2ABCDE7C', '赵文博', '0571-8803****',
       u.id, '赵文博', 'ACTIVE', '2003-09-28', 5,
       '区属国有企业，承担城市基础设施投资与建设'
FROM `sys_user` u WHERE u.username = 'chengtou_admin'
UNION ALL
SELECT 4, 3, '某某区卫生健康局', 'ORG-WEIJIAN', 'GOVERNMENT', '11330102MB9988776D', '周海涛', '0571-8804****',
       u.id, '周海涛', 'ACTIVE', '2019-01-10', 2,
       '另一租户下机构，用于跨租户隔离验证'
FROM `sys_user` u WHERE u.username = 'wjj_admin';

-- 注：MySQL 的 VALUES 列表内不允许子查询，故统一用 INSERT ... SELECT ... UNION ALL
INSERT INTO `org_department`
    (`id`, `tenant_id`, `institution_id`, `parent_id`, `name`, `code`, `level`, `path`,
     `leader_user_id`, `leader_name`, `sort`)
SELECT 10, 2, 1, 0, '办公室', 'FAGAI-BGS', 1, '/10/', u.id, '刘敏', 10
FROM `sys_user` u WHERE u.username = 'fagai_liu'
UNION ALL
SELECT 11, 2, 1, 0, '发展规划科', 'FAGAI-FZGH', 1, '/11/', u.id, '王振华', 20
FROM `sys_user` u WHERE u.username = 'fagai_admin'
UNION ALL
SELECT 12, 2, 1, 0, '价格管理科', 'FAGAI-JGGL', 1, '/12/', u.id, '刘敏', 30
FROM `sys_user` u WHERE u.username = 'fagai_liu'
UNION ALL
SELECT 13, 2, 1, 12, '收费管理室', 'FAGAI-SFGL', 2, '/12/13/', NULL, NULL, 31
UNION ALL
SELECT 14, 2, 1, 13, '综合收费组', 'FAGAI-ZHSF', 3, '/12/13/14/', NULL, NULL, 32
UNION ALL
SELECT 15, 2, 1, 0, '项目审批科', 'FAGAI-XMSP', 1, '/15/', NULL, NULL, 40
UNION ALL
SELECT 16, 2, 1, 0, '综合科', 'FAGAI-ZHK', 1, '/16/', NULL, NULL, 50
UNION ALL
SELECT 20, 2, 2, 0, '审批服务科', 'SHENPI-SPFW', 1, '/20/', u.id, '陈婉如', 10
FROM `sys_user` u WHERE u.username = 'shenpi_admin'
UNION ALL
SELECT 21, 2, 2, 0, '政务大厅管理科', 'SHENPI-ZWDT', 1, '/21/', NULL, NULL, 20
UNION ALL
SELECT 30, 2, 3, 0, '综合管理部', 'CT-ZHGL', 1, '/30/', u.id, '赵文博', 10
FROM `sys_user` u WHERE u.username = 'chengtou_admin'
UNION ALL
SELECT 31, 2, 3, 0, '项目管理部', 'CT-XMGL', 1, '/31/', NULL, NULL, 20
UNION ALL
SELECT 40, 3, 4, 0, '医政科', 'WJJ-YZK', 1, '/40/', NULL, NULL, 10;

INSERT INTO `org_member`
    (`tenant_id`, `institution_id`, `department_id`, `user_id`, `name`, `mobile`, `email`,
     `employee_no`, `job_title`, `is_org_admin`, `status`, `joined_at`)
SELECT 2, 1, 10, u.id, '刘敏',   '13805710001', 'liumin@fagai.gov.cn',   'FG2015003', '办公室主任',   0, 'ACTIVE', '2015-07-01'
FROM `sys_user` u WHERE u.username = 'fagai_liu'
UNION ALL
SELECT 2, 1, 11, u.id, '王振华', '13805710002', 'wangzh@fagai.gov.cn',   'FG2008001', '局长',        1, 'ACTIVE', '2008-03-10'
FROM `sys_user` u WHERE u.username = 'fagai_admin'
UNION ALL
SELECT 2, 1, 11, u.id, '李思远', '13805710003', 'lisy@fagai.gov.cn',     'FG2021011', '科员',        0, 'ACTIVE', '2021-08-16'
FROM `sys_user` u WHERE u.username = 'fagai_li'
UNION ALL
SELECT 2, 1, 12, u.id, '陈静怡', '13805710004', 'chenjy@fagai.gov.cn',   'FG2019007', '副主任科员',  0, 'ACTIVE', '2019-09-02'
FROM `sys_user` u WHERE u.username = 'fagai_chen'
UNION ALL
SELECT 2, 1, 14, u.id, '吴俊杰', '13805710005', 'wujj@fagai.gov.cn',     'FG2022004', '工作人员',    0, 'ACTIVE', '2022-06-20'
FROM `sys_user` u WHERE u.username = 'fagai_wu'
UNION ALL
SELECT 2, 2, 20, u.id, '陈婉如', '13805720001', 'chenwr@shenpi.gov.cn',  'SP2016001', '局长',        1, 'ACTIVE', '2016-03-01'
FROM `sys_user` u WHERE u.username = 'shenpi_admin'
UNION ALL
SELECT 2, 2, 20, u.id, '周晓峰', '13805720002', 'zhouxf@shenpi.gov.cn',  'SP2018009', '科员',        0, 'ACTIVE', '2018-05-14'
FROM `sys_user` u WHERE u.username = 'shenpi_zhou'
UNION ALL
SELECT 2, 2, 21, u.id, '孙丽华', '13805720003', 'sunlh@shenpi.gov.cn',   'SP2020006', '副科长',      0, 'ACTIVE', '2020-11-03'
FROM `sys_user` u WHERE u.username = 'shenpi_sun'
UNION ALL
SELECT 2, 3, 30, u.id, '赵文博', '13805730001', 'zhaowb@chengtou.com',   'CT2003001', '总经理',      1, 'ACTIVE', '2003-09-28'
FROM `sys_user` u WHERE u.username = 'chengtou_admin'
UNION ALL
SELECT 2, 3, 31, u.id, '马建军', '13805730002', 'majj@chengtou.com',     'CT2017012', '项目经理',    0, 'ACTIVE', '2017-04-11'
FROM `sys_user` u WHERE u.username = 'chengtou_ma'
UNION ALL
SELECT 2, 3, 30, u.id, '胡文静', '13805730003', 'huwj@chengtou.com',     'CT2020008', '财务主管',    0, 'ACTIVE', '2020-07-06'
FROM `sys_user` u WHERE u.username = 'chengtou_hu'
UNION ALL
SELECT 3, 4, 40, u.id, '周海涛', '13805740001', 'zhouht@weijian.gov.cn', 'WJ2019001', '局长',        1, 'ACTIVE', '2019-01-10'
FROM `sys_user` u WHERE u.username = 'wjj_admin'
UNION ALL
SELECT 3, 4, 40, u.id, '徐雅琴', '13805740002', 'xuyq@weijian.gov.cn',   'WJ2021005', '科员',        0, 'ACTIVE', '2021-03-22'
FROM `sys_user` u WHERE u.username = 'wjj_xu';


-- ============================================================================
-- 十一、入驻演示数据：资源池 / 机构配额 / 部门额度 / 分配流水
-- ============================================================================

INSERT INTO `tenant_resource_pool`
    (`tenant_id`, `period`, `token_total`, `token_used`, `expert_seats`, `expert_used`,
     `skill_seats`, `skill_used`, `warn_threshold`, `unit_price`, `expire_at`, `status`)
VALUES
    (2, '2026-09', 5000000, 0, 12, 0, 18, 0, 20, 0.000120, '2027-09-30', 'ACTIVE'),
    (3, '2026-09',  800000, 0,  4, 0,  6, 0, 20, 0.000120, '2027-09-30', 'ACTIVE');

INSERT INTO `org_quota`
    (`tenant_id`, `institution_id`, `period`, `quota_tokens`, `used_tokens`, `free_tokens`,
     `warn_threshold`, `frozen`, `effective_from`, `effective_to`, `status`)
VALUES
    (2, 1, '2026-09', 2000000, 0, 0, 20, 0, '2026-09-01', '2027-08-31', 'ACTIVE'),
    (2, 2, '2026-09', 1800000, 0, 0, 20, 0, '2026-09-01', '2027-08-31', 'ACTIVE'),
    (2, 3, '2026-09',  900000, 0, 0, 20, 0, '2026-09-01', '2027-08-31', 'ACTIVE'),
    (3, 4, '2026-09',  600000, 0, 0, 20, 0, '2026-09-01', '2027-08-31', 'ACTIVE');

INSERT INTO `dept_quota`
    (`tenant_id`, `institution_id`, `department_id`, `period`, `quota_tokens`, `used_tokens`, `warn_threshold`)
VALUES
    (2, 1, 10, '2026-09', 300000, 0, 20),
    (2, 1, 11, '2026-09', 500000, 0, 20),
    (2, 1, 12, '2026-09', 400000, 0, 20),
    (2, 1, 13, '2026-09', 200000, 0, 20),
    (2, 1, 15, '2026-09', 400000, 0, 20),
    (2, 1, 16, '2026-09', 200000, 0, 20),
    (2, 2, 20, '2026-09', 900000, 0, 20),
    (2, 2, 21, '2026-09', 900000, 0, 20),
    (2, 3, 30, '2026-09', 500000, 0, 20),
    (2, 3, 31, '2026-09', 400000, 0, 20);

INSERT INTO `quota_alloc_log`
    (`tenant_id`, `institution_id`, `scope_type`, `scope_id`, `period`, `action`,
     `before_tokens`, `delta`, `after_tokens`, `reason`, `operator_id`, `operator_name`, `operator_role`)
SELECT 2, 0, 'TENANT', 2, '2026-09', 'ALLOCATE', 0, 5000000, 5000000, '平台交付词元套餐', 0, '平台运营', 'PLATFORM_OPS'
UNION ALL
SELECT 2, 1, 'ORG', 1, '2026-09', 'ALLOCATE', 0, 2000000, 2000000, '入驻第 3 步：向机构分配配额上限', u.id, '李国强', 'ROLE_TENANT_ADMIN'
FROM `sys_user` u WHERE u.username = 'dsj_admin'
UNION ALL
SELECT 2, 1, 'DEPT', 11, '2026-09', 'ALLOCATE', 0, 500000, 500000, '入驻第 5 步：二次分配到部门', u.id, '王振华', 'ROLE_ORG_ADMIN'
FROM `sys_user` u WHERE u.username = 'fagai_admin';


-- ============================================================================
-- 十二、入驻演示数据：分摊规则 / 资源授权
-- ============================================================================

INSERT INTO `cost_alloc_rule`
    (`id`, `tenant_id`, `name`, `rule_type`, `period_type`, `config_json`, `version`,
     `effective_from`, `status`, `remark`)
VALUES
    (1, 2, '2026 年度机构分摊方案（按编制人数固定比例）', 'FIXED_RATIO', 'MONTH',
     JSON_OBJECT('ratios', JSON_ARRAY(
        JSON_OBJECT('institutionId', 1, 'ratio', 40),
        JSON_OBJECT('institutionId', 2, 'ratio', 36),
        JSON_OBJECT('institutionId', 3, 'ratio', 24))),
     1, '2026-09-01', 'ACTIVE', '比例合计 100%，变更次期生效并留痕');

INSERT INTO `resource_grant`
    (`tenant_id`, `institution_id`, `res_type`, `res_id`, `res_key`, `res_name`, `extra`, `enabled`, `granted_by`)
SELECT 2, 1, 'MODEL', m.id, m.provider_key, m.name, JSON_OBJECT('billing_ratio', 1.0), 1, 0
FROM `model_config` m WHERE m.provider_key IN ('deepseek', 'dashscope', 'echo')
UNION ALL
SELECT 2, 2, 'MODEL', m.id, m.provider_key, m.name, JSON_OBJECT('billing_ratio', 1.2), 1, 0
FROM `model_config` m WHERE m.provider_key IN ('deepseek', 'echo')
UNION ALL
SELECT 2, 3, 'MODEL', m.id, m.provider_key, m.name, JSON_OBJECT('billing_ratio', 0.8), 1, 0
FROM `model_config` m WHERE m.provider_key IN ('echo');


-- ============================================================================
-- 十三、入驻演示数据：审批流定义（多级审批）
-- ============================================================================

INSERT INTO `approval_flow_def`
    (`tenant_id`, `institution_id`, `biz_type`, `name`, `steps_json`, `status`, `remark`)
VALUES
    (2, 1, 'LEAVE', '请假审批流（部门负责人 → 企业管理员）',
     JSON_ARRAY(
        JSON_OBJECT('seq', 1, 'approver_type', 'DEPT_LEADER'),
        JSON_OBJECT('seq', 2, 'approver_type', 'ORG_ADMIN', 'threshold_days', 3)),
     'ACTIVE', '单次 ≤3 天仅需部门负责人；>3 天加签企业管理员'),
    (2, 2, 'LEAVE', '请假审批流（部门负责人 → 企业管理员）',
     JSON_ARRAY(
        JSON_OBJECT('seq', 1, 'approver_type', 'DEPT_LEADER'),
        JSON_OBJECT('seq', 2, 'approver_type', 'ORG_ADMIN', 'threshold_days', 5)),
     'ACTIVE', '审批局口径：≤5 天仅需部门负责人'),
    (2, 3, 'LEAVE', '请假审批流（部门负责人 → 企业管理员）',
     JSON_ARRAY(
        JSON_OBJECT('seq', 1, 'approver_type', 'DEPT_LEADER'),
        JSON_OBJECT('seq', 2, 'approver_type', 'ORG_ADMIN', 'threshold_days', 2)),
     'ACTIVE', '国企口径：≤2 天仅需部门负责人'),
    (2, 1, 'QUOTA_EXPAND', '额度扩容申请（企业管理员 → 租户管理员）',
     JSON_ARRAY(
        JSON_OBJECT('seq', 1, 'approver_type', 'ORG_ADMIN'),
        JSON_OBJECT('seq', 2, 'approver_type', 'TENANT_ADMIN')),
     'ACTIVE', 'FR-H3 演示链路：通过后配额自动增加'),
    (2, 1, 'RESOURCE_OPEN', '资源开通申请（企业管理员 → 租户管理员）',
     JSON_ARRAY(
        JSON_OBJECT('seq', 1, 'approver_type', 'ORG_ADMIN'),
        JSON_OBJECT('seq', 2, 'approver_type', 'TENANT_ADMIN')),
     'ACTIVE', 'FR-J2 演示链路');


-- ============================================================================
-- 十四、入驻演示数据：假种与假期余额
-- ============================================================================

INSERT INTO `leave_type`
    (`tenant_id`, `code`, `name`, `unit`, `quota_days_per_year`, `need_proof`, `advance_days`,
     `max_consecutive_days`, `paid`, `sort`, `status`)
VALUES
    (2, 'ANNUAL',    '年假', 'WORKDAY', 10,  0, 3,  15, 1, 10, 'ENABLED'),
    (2, 'SICK',      '病假', 'WORKDAY', 15,  1, 0,  30, 1, 20, 'ENABLED'),
    (2, 'CASUAL',    '事假', 'WORKDAY',  0,  0, 1,  10, 0, 30, 'ENABLED'),
    (2, 'MARRIAGE',  '婚假', 'DAY',      3,  1, 7,   3, 1, 40, 'ENABLED'),
    (2, 'MATERNITY', '产假', 'DAY',     98,  1, 30, 98, 1, 50, 'ENABLED'),
    (2, 'COMP',      '调休', 'WORKDAY',  5,  0, 0,   5, 1, 60, 'ENABLED'),
    (3, 'ANNUAL',    '年假', 'WORKDAY', 10,  0, 3,  15, 1, 10, 'ENABLED'),
    (3, 'SICK',      '病假', 'WORKDAY', 15,  1, 0,  30, 1, 20, 'ENABLED'),
    (3, 'CASUAL',    '事假', 'WORKDAY',  0,  0, 1,  10, 0, 30, 'ENABLED');

-- 为入驻演示员工李思远预置 2026 年度余额（年假 10 天 / 病假 15 天 / 调休 5 天）
INSERT INTO `leave_balance`
    (`tenant_id`, `institution_id`, `user_id`, `leave_type_code`, `year`, `total_days`, `used_days`, `pending_days`)
SELECT 2, 1, u.id, 'ANNUAL', 2026, 10, 0, 0 FROM `sys_user` u WHERE u.username = 'fagai_li'
UNION ALL
SELECT 2, 1, u.id, 'SICK',   2026, 15, 0, 0 FROM `sys_user` u WHERE u.username = 'fagai_li'
UNION ALL
SELECT 2, 1, u.id, 'CASUAL', 2026,  0, 0, 0 FROM `sys_user` u WHERE u.username = 'fagai_li'
UNION ALL
SELECT 2, 1, u.id, 'COMP',   2026,  5, 0, 0 FROM `sys_user` u WHERE u.username = 'fagai_li'
UNION ALL
SELECT 2, 1, u.id, 'ANNUAL', 2026, 10, 0, 0 FROM `sys_user` u WHERE u.username = 'fagai_chen'
UNION ALL
SELECT 2, 1, u.id, 'SICK',   2026, 15, 0, 0 FROM `sys_user` u WHERE u.username = 'fagai_chen';
