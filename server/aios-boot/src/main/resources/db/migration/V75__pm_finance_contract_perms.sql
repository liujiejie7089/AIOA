-- V75：项目管理模块（PM）批次 4 —— 补种经费 / 合同的权限码
--
-- 为什么单独一个版本：V73（建表）与 V74 都已在本机应用过（Flyway 已记录 checksum），
-- 不能回头改它们；且**权限码纪律**要求「只为已实现能力播种」——批次 4 的端点本次才落地，
-- 故权限码在本次迁移里补种（三段链：PermissionCatalog 常量 + 本表 + 前端角色清单）。
--
-- 依据：docs/40 §4 权限码表、docs/43 §4。

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:budget:manage', '项目管理（经费流水维护）', 'APP', NULL, 107, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:budget:manage');

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:contract:manage', '项目管理（合同与收付款）', 'APP', NULL, 108, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:contract:manage');
