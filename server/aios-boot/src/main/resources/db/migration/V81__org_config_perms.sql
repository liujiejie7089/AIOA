-- V81：机构作用域参数配置权限码（需求二 · 管理端菜单权限，docs/44 §2.5 B 案）
--
-- 为什么单独一个版本：端点（OrgConfigController）随本需求在 aioa-chat 落地，
-- 权限码在与端点同源的迁移里补种（三段链：PermissionCatalog 常量 + 本表 + 前端 permissions.ts）。
--
-- 依据：docs/44 §2.5 B 案；角色集复用 PermissionCatalog.ORG_ADMINS
--       = {ROLE_ADMIN, ROLE_TENANT_ADMIN, ROLE_ORG_ADMIN}。
-- 作用域由后端按调用者档位收紧：机构管理员钉死本机构，平台/租户管理员须选本租户机构。
--
-- 写法照抄 V76 的幂等写法：外层 SELECT 嵌套子查询规避 MySQL「同一语句不可改又查同表」限制。

INSERT INTO `sys_permission` (`tenant_id`, `perm_code`, `name`, `type`, `parent_id`, `sort`, `created_at`)
SELECT 0, 'org:config:manage', '机构参数配置', 'APP', NULL, 110, NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM (SELECT `perm_code` FROM `sys_permission`) t WHERE t.`perm_code` = 'org:config:manage');
