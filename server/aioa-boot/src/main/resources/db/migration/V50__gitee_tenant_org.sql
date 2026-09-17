-- ===========================================================================
-- V50 · 每个租户各自的 Gitee 组织（多企业各自独立 Gitee 组织）
-- ===========================================================================
-- 需求：「支持不同企业创建不同的 gitee」—— 此前 aioa.gitee.org 是**全局单一值**，
--   所有租户的仓库都落在同一个共享 Gitee 组织下。现在隔离边界定为**租户**
--   （tenant_id）：同一租户内不同部门仍复用仓库命名前缀（dept<id>-）做部门隔离，
--   但不同企业（租户）可以各自拥有独立的 Gitee 组织。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V49，故本文件为 V50。
--
-- 设计要点：
--   · 隔离边界 = 租户，不是机构：机构级多组织不在本期范围。
--   · OAuth 应用仍是**平台级**（clientId/secret/redirectUri 不变），因此不改
--     GiteeClient 的 OAuth 方法，也不改 GiteeAccountService。
--   · 租户级配置是「覆盖 + 回落」：没配置的租户（或 org 留空）回落到全局
--     aioa.gitee.org，从而不破坏任何既有项目、演示租户与现有 E2E 套件。
--   · 这是**每租户单行**表（singleton-per-tenant），不需要软删；清配置 = 删行回落默认。
--   · 刻意**不**给 tenant 9 播种任何行：这正是用来验证「回落路径仍工作」的基线。
--
-- 安全：org_name 会被拼进 Gitee 请求路径（/orgs/{org}/repos 等），因此 save 时
--   由 GiteeTenantConfigService 用保守正则（字母/数字/-/_/.，长度≤128）强校验，
--   非法值一律拒绝，避免路径注入。
-- ===========================================================================

CREATE TABLE IF NOT EXISTS `gitee_tenant_config` (
    `id`         BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`  BIGINT       NOT NULL COMMENT '所属租户（隔离边界）',
    `org_name`   VARCHAR(128) NOT NULL COMMENT '该租户各自的 Gitee 组织 login（覆盖全局默认 aioa.gitee.org）',
    `enabled`    TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=该租户 Gitee 仓库联动启用（覆盖平台开关）；0=关闭',
    `note`       VARCHAR(255) NULL COMMENT '备注（如「XX 企业自建组织」）',
    `created_by` BIGINT       NULL COMMENT '创建/最后配置人（sys_user.id）',
    `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_by` BIGINT       NULL,
    `updated_at` DATETIME(6)  NULL,
    UNIQUE KEY `uk_gitee_tenant_config_tenant` (`tenant_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '每租户各自的 Gitee 组织配置（覆盖全局默认）';
