-- ============================================================================
-- AIOA 多角色种子：新增「普通用户」账号，用于真实登录 / 角色切换演示
--   zhangsan / User@123  （ROLE_USER 普通用户）
--   BCrypt(强度 10) 哈希，前缀 $2a$ 与 admin 种子保持一致，确保 Spring 校验通过
-- ============================================================================

-- 普通用户 zhangsan ----------------------------------------------------------
INSERT INTO sys_user (tenant_id, username, password_hash, nickname, status, auth_type, created_by)
VALUES (0, 'zhangsan',
        '$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS',
        '张三', 'ENABLED', 'local', 0);

-- zhangsan → ROLE_USER -------------------------------------------------------
INSERT INTO sys_user_role (tenant_id, user_id, role_id, created_by)
SELECT 0, u.id, r.id, 0
FROM sys_user u, sys_role r
WHERE u.username = 'zhangsan' AND r.role_code = 'ROLE_USER';

-- 给 zhangsan 独立的词元额度（与共享额度 user_id=0 并存，BillingService.scopeUsers 会合并查询）
INSERT INTO tenant_quota (tenant_id, user_id, quota_tokens, used_tokens, free_tokens)
SELECT 0, u.id, 100000, 0, 2000
FROM sys_user u
WHERE u.username = 'zhangsan';
