-- V71：项目管理模块（PM）批次 1 —— 项目 / 成员 / 任务 三表 + 仓库绑定列 + 权限码
--
-- 依据：docs/40-项目管理模块设计与实施计划.md §6.1（V71 段）。
-- 本文件是批次 1 的落地：项目 CRUD + 类型守卫（BR-01/02）+ 成员（BR-03/04/05）
--   + 任务 CRUD 与状态机（BR-10）+ 仓库绑定与成对约束（BR-06/BR-12）。
-- 批次 3/4 的 pm_folder/pm_document（V72）与 pm_expense/pm_contract/...（V73）不在本文件。
--
-- ★ 三条不能省的约定（沿用现库既有做法，别自创写法）：
--   1) 租户维度：每表必有 tenant_id，所有查询按它收窄；
--   2) 软删 + 唯一键：deleted_at + 虚拟生成列 alive = IF(deleted_at IS NULL,1,NULL)，
--      唯一键末位带 alive —— 未删行 alive=1 参与防重，已删行 alive=NULL 不参与（可重登录同编码）。
--      ⚠ 由此推出铁律：**软删行会从唯一约束里消失**，所以「插入前必须先查软删行」，
--      否则同一 project_no 删了再建会撞不上唯一键、却在前端表现为「两条同名项目」。
--      生成列 alive **不要**在实体类里映射（MyBatis-Plus 会尝试写它而报错）。
--   3) 字符集 utf8mb4 / 存储引擎 InnoDB / 时间 DATETIME(6)。
--
-- ★ 命名冲突告警：本模块的「任务」表叫 `pm_task`。
--   既有的 `gitee_task` 是 **异步任务队列（outbox）**（task_type=CREATE_REPO/SYNC_MEMBER…），
--   与「人做的业务任务」是两回事。两者**不得**互相复用或改名为 task。

-- ---------------------------------------------------------------------------
-- 1. 项目主表：业务项目与开发项目共用一张表，project_type 决定配置面
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_project` (
    `id`             BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT        NOT NULL,
    `project_no`     VARCHAR(64)   NOT NULL COMMENT '项目编号（租户内唯一）',
    `name`           VARCHAR(160)  NOT NULL COMMENT '项目名称',
    `project_type`   VARCHAR(16)   NOT NULL COMMENT 'BUSINESS 业务项目 / DEV 开发项目',
    `status`         VARCHAR(16)   NOT NULL DEFAULT 'ACTIVE'
        COMMENT 'DRAFT 草稿 / ACTIVE 进行中 / SUSPENDED 暂停 / CLOSED 已结项 / ARCHIVED 已归档',
    `institution_id` BIGINT        NOT NULL COMMENT '归属机构',
    `department_id`  BIGINT        NOT NULL DEFAULT 0 COMMENT '归属部门（0=机构直属）',
    `owner_member_id` BIGINT       NULL COMMENT '项目负责人（org_member.id，非 sys_user.id）',
    `budget_amount`  DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '预算总额（计划值，实际值在 pm_expense）',
    `start_date`     DATE          NULL,
    `end_date`       DATE          NULL,
    `description`    VARCHAR(1024) NULL,
    `created_by`     BIGINT        NULL,
    `created_at`     DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)   NULL,
    `deleted_at`     DATETIME(6)   NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_project_no` (`tenant_id`, `project_no`, `alive`),
    KEY `idx_pm_project_scope` (`tenant_id`, `institution_id`, `department_id`, `status`),
    KEY `idx_pm_project_type` (`tenant_id`, `project_type`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目主表（业务/开发两类型共用）';

-- ---------------------------------------------------------------------------
-- 2. 项目成员 + 项目内角色
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_project_member` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT      NOT NULL,
    `project_id`   BIGINT      NOT NULL,
    `member_id`    BIGINT      NOT NULL COMMENT 'org_member.id（只能是本租户在册员工）',
    `user_id`      BIGINT      NULL COMMENT '冗余 sys_user.id，便于按登录人过滤「我参与的项目」',
    `role_code`    VARCHAR(16) NOT NULL DEFAULT 'MEMBER'
        COMMENT 'OWNER 负责人 / PM 项目经理 / DEV 开发 / MEMBER 成员 / VIEWER 只读',
    `repo_sync_status` VARCHAR(16) NOT NULL DEFAULT 'NA'
        COMMENT 'NA 业务项目无仓库 / SYNCED / PENDING / FAILED（开发项目的仓库协作者同步态）',
    `joined_at`    DATE        NULL,
    `created_by`   BIGINT      NULL,
    `created_at`   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`   DATETIME(6) NULL,
    `deleted_at`   DATETIME(6) NULL,
    `alive`        TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_project_member` (`project_id`, `member_id`, `alive`),
    KEY `idx_pm_member_user` (`tenant_id`, `user_id`),
    KEY `idx_pm_member_project` (`project_id`, `role_code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目成员与项目内角色';

-- ---------------------------------------------------------------------------
-- 3. 业务任务（注意：与 gitee_task「异步队列」无关，勿混用）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_task` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT        NOT NULL,
    `project_id`      BIGINT        NOT NULL,
    `parent_id`       BIGINT        NULL COMMENT '父任务（子任务），最多两级',
    `title`           VARCHAR(256)  NOT NULL,
    `description`     VARCHAR(2048) NULL,
    `status`          VARCHAR(16)   NOT NULL DEFAULT 'TODO'
        COMMENT 'TODO 待办 / DOING 进行中 / BLOCKED 阻塞 / DONE 已完成 / CANCELED 已取消',
    `priority`        VARCHAR(8)    NOT NULL DEFAULT 'MEDIUM' COMMENT 'LOW / MEDIUM / HIGH / URGENT',
    `assignee_member_id` BIGINT     NULL COMMENT '负责人 org_member.id',
    `start_date`      DATE          NULL,
    `due_date`        DATE          NULL,
    `progress`        TINYINT       NOT NULL DEFAULT 0 COMMENT '进度 0-100',
    -- 仓库关联：仅开发项目可写（BR-01 类型守卫 + BR-12 成对约束），业务项目这些列恒为 NULL
    `repo_id`         BIGINT        NULL COMMENT 'gitee_project.id（仅开发项目）',
    `repo_issue_no`   VARCHAR(32)   NULL COMMENT '关联 issue 号（仅开发项目，与 repo_id 成对）',
    `repo_branch`     VARCHAR(128)  NULL COMMENT '分支名（仅开发项目）',
    `repo_commit_sha` VARCHAR(64)   NULL COMMENT '关联提交 SHA（仅开发项目）',
    `created_by`      BIGINT        NULL,
    `created_at`      DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`      DATETIME(6)   NULL,
    `deleted_at`      DATETIME(6)   NULL,
    `alive`           TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    KEY `idx_pm_task_project` (`tenant_id`, `project_id`, `status`),
    KEY `idx_pm_task_assignee` (`assignee_member_id`, `status`),
    KEY `idx_pm_task_parent` (`parent_id`),
    KEY `idx_pm_task_repo` (`repo_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目任务（业务任务，非异步队列）';

-- ---------------------------------------------------------------------------
-- 4. 仓库 ↔ 项目绑定：对既有 gitee_project 做**最小改动**（只加一列 + 一索引）
-- ---------------------------------------------------------------------------
-- 为什么不新建映射表：gitee_project 已是「平台项目 ↔ Gitee 仓库」的唯一事实源，
-- 再建一张 pm_repo_bind 会让「一个仓库能绑两个项目」成为合法状态（无唯一约束兜底）。
-- 加一列则天然满足 BR-06「一个仓库只归一个项目」——一个 gitee_project 行只有一个 pm_project_id。
-- 空 = 未归属任何项目（既有 V48 数据全为空，零回归；既有仓库仍可在「项目与仓库」页独立管理）。
ALTER TABLE `gitee_project`
    ADD COLUMN `pm_project_id` BIGINT NULL COMMENT '归属项目 pm_project.id；NULL=未归属项目',
    ADD KEY `idx_gitee_project_pm` (`tenant_id`, `pm_project_id`);

-- ---------------------------------------------------------------------------
-- 5. 权限码（与 PermissionCatalog 同源；sys_permission 供权限申请链路展示与发放）
-- ---------------------------------------------------------------------------
-- 三段链纪律：权限码必须**同时**登记到 PermissionCatalog（Java 常量 + GRANTS + PERMISSION_NAMES）
-- 与本表，否则前端菜单/路由会因「后端不认」而 403（菜单/路由/接口三层必须同源）。
--
-- 本批次只播种**已实现能力**的 5 个码；pm:doc:manage / pm:budget:manage / pm:contract:manage
-- 随批次 3/4 的表一起播种 —— 先播未实现的码会让它出现在「可申请权限」清单里，
-- 用户申请到却无任何端点认它（能力事实上不可用）。
INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:project:view', '项目管理（查看）', 'APP', NULL, 100, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:project:view');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:project:create', '项目管理（新建项目）', 'APP', NULL, 101, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:project:create');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:project:manage', '项目管理（改项目/改状态/软删/绑仓库）', 'APP', NULL, 102, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:project:manage');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:member:manage', '项目管理（成员与角色）', 'APP', NULL, 103, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:member:manage');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:task:manage', '项目管理（任务）', 'APP', NULL, 104, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:task:manage');
