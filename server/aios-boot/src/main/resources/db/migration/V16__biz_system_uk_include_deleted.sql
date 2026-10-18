-- V16 修复 biz_system 唯一键与逻辑删除的冲突：
-- 逻辑删除（deleted_at 置时间戳）后同编码无法重新注册（uk 不含 deleted_at 仍冲突）。
-- 将 deleted_at 纳入唯一键：未删除行 deleted_at=NULL（MySQL 唯一索引允许多个 NULL，互不冲突），
-- 已删除行带时间戳，不再占用编码，可重新注册。

ALTER TABLE `biz_system`
    DROP INDEX `uk_biz_system_code`,
    ADD UNIQUE KEY `uk_biz_system_code` (`tenant_id`, `system_code`, `deleted_at`);
