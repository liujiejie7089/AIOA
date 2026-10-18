-- V74：项目管理模块（PM）—— 项目数字人分配 + 项目上下文控制（全新能力，docs/43 §4）
--
-- 依据：docs/43-项目管理模块_批次2-4与数字人上下文_落地设计.md。
-- 用户关键词：「分配项目数字人（后台上传，网上搜索,政策）」「项目上下文控制」。
--
-- ★ 复用而非重造：本平台**已有**「数字员工」子系统（docs/10、docs/15）——
--   实例在 `agent_worker`，会话经 `chat_conversation.worker_id` 绑定，职责边界由 `WorkerRole` 唯一定义。
--   因此「分配项目数字人」= 把**已存在的数字员工**挂到一个项目上（新表 pm_project_worker），
--   **不新建第二套数字人**（否则出现两套账号/两套职责，与单入口纪律冲突）。
-- ★ 「上下文」= 该数字人在本项目里可用的知识来源，三类：
--   UPLOAD     后台上传（项目文档 / 指定文件夹）
--   WEB_SEARCH 网上搜索（关键词/域名/条数，config JSON）
--   POLICY     政策（政策知识库文档 kb_document）
--   全部落 `pm_context_source` 一张表，用 source_type 区分 —— 与 docs/40 §8.3「同表 + 判別列」同款取舍。
--
-- ★ 三条既有约定照抄（见 V71 顶部说明）：tenant_id；软删 deleted_at + alive（唯一键末位带 alive）；
--   生成列 alive 不映射实体；utf8mb4/InnoDB/DATETIME(6)。

-- ---------------------------------------------------------------------------
-- 1. 项目 ↔ 数字员工 分配（一个项目可分配多个数字员工；一个数字员工可服务多个项目）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_project_worker` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT      NOT NULL,
    `project_id`   BIGINT      NOT NULL,
    `worker_id`    BIGINT      NOT NULL COMMENT 'agent_worker.id（既有数字员工，非新建）',
    `assign_role`  VARCHAR(32) NOT NULL DEFAULT '' COMMENT '在本项目的用途说明（如「项目助理」「合同初审」）',
    `enabled`      TINYINT     NOT NULL DEFAULT 1 COMMENT '0 已停用（停用后本项目不再下发其上下文）',
    `assigned_by`  BIGINT      NULL COMMENT '分配人 sys_user.id',
    `created_at`   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`   DATETIME(6) NULL,
    `deleted_at`   DATETIME(6) NULL,
    `alive`        TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_project_worker` (`project_id`, `worker_id`, `alive`),
    KEY `idx_pm_pw_worker` (`tenant_id`, `worker_id`),
    KEY `idx_pm_pw_project` (`project_id`, `enabled`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目 ↔ 数字员工 分配（复用既有数字员工）';

-- ---------------------------------------------------------------------------
-- 2. 项目上下文来源（项目数字人可用的知识来源；「项目上下文控制」的存储）
-- ---------------------------------------------------------------------------
CREATE TABLE `pm_context_source` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL,
    `project_id`     BIGINT       NOT NULL,
    `worker_id`      BIGINT       NOT NULL DEFAULT 0 COMMENT '0=项目级默认上下文（对所有已分配数字人生效）；否则仅对该数字员工',
    `source_type`    VARCHAR(16)  NOT NULL COMMENT 'UPLOAD 后台上传 / WEB_SEARCH 网上搜索 / POLICY 政策',
    `name`           VARCHAR(160) NOT NULL DEFAULT '' COMMENT '来源显示名',
    `folder_id`      BIGINT       NULL COMMENT 'UPLOAD：指向 pm_folder（整目录纳入）',
    `file_id`        BIGINT       NULL COMMENT 'UPLOAD：指向 sys_file（单文件纳入）',
    `kb_document_id` BIGINT       NULL COMMENT 'POLICY：指向 kb_document（政策库文档）',
    `config`         JSON         NULL COMMENT 'WEB_SEARCH：{"keywords":[...],"domains":[...],"maxResults":N}',
    `enabled`        TINYINT      NOT NULL DEFAULT 1 COMMENT '0 已关闭（保留配置但不参与上下文组装）',
    `created_by`     BIGINT       NULL,
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    `deleted_at`     DATETIME(6)  NULL,
    `alive`          TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    KEY `idx_pm_ctx_project` (`tenant_id`, `project_id`, `source_type`, `enabled`),
    KEY `idx_pm_ctx_worker` (`project_id`, `worker_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目上下文来源（上传/网搜/政策）';

-- ---------------------------------------------------------------------------
-- 3. 权限码 —— 同 V73：**有意不播种** pm:ai:manage。
--    纪律：只为已实现能力播种权限码（见 V71 顶部）。数字人分配 / 上下文控制的端点落地时
--    随其实现在**当次**迁移里补这个码。
-- ---------------------------------------------------------------------------
