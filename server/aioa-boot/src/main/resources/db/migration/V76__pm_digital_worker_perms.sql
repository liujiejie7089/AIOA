-- V76：项目管理模块（PM）—— 补种「数字人 / 上下文」权限码
--
-- 为什么单独一个版本：V74（建表）提到「有意不播种 pm:ai:manage —— 端点落地时随其实现在当次迁移里补」。
-- 数字人分配 + 上下文控制端点本次才实现，故权限码在本次迁移里补种
-- （三段链：PermissionCatalog 常量 + 本表 + 前端角色清单）。
--
-- 依据：docs/43 §5.4、docs/40 §4 权限码表。

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'pm:ai:manage', '项目管理（数字人与上下文）', 'APP', NULL, 109, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'pm:ai:manage');
