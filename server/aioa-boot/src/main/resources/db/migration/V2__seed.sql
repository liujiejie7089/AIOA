-- ============================================================================
-- AIOA M1 种子数据
-- admin 密码：Admin@123
--   BCrypt(强度 10) 哈希由 spring-security-crypto 6.3.4 的
--   BCrypt.hashpw("Admin@123", BCrypt.gensalt()) 生成，并已用
--   BCrypt.checkpw / BCryptPasswordEncoder.matches 双向校验通过；
--   启动时 StartupCheckRunner 会再打一条校验日志。
--   切勿把明文密码用于生产，首次登录后请立即改密。
-- ============================================================================

-- 租户（默认租户 0） --------------------------------------------------------
INSERT INTO sys_tenant (tenant_id, code, name, status)
VALUES (0, 'default', '默认租户', 'ENABLED');

-- 角色 ---------------------------------------------------------------------
INSERT INTO sys_role (tenant_id, role_code, name, type, data_scope)
VALUES (0, 'ROLE_ADMIN', '系统管理员', 'SYSTEM', 'ALL');
INSERT INTO sys_role (tenant_id, role_code, name, type, data_scope)
VALUES (0, 'ROLE_USER', '普通用户', 'BUSINESS', 'SELF');

-- 用户（admin / Admin@123） -------------------------------------------------
INSERT INTO sys_user (tenant_id, username, password_hash, nickname, status, auth_type, created_by)
VALUES (0, 'admin', '$2a$10$t1puZo3ANZlsQpD57aSOiOVDTev.FKR6hV.348.xUpmIU4bfOpfSm',
        '系统管理员', 'ENABLED', 'local', 0);

-- 权限样例 -----------------------------------------------------------------
INSERT INTO sys_permission (tenant_id, perm_code, name, type, sort)
VALUES (0, 'aioa:app:ticket', '票务系统', 'APP', 10),
       (0, 'aioa:app:dispatch', '统一调度', 'APP', 20),
       (0, 'aioa:chat:use', '对话助手', 'API', 30),
       (0, 'aioa:kb:view', '知识库查看', 'API', 40),
       (0, 'aioa:approval:*', '审批中心', 'APP', 50),
       (0, 'aioa:admin:*', '系统管理', 'ADMIN', 60);

-- admin → ROLE_ADMIN -------------------------------------------------------
INSERT INTO sys_user_role (tenant_id, user_id, role_id, created_by)
SELECT 0, u.id, r.id, 0
FROM sys_user u, sys_role r
WHERE u.username = 'admin' AND r.role_code = 'ROLE_ADMIN';

-- ROLE_ADMIN → 全部权限 ----------------------------------------------------
INSERT INTO sys_role_permission (tenant_id, role_id, perm_id, created_by)
SELECT 0, r.id, p.id, 0
FROM sys_role r, sys_permission p
WHERE r.role_code = 'ROLE_ADMIN';

-- 应用注册表 ---------------------------------------------------------------
INSERT INTO app_registry (tenant_id, app_code, name, entry_url, route_prefix, host_type, icon,
                          permission_code, enabled, props, sort)
VALUES (0, 'ticket', '票务系统', 'http://localhost:5174/', '/app/ticket', 'wujie', 'ticket',
        'aioa:app:ticket', true, '{}'::jsonb, 10),
       (0, 'dispatch', '统一调度', 'http://localhost:5175/', '/app/dispatch', 'iframe', 'schedule',
        'aioa:app:dispatch', true, '{}'::jsonb, 20);

-- Agent 定义 ---------------------------------------------------------------
INSERT INTO agent_definition (tenant_id, agent_code, name, type, domain, system_prompt, model_ref,
                              context_turns, max_steps, enabled, description)
VALUES (0, 'main', '主智能体', 'main', NULL, NULL, 'echo', 10, 8, true, '主智能体：负责意图识别与任务路由'),
       (0, 'ticket_agent', '票务助手', 'sub', 'ticket', NULL, 'echo', 10, 8, true, '票务领域子智能体'),
       (0, 'dispatch_agent', '调度助手', 'sub', 'dispatch', NULL, 'echo', 10, 8, true, '调度领域子智能体'),
       (0, 'kb_agent', '知识库助手', 'sub', 'kb', NULL, 'echo', 10, 8, true, '知识库问答子智能体');

-- 模型供应商（M1 回声模型） -------------------------------------------------
INSERT INTO model_provider (tenant_id, name, type, base_url, models, api_key_env, enabled)
VALUES (0, 'echo', 'local', '', '[]'::jsonb, '', true);
