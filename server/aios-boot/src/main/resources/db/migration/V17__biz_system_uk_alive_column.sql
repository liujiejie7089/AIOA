-- V17 修复 biz_system 防重：MySQL 唯一索引对 NULL 不去重，
-- V16 的 (tenant_id, system_code, deleted_at) 无法阻止两条未删除（deleted_at=NULL）的同编码记录。
-- 方案：虚拟列 alive = IF(deleted_at IS NULL, 1, NULL)：
--   未删除行 alive=1（参与唯一约束，防重）；
--   已删除行 alive=NULL（不参与，同编码可重新注册）。

ALTER TABLE `biz_system`
    DROP INDEX `uk_biz_system_code`,
    ADD COLUMN `alive` TINYINT GENERATED ALWAYS AS (IF(`deleted_at` IS NULL, 1, NULL)) VIRTUAL,
    ADD UNIQUE KEY `uk_biz_system_code` (`tenant_id`, `system_code`, `alive`);
