-- =============================================================================
-- V66 租户层级与登录域名（docs/38 批次 A）
--
-- 规格（用户）：租户拥有独立域名；平台管理员为租户分配登录域名；
--              租户管理员可以在本租户下建子租户并为其分配管理员。
--
-- 现状：sys_tenant 只有 id/tenant_id/code/name/status ⇒ 无域名、无层级。
--
-- 层级口径（docs/38 §3 默认假设 1）：平台 → 顶层租户(level=1) → 子租户(level=2)，
-- 只允许一层；子租户不能再建子租户（拒绝时给明确文案，不做静默降级）。
--
-- 兼容性：全部列带默认值 ⇒ 既有 3 行自动成为 level=1 / parent_id=0，
--        不需要单独回填；domain 允许 NULL（历史租户不强制补）。
-- =============================================================================

ALTER TABLE sys_tenant
    ADD COLUMN parent_id BIGINT       NOT NULL DEFAULT 0 COMMENT '上级租户 id；顶层租户为 0（V66）',
    ADD COLUMN level     TINYINT      NOT NULL DEFAULT 1 COMMENT '层级：1=顶层租户，2=子租户（V66）',
    ADD COLUMN domain    VARCHAR(128) NULL COMMENT '平台分配的登录域名，如 dsj.aioa.local（V66）';

-- 域名唯一（MySQL 唯一索引允许多个 NULL，因此未分配域名的租户不受影响）
ALTER TABLE sys_tenant
    ADD UNIQUE KEY uk_tenant_domain (domain);

-- 按层级/父租户检索（子租户列表、同级去重）
ALTER TABLE sys_tenant
    ADD KEY idx_tenant_parent (parent_id, deleted_at);

-- 演示数据：给既有两个业务租户分配域名，使列表页有真实可读内容。
-- 用 code 定位而不是写死 id，避免与其它环境的自增序列耦合。
UPDATE sys_tenant SET domain = 'dsj.aioa.local' WHERE code = 'DSJ-DEMO' AND domain IS NULL;
UPDATE sys_tenant SET domain = 'wjj.aioa.local' WHERE code = 'WJJ-DEMO' AND domain IS NULL;
