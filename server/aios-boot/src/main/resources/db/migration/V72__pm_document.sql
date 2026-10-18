-- V72：项目管理模块（PM）批次 3 —— 文档（文件夹 + 文档）
--
-- 依据：docs/40 §6.2（V72 段）+ docs/43（关键词落地设计）。
-- 本文件落地：pm_folder（企业级公共 / 项目专属两类文件夹）+ pm_document（文档索引）。
-- 批次 4 的 pm_expense/pm_contract/...（V73）与「项目数字人分配 / 项目上下文控制」（V74）不在本文件。
--
-- ★ 与 docs/40 §6.2 草案的一处**有意修正**（否则是一个真缺陷）：
--   草案的 `parent_id` 与唯一键写法
--     parent_id BIGINT NULL, UNIQUE KEY (tenant_id, COALESCE(project_id,0), parent_id, name, alive)
--   有陷阱：MySQL 唯一键里 **NULL 视为彼此不同** ⇒ 同一个根下（parent_id=NULL）
--   可以插入两条同名文件夹，唯一约束形同虚设。
--   修正：`parent_id BIGINT NOT NULL DEFAULT 0`（0=根，沿用本项目 department_id=0「机构直属」的同款约定），
--   唯一键用 `(tenant_id, COALESCE(project_id,0), parent_id, name, alive)`，根目录也随之受约束。
--   上层服务把「父为根」统一表示为 parent_id=0，不出现 NULL。
--
-- ★ 三条既有约定照抄（见 V71 顶部说明）：tenant_id 收窄；软删 deleted_at + 虚拟列 alive，
--   唯一键末位带 alive（⇒ 插入前必须先查软删行）；生成列 alive 不映射到实体；utf8mb4/InnoDB/DATETIME(6)。

-- ---------------------------------------------------------------------------
-- 1. 文档文件夹：企业级公共（跨项目）与项目专属（挂在项目下）两类同表
-- ---------------------------------------------------------------------------
-- 为什么两类同表：结构完全一致（父子树 + 命名唯一），只差 scope 与是否带 project_id。
-- 拆两张表会让「进入项目文档页要同时查两棵树」，且级联策略（BR-07）要写两遍。
CREATE TABLE `pm_folder` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`    BIGINT       NOT NULL,
    `scope`        VARCHAR(16)  NOT NULL COMMENT 'ENTERPRISE 企业级公共（project_id=0） / PROJECT 项目专属',
    `project_id`   BIGINT       NOT NULL DEFAULT 0 COMMENT 'scope=PROJECT 时必填；ENTERPRISE 固定 0',
    `parent_id`    BIGINT       NOT NULL DEFAULT 0 COMMENT '父文件夹 pm_folder.id；0=根（不用 NULL，见文件头修正说明）',
    `name`         VARCHAR(128) NOT NULL COMMENT '文件夹名（同租户同归属下唯一）',
    `path`         VARCHAR(512) NOT NULL DEFAULT '' COMMENT '物化路径 /1/12/，便于子树查询与防环',
    `storage_kind` VARCHAR(16)  NOT NULL DEFAULT 'LOCAL'
        COMMENT 'LOCAL 落 sys_file / CLOUD 云盘（抽象位，见 docs/40 §8.3）',
    `cloud_ref`    VARCHAR(512) NULL COMMENT '云盘侧文件夹 id/path（storage_kind=CLOUD 时）',
    `created_by`   BIGINT       NULL,
    `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`   DATETIME(6)  NULL,
    `deleted_at`   DATETIME(6)  NULL,
    `alive`        TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_folder` (`tenant_id`, `project_id`, `parent_id`, `name`, `alive`),
    KEY `idx_pm_folder_path` (`tenant_id`, `path`(191)),
    KEY `idx_pm_folder_project` (`tenant_id`, `scope`, `project_id`, `parent_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '文档文件夹（企业级公共 / 项目专属）';

-- ---------------------------------------------------------------------------
-- 2. 文档索引：字节实体落既有 sys_file，本表只存索引与版本
-- ---------------------------------------------------------------------------
-- source 区分「外部上传」与「大模型创建」（用户关键词：所有文档（外部，大模型创建））：
--   UPLOAD 外部上传（经 POST /api/v1/files/upload 落 sys_file）
--   AI     大模型创建（由项目数字人生成，字节同样落 sys_file，source=AI 便于审计与统计）
CREATE TABLE `pm_document` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`   BIGINT       NOT NULL,
    `folder_id`   BIGINT       NOT NULL COMMENT '所属文件夹 pm_folder.id',
    `project_id`  BIGINT       NOT NULL DEFAULT 0 COMMENT '冗余项目维度（企业级文档为 0），便于按项目聚合',
    `name`        VARCHAR(256) NOT NULL,
    `file_id`     BIGINT       NULL COMMENT 'sys_file.id（字节实体）；AI 生成时同样落盘后再挂',
    `source`      VARCHAR(16)  NOT NULL DEFAULT 'UPLOAD' COMMENT 'UPLOAD 外部上传 / AI 大模型创建',
    `content_text` MEDIUMTEXT  NULL COMMENT 'AI 生成文档的正文（便于在线预览与检索；上传件为空）',
    `size_bytes`  BIGINT       NOT NULL DEFAULT 0,
    `version`     INT          NOT NULL DEFAULT 1 COMMENT '同名覆盖时自增',
    `tags`        VARCHAR(255) NULL,
    `uploaded_by` BIGINT       NULL COMMENT '上传人 / 生成人 user_id',
    `created_at`  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`  DATETIME(6)  NULL,
    `deleted_at`  DATETIME(6)  NULL,
    `alive`       TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    UNIQUE KEY `uk_pm_document` (`folder_id`, `name`, `version`, `alive`),
    KEY `idx_pm_document_project` (`tenant_id`, `project_id`),
    KEY `idx_pm_document_folder` (`folder_id`, `deleted_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '项目/企业文档索引（字节落 sys_file）';

-- ---------------------------------------------------------------------------
-- 3. 权限码（与本批次已实现端点同源；三段链：PermissionCatalog + 本表 + 前端 permissions.ts）
-- ---------------------------------------------------------------------------
INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:doc:view', '项目管理（文档查看）', 'APP', NULL, 105, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:doc:view');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:doc:manage', '项目管理（文档：建文件夹/上传/删除）', 'APP', NULL, 106, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:doc:manage');
