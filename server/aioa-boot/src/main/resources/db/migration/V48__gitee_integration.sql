-- ===========================================================================
-- V48 · Gitee V5 联动（多部门项目 ↔ Gitee 仓库）
-- ===========================================================================
-- 需求：平台为业务层、Gitee 为 Git 底层存储。不同部门在平台建项目 → 平台自动在
--   Gitee 组织的对应团队名下建仓库；支持网页上传提交与本地 git push；Gitee 的
--   提交 / PR / Issue / 评论通过 Webhook 回传到平台展示。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V47，故本文件为 V48。
--
-- ⚠️ 本仓 alive 约定（见 V43）：alive TINYINT GENERATED ALWAYS AS (IF(deleted_at IS NULL,1,NULL)) VIRTUAL，
--    仅用于配合唯一键让软删行不占位。本迁移的软删表一律遵守。
--
-- ⚠️ **实测过的 Gitee V5 能力边界**（2026-09-16 逐端点探测，证据见 docs/30 §2）：
--    · 可用：POST /orgs/{org}/repos（组织内建仓）、POST /repos/{o}/{r}/hooks（配 Webhook）、
--            POST /repos/{o}/{r}/contents/{path}（网页提交）、
--            POST|GET /repos/{o}/{r}/collaborators（仓库协作者＝成员权限）、
--            GET /repos/{o}/{r}/teams（**仓库级**团队关联）、branches / commits / pulls / issues 等。
--    · **不可用**：/orgs/{org}/teams（组织级团队的创建/列举）在 gitee.com V5 返回 **HTML 404**，
--            即「在组织内创建 Team」没有开放 API。因此部门→Team 采用「平台侧逻辑 Team +
--            仓库命名命名空间 + 协作者权限」落地，并保留 gitee_team_id 供企业版/未来 API 对接。
--      这正是 gitee_team.provider 字段存在的理由（NAMESPACE / API 两种实现）。
--    · 未认证请求会 **403 Rate Limit Exceeded**（实测），故所有写操作必须走 gitee_task 异步队列。
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. gitee_account · 平台用户 ↔ Gitee 账号绑定（OAuth2 授权码模式）
-- ---------------------------------------------------------------------------
-- gitee_uid 是**身份映射的锚点**：Webhook 回传的是 Gitee 用户信息，
--   只能靠 gitee_uid 反查平台 user_id（登录名可改、昵称可改，uid 不变）。
-- 令牌安全：access_token / refresh_token **加密存储**（AES-GCM，密文带 `enc:` 前缀，
--   密钥来自 aioa.gitee.token-enc-key），且**任何接口都不得把令牌回传前端**。
CREATE TABLE IF NOT EXISTS `gitee_account` (
    `id`               BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`        BIGINT        NOT NULL COMMENT '所属租户',
    `user_id`          BIGINT        NOT NULL COMMENT '平台用户 id（sys_user.id）',
    `gitee_uid`        BIGINT        NOT NULL COMMENT 'Gitee 数字 id：Webhook 身份映射的锚点',
    `gitee_username`   VARCHAR(128)  NOT NULL COMMENT 'Gitee 登录名（可改，仅用于展示与协作者接口）',
    `gitee_name`       VARCHAR(128)  NULL COMMENT 'Gitee 昵称',
    `avatar_url`       VARCHAR(512)  NULL COMMENT 'Gitee 头像',
    `access_token`     VARCHAR(1024) NOT NULL COMMENT 'OAuth2 access_token（AES-GCM 密文，enc: 前缀）',
    `refresh_token`    VARCHAR(1024) NULL COMMENT 'OAuth2 refresh_token（密文）；用于自动续期',
    `token_expires_at` DATETIME(6)   NULL COMMENT 'access_token 过期时间；为空表示不过期',
    `scope`            VARCHAR(255)  NULL COMMENT '授权 scope（须含 repo）',
    `bound_at`         DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '首次绑定时间',
    `refreshed_at`     DATETIME(6)   NULL COMMENT '最近一次刷新令牌时间',
    `created_at`       DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`       DATETIME(6)   NULL,
    `deleted_at`       DATETIME(6)   NULL COMMENT '解绑＝软删（保留审计）',
    `alive`            TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_gitee_account_user` (`tenant_id`, `user_id`, `alive`),
    UNIQUE KEY `uk_gitee_account_gitee` (`tenant_id`, `gitee_uid`, `alive`)
        COMMENT '同一 Gitee 账号在同一租户内只能绑定一个平台用户',
    KEY `idx_gitee_account_uid` (`gitee_uid`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Gitee 账号绑定与 OAuth2 令牌';

-- ---------------------------------------------------------------------------
-- 2. gitee_oauth_state · 授权码模式的 state（防 CSRF + 防重放）
-- ---------------------------------------------------------------------------
-- OAuth2 授权码模式必须有 state：回调是**无鉴权**的浏览器跳转，
--   若不校验 state，攻击者可用自己的 code 诱导受害者完成绑定（账号劫持）。
CREATE TABLE IF NOT EXISTS `gitee_oauth_state` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `state`        VARCHAR(64)  NOT NULL COMMENT '随机 state（一次性）',
    `tenant_id`    BIGINT       NOT NULL,
    `user_id`      BIGINT       NOT NULL COMMENT '发起授权的平台用户',
    `redirect_uri` VARCHAR(512) NOT NULL COMMENT '发起时使用的回调地址（回调必须原样匹配）',
    `consumed`     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=已被回调消费（防重放）',
    `expires_at`   DATETIME(6)  NOT NULL COMMENT 'state 有效期（默认 10 分钟）',
    `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY `uk_gitee_oauth_state` (`state`),
    KEY `idx_gitee_oauth_state_exp` (`expires_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Gitee OAuth2 state（一次性防 CSRF）';

-- ---------------------------------------------------------------------------
-- 3. gitee_team · 部门 ↔ Gitee 团队（部门隔离的落点）
-- ---------------------------------------------------------------------------
-- 部门隔离三重落地：
--   ① namespace：该部门仓库的**命名前缀**（如 `dept21-`），保证仓库在组织内可按部门聚类；
--   ② gitee_team_id：企业版 / 未来 API 开放时，把仓库真正挂到组织团队下（repo-teams 关联）；
--   ③ 协作者权限：见 gitee_repo_member，跨部门成员必须被显式加为协作者才可见。
-- provider 取值：NAMESPACE（默认，开源 gitee.com 可用）/ API（组织团队 API 可用时）。
CREATE TABLE IF NOT EXISTS `gitee_team` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL,
    `department_id` BIGINT       NOT NULL COMMENT '平台部门 id（org_department.id）',
    `org_name`      VARCHAR(128) NOT NULL COMMENT 'Gitee 总组织（login）',
    `team_name`     VARCHAR(128) NOT NULL COMMENT '团队显示名（默认取部门名）',
    `namespace`     VARCHAR(64)  NOT NULL COMMENT '仓库命名前缀，部门隔离的可观测落点',
    `gitee_team_id` BIGINT       NULL COMMENT 'Gitee 组织团队 id；NAMESPACE 模式下为空',
    `provider`      VARCHAR(16)  NOT NULL DEFAULT 'NAMESPACE' COMMENT 'NAMESPACE / API',
    `provisioned`   TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=已在 Gitee 侧真正建好（API 模式）',
    `remark`        VARCHAR(255) NULL,
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6)  NULL,
    `deleted_at`    DATETIME(6)  NULL,
    `alive`         TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_gitee_team_dept` (`tenant_id`, `department_id`, `alive`),
    KEY `idx_gitee_team_ns` (`tenant_id`, `namespace`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '部门 ↔ Gitee 组织团队（部门隔离）';

-- ---------------------------------------------------------------------------
-- 4. gitee_project · 平台项目 ↔ Gitee 仓库映射
-- ---------------------------------------------------------------------------
-- status 状态机：CREATING → ACTIVE（建仓+Webhook 均成功）
--                CREATING → FAILED（建仓或配 Webhook 失败，error_msg 记原因，可重试）
--                ACTIVE   → DELETED（软删；是否删 Gitee 仓库由 purge_repo 记录）
-- webhook_secret 用**明文**存：它是回调校验的共享密钥，平台必须能原样比对；
--   但同样**不得回传前端**（前端只需要知道「已配置」）。
CREATE TABLE IF NOT EXISTS `gitee_project` (
    `id`               BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`        BIGINT       NOT NULL,
    `department_id`    BIGINT       NOT NULL COMMENT '归属部门（单一归属，跨部门需显式加成员）',
    `team_id`          BIGINT       NULL COMMENT '关联 gitee_team.id',
    `name`             VARCHAR(128) NOT NULL COMMENT '项目名（展示用）',
    `repo_name`        VARCHAR(160) NOT NULL COMMENT 'Gitee 仓库名（含部门命名前缀）',
    `description`      VARCHAR(512) NULL,
    `visibility`       VARCHAR(16)  NOT NULL DEFAULT 'private' COMMENT 'private / public',
    `gitee_owner`      VARCHAR(128) NOT NULL COMMENT '仓库 owner（总组织 login 或用户 login）',
    `gitee_repo`       VARCHAR(160) NOT NULL COMMENT 'Gitee 仓库 path（API 路径段）',
    `gitee_repo_id`    BIGINT       NULL COMMENT 'Gitee 仓库数字 id',
    `gitee_html_url`   VARCHAR(512) NULL COMMENT '网页地址（前端「跳转原仓库」用）',
    `gitee_ssh_url`    VARCHAR(512) NULL COMMENT 'SSH 地址（本地 git push 用）',
    `gitee_https_url`  VARCHAR(512) NULL COMMENT 'HTTPS 地址',
    `default_branch`   VARCHAR(64)  NULL DEFAULT 'master' COMMENT '默认分支',
    `webhook_id`       BIGINT       NULL COMMENT 'Gitee Webhook id（用于后续更新/删除）',
    `webhook_secret`   VARCHAR(128) NULL COMMENT 'Webhook 校验密钥（Gitee 侧 password，明文存但不下发）',
    `webhook_events`   VARCHAR(255) NULL COMMENT '已订阅事件，逗号分隔',
    `status`           VARCHAR(16)  NOT NULL DEFAULT 'CREATING' COMMENT 'CREATING/ACTIVE/FAILED/DELETED',
    `error_msg`        VARCHAR(512) NULL COMMENT '建仓或配置失败原因',
    `purge_repo`       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删项目时是否同时删除 Gitee 仓库',
    `created_by`       BIGINT       NULL,
    `created_at`       DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`       DATETIME(6)  NULL,
    `deleted_at`       DATETIME(6)  NULL,
    `alive`            TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_gitee_project_repo` (`tenant_id`, `gitee_owner`, `gitee_repo`, `alive`),
    KEY `idx_gitee_project_dept` (`tenant_id`, `department_id`, `status`),
    KEY `idx_gitee_project_status` (`status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '平台项目 ↔ Gitee 仓库映射';

-- ---------------------------------------------------------------------------
-- 5. gitee_repo_member · 仓库成员（平台 → Gitee 权限同步的记账）
-- ---------------------------------------------------------------------------
-- 为什么按 gitee_username 而不是 user_id 做唯一键：
--   仓库协作者接口认的是 Gitee 登录名，且**可能有人在 Gitee 侧被直接加入**（user_id 为 NULL）。
--   source 区分来源：PLATFORM（平台同步）/ GITEE（定时校准发现的外部变更）。
CREATE TABLE IF NOT EXISTS `gitee_repo_member` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `project_id`     BIGINT       NOT NULL,
    `user_id`        BIGINT       NULL COMMENT '平台用户 id；Gitee 侧直接加入且未绑定时为空',
    `gitee_uid`      BIGINT       NULL,
    `gitee_username` VARCHAR(128) NOT NULL COMMENT 'Gitee 登录名（协作者接口的键）',
    `role`           VARCHAR(16)  NOT NULL DEFAULT 'WRITE' COMMENT 'READ / WRITE / ADMIN',
    `source`         VARCHAR(16)  NOT NULL DEFAULT 'PLATFORM' COMMENT 'PLATFORM / GITEE',
    `sync_status`    VARCHAR(16)  NOT NULL DEFAULT 'SYNCED' COMMENT 'SYNCED / PENDING / FAILED',
    `last_error`     VARCHAR(255) NULL,
    `synced_at`      DATETIME(6)  NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_gitee_repo_member` (`project_id`, `gitee_username`, `alive`),
    KEY `idx_gitee_repo_member_user` (`tenant_id`, `user_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Gitee 仓库成员与权限同步状态';

-- ---------------------------------------------------------------------------
-- 6. gitee_event · 操作事件日志（Webhook 回传的落点）
-- ---------------------------------------------------------------------------
-- 幂等：Gitee 会**重复投递**同一事件。event_key 由「事件类型 + 业务标识」拼成
--   （push→request_id/sha、MR→id+action、Issue→id+action、评论→id+updated_at），
--   唯一键冲突即视为重复投递，直接丢弃并记 hit，保证用户不会看到重复条目。
-- 身份映射：actor_gitee_uid → actor_user_id（未绑定则为 NULL，前端显示 Gitee 登录名）。
CREATE TABLE IF NOT EXISTS `gitee_event` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`       BIGINT        NOT NULL,
    `project_id`      BIGINT        NULL COMMENT '命中的平台项目；未找到映射时为空',
    `event_type`      VARCHAR(32)   NOT NULL COMMENT 'PUSH / MERGE_REQUEST / ISSUE / NOTE / OTHER',
    `gitee_event`     VARCHAR(64)   NULL COMMENT 'Gitee 原始事件头（如 Push Hook / Merge Request Hook）',
    `event_key`       VARCHAR(190)  NOT NULL COMMENT '幂等键（唯一）',
    `request_id`      VARCHAR(64)   NULL COMMENT 'Gitee 请求 id',
    `commit_sha`      VARCHAR(64)   NULL,
    `actor_gitee_uid` BIGINT        NULL COMMENT '操作人 Gitee uid（身份映射输入）',
    `actor_login`     VARCHAR(128)  NULL COMMENT '操作人 Gitee 登录名',
    `actor_user_id`   BIGINT        NULL COMMENT '映射到的平台用户 id；未绑定为空',
    `ref_name`        VARCHAR(255)  NULL COMMENT '分支 / 标签 / 目标分支',
    `action`          VARCHAR(32)   NULL COMMENT 'opened / closed / merged / comment 等',
    `title`           VARCHAR(512)  NULL COMMENT '可读标题（PR/Issue 标题）',
    `summary`         VARCHAR(1024) NULL COMMENT '一句话摘要（前端列表直接展示）',
    `payload`         JSON          NULL COMMENT '原始报文（排障用；列表接口不返回）',
    `occurred_at`     DATETIME(6)   NULL COMMENT 'Gitee 侧发生时间',
    `received_at`     DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '平台接收时间',
    UNIQUE KEY `uk_gitee_event_key` (`event_key`),
    KEY `idx_gitee_event_project` (`project_id`, `id`),
    KEY `idx_gitee_event_actor` (`actor_gitee_uid`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Gitee 操作事件日志（Webhook 回传）';

-- ---------------------------------------------------------------------------
-- 7. gitee_commit · 提交记录（网页上传 + Webhook push 两路合一）
-- ---------------------------------------------------------------------------
-- 两路来源：WEB（平台网页上传文件经 contents 接口提交）/ GIT（本地 git push 经 Webhook 回传）。
-- 唯一键 (project_id, sha)：同一提交被重复投递或同时被两路记录时只留一条。
CREATE TABLE IF NOT EXISTS `gitee_commit` (
    `id`             BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT        NOT NULL,
    `project_id`     BIGINT        NOT NULL,
    `sha`            VARCHAR(64)   NOT NULL COMMENT '提交 sha（short/long 统一按长 sha 存）',
    `branch`         VARCHAR(128)  NULL,
    `message`        VARCHAR(1024) NULL COMMENT '提交信息',
    `author_name`    VARCHAR(128)  NULL,
    `author_email`   VARCHAR(190)  NULL,
    `gitee_uid`      BIGINT        NULL COMMENT '作者 Gitee uid（可用于身份映射）',
    `author_user_id` BIGINT        NULL COMMENT '映射到的平台用户 id',
    `source`         VARCHAR(16)   NOT NULL DEFAULT 'GIT' COMMENT 'WEB / GIT',
    `event_id`       BIGINT        NULL COMMENT '来源事件（GIT 路径）',
    `committed_at`   DATETIME(6)   NULL,
    `created_at`     DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY `uk_gitee_commit` (`project_id`, `sha`),
    KEY `idx_gitee_commit_branch` (`project_id`, `branch`, `id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Gitee 提交记录（网页 + git push 合流）';

-- ---------------------------------------------------------------------------
-- 8. gitee_task · 异步任务队列（outbox）
-- ---------------------------------------------------------------------------
-- 为什么不用 MQ / Redis：本部署**没有可用的 Redis**（application.yml 里配了但健康检查被关），
--   引入外部中间件会把这个功能变成「部署必装项」。落库 + @Scheduled 轮询最简单可靠。
-- 为什么必须异步：① Gitee 对未认证/高频请求会 403 Rate Limit Exceeded（实测）；
--   ② 建仓 + 配 Webhook + 同步成员是**多步外部调用**，同步做会让建项目接口超时。
-- 并发安全：抢占式领取（UPDATE ... SET status='RUNNING', locked_by=? WHERE id=? AND status='PENDING'）。
CREATE TABLE IF NOT EXISTS `gitee_task` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT       NOT NULL,
    `task_type`    VARCHAR(32)  NOT NULL COMMENT 'CREATE_REPO / CONFIGURE_WEBHOOK / SYNC_MEMBER / DELETE_REPO / SYNC_ALL',
    `biz_type`     VARCHAR(32)  NULL COMMENT 'PROJECT / MEMBER',
    `biz_id`       BIGINT       NULL COMMENT '业务主键（project_id / member_id）',
    `payload`      JSON         NULL COMMENT '任务参数',
    `status`       VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING / RUNNING / DONE / FAILED',
    `attempts`     INT          NOT NULL DEFAULT 0,
    `max_attempts` INT          NOT NULL DEFAULT 5,
    `next_run_at`  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '下次可执行时间（失败退避）',
    `locked_at`    DATETIME(6)  NULL,
    `locked_by`    VARCHAR(64)  NULL,
    `last_error`   VARCHAR(512) NULL,
    `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`   DATETIME(6)  NULL,
    KEY `idx_gitee_task_pick` (`status`, `next_run_at`, `id`),
    KEY `idx_gitee_task_biz` (`biz_type`, `biz_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Gitee 异步任务队列（outbox，规避限流）';

-- ---------------------------------------------------------------------------
-- 9. 权限码（与 PermissionCatalog 同源；sys_permission 供权限申请链路展示与发放）
-- ---------------------------------------------------------------------------
-- 三段链纪律：WorkerRole → requiredPermission → PermissionCatalog，未知码默认拒绝。
-- 因此新权限码必须**同时**登记到 PermissionCatalog（Java 常量）与本表，否则
-- 前端菜单/路由会因「后端不认」而 403（菜单/路由/接口三层必须同源）。
INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'project:view', '项目与代码仓库（查看）', 'APP', NULL, 90, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'project:view');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'project:manage', '项目与代码仓库（管理）', 'APP', NULL, 91, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'project:manage');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'gitee:bind', 'Gitee 账号绑定', 'API', NULL, 92, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'gitee:bind');
