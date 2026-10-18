-- V12: 应用（功能模块）可见范围：ALL 所有人 / ADMIN 仅租户管理员
ALTER TABLE app_registry
    ADD COLUMN visible_scope VARCHAR(16) NOT NULL DEFAULT 'ALL' COMMENT '可见范围：ALL/ADMIN' AFTER enabled;
