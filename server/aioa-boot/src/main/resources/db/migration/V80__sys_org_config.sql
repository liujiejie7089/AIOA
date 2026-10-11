-- V80：机构作用域系统参数（需求二 · 管理端菜单权限，docs/44 §2.5 B 案）
--
-- 为什么单独一个表（而不是复用 sys_config 加 scope 列）：
--   sys_config 的全部读写都按 tenant_id 过滤，且 AdminConfigController.requireAdmin()
--   硬拒机构管理员（ROLE_ORG_ADMIN）。若「只放开菜单」，机构管理员会改到**全租户**参数 ⇒ 越权。
--   B 案据此新建一个**机构作用域**配置面，与 sys_config 完全隔离：
--     · 不动 sys_config 的表结构与既有读写（零回归）；
--     · 机构管理员只能 upsert 本机构（institution_id 由后端从登录态钉死）的覆盖值；
--     · 读取按「机构覆盖值 → 租户值 → 平台默认」逐级 merge，删除覆盖值即恢复继承。
--   表结构 / 字符集 / 注释风格照抄 V72；唯一键口径照抄 V18（tenant_id, 业务键）。
--
-- ★ 三条既有约定照抄（见 V71/V72 顶部）：tenant_id 收窄；utf8mb4/InnoDB/DATETIME(6)；
--   本表为覆盖值存储，**无软删**（删除覆盖值即恢复继承，物理删更直观，且唯一键不残留死行）。

CREATE TABLE `sys_org_config` (
    `id`             BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`      BIGINT       NOT NULL COMMENT '租户 ID（一律取登录态，不接受前端入参，防改包提权）',
    `institution_id` BIGINT       NOT NULL COMMENT '机构 ID（机构管理员被钉死为本机构；平台/租户管理员须属本租户）',
    `config_key`     VARCHAR(64)  NOT NULL COMMENT '参数键（与该租户 sys_config 的键集同源）',
    `config_name`    VARCHAR(128) NOT NULL COMMENT '参数名称（中文，复制自 sys_config，便于本表自描述）',
    `group_code`     VARCHAR(32)  NOT NULL DEFAULT 'COMMON' COMMENT 'CONVERSATION / QUOTA / KNOWLEDGE / SECURITY / COMMON / AUDIT',
    `value_type`     VARCHAR(16)  NOT NULL DEFAULT 'STRING' COMMENT 'INT / DECIMAL / BOOL / STRING / JSON',
    `config_value`   VARCHAR(512) NOT NULL COMMENT '机构覆盖值（统一以字符串存储）',
    `created_by`     BIGINT       NULL COMMENT '创建人 user_id',
    `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`     DATETIME(6)  NULL,
    UNIQUE KEY `uk_sys_org_config` (`tenant_id`, `institution_id`, `config_key`),
    KEY `idx_sys_org_config_inst` (`tenant_id`, `institution_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '机构作用域系统参数覆盖值（与 sys_config 隔离，机构管理员可配本机构）';
