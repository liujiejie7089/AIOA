-- =====================================================================
-- V59 工具桥接真实化（aioa-bridge）
--
-- 背景：V1 建了 tool_system / tool_definition / tool_permission /
--       tool_invocation_log 四张表，但 aioa-bridge 只有实体与 Mapper，
--       InternalToolController#invoke 固定抛 501（「tool invoke 将在 M2 实现」）。
--       本次补齐：定义驱动的真实 HTTP 调用 + 角色权限闸门 + 幂等去重 +
--       需审批（HITL）挂起 + 调用日志。
--
-- 本迁移只做「结构缺口修补 + 演示种子」，不含业务数据搬迁。
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. 幂等键：tool_invocation_log 缺 idempotency_key，无法做去重
--    （tool_definition.idempotency_required 已存在但无人读取）。
--    MySQL 唯一索引允许多行 NULL，因此未传幂等键的调用不受影响。
-- ---------------------------------------------------------------------
ALTER TABLE `tool_invocation_log`
    ADD COLUMN `idempotency_key` VARCHAR(128) NULL COMMENT '调用方幂等键；idempotency_required=1 时必填',
    ADD COLUMN `result_body` MEDIUMTEXT NULL COMMENT '响应体（截断至 max_bytes），供幂等重放',
    ADD COLUMN `pending_args` JSON NULL COMMENT '挂起等待审批时的原始入参，审批通过后据此恢复执行';

ALTER TABLE `tool_invocation_log`
    ADD UNIQUE KEY `uk_tool_invocation_idem` (`tenant_id`, `tool_code`, `idempotency_key`);

-- ---------------------------------------------------------------------
-- 2. 工具定义唯一键从「全局 (tool_code, version)」改为「租户内唯一」。
--    原约束导致租户无法用同版本号覆盖全局工具（撞唯一键），
--    与「机构/租户专享优先于全局」的既有口径（见 docs/15 权限矩阵）不符。
--    表为空（V1 起从未播种），改约束无数据风险。
-- ---------------------------------------------------------------------
ALTER TABLE `tool_definition`
    DROP INDEX `uk_tool_definition`;

ALTER TABLE `tool_definition`
    ADD CONSTRAINT `uk_tool_definition_tenant` UNIQUE (`tenant_id`, `tool_code`, `version`);

-- =====================================================================
-- 3. 演示/验收种子：把「平台自带 agent 服务」注册为一个可调用系统，
--    并登记 4 个探针工具，分别覆盖
--      agent_health            —— 直通（默认放行，无权限行）
--      agent_health_approval   —— 需审批（HITL 挂起）
--      agent_health_idem       —— 需幂等键（去重）
--      agent_health_restricted —— 角色白名单（ROLE_ADMIN 放行 / ROLE_MEMBER 拒绝）
--
--    base_url 指向同机 agent 服务（:8000），与 start-all.sh 的编排一致；
--    生产部署请通过「工具注册」页改 base_url，无需改代码。
-- =====================================================================
INSERT INTO `tool_system`
(`tenant_id`, `system_code`, `name`, `base_url`, `health_url`, `auth_type`, `auth_ref`,
 `timeout_ms`, `circuit_breaker`, `status`, `created_by`)
VALUES (0, 'aioa_agent', 'AIOA 智能体服务', 'http://127.0.0.1:8000', '/health', NULL, NULL,
        5000, NULL, 'ACTIVE', 0);

INSERT INTO `tool_definition`
(`tenant_id`, `tool_code`, `version`, `name`, `description`, `domain`, `system_code`,
 `endpoint`, `http_method`, `input_schema`, `output_schema`, `risk_level`,
 `requires_approval`, `idempotency_required`, `timeout_ms`, `retry_policy`, `rate_limit`,
 `auth_type`, `auth_ref`, `param_mapping`, `response_jmespath`, `max_bytes`, `status`, `owner`, `created_by`)
VALUES
(0, 'agent_health', '1.0.0', '智能体健康探针',
 '探活 AIOA 智能体服务（GET /health），返回 {"status":"UP"}。用于验证「定义驱动」的工具桥接真实 HTTP 调用链路。',
 'platform', 'aioa_agent', '/health', 'GET',
 '{"type":"object","properties":{},"required":[]}',
 '{"type":"object","properties":{"status":{"type":"string"}}}',
 'LOW', 0, 0, 3000, NULL, NULL, NULL, NULL, NULL, 'status', 4096, 'ACTIVE', 'platform', 0),

(0, 'agent_health_approval', '1.0.0', '需审批的智能体健康探针',
 '与 agent_health 同目标，但 requires_approval=1：调用不直接执行，先挂起并生成审批单，终审通过后由回调恢复执行。',
 'platform', 'aioa_agent', '/health', 'GET',
 '{"type":"object","properties":{},"required":[]}',
 '{"type":"object","properties":{"status":{"type":"string"}}}',
 'HIGH', 1, 0, 3000, NULL, NULL, NULL, NULL, NULL, 'status', 4096, 'ACTIVE', 'platform', 0),

(0, 'agent_health_idem', '1.0.0', '幂等智能体健康探针',
 '与 agent_health 同目标，但 idempotency_required=1：调用方必须携带 idempotencyKey，同键重复调用直接回放首次结果。',
 'platform', 'aioa_agent', '/health', 'GET',
 '{"type":"object","properties":{"idempotencyKey":{"type":"string"}},"required":["idempotencyKey"]}',
 '{"type":"object","properties":{"status":{"type":"string"}}}',
 'LOW', 0, 1, 3000, NULL, NULL, NULL, NULL, NULL, 'status', 4096, 'ACTIVE', 'platform', 0),

(0, 'agent_health_restricted', '1.0.0', '受限智能体健康探针',
 '与 agent_health 同目标，但 tool_permission 配了 ALLOW(ROLE_ADMIN) + DENY(ROLE_MEMBER)：存在 ALLOW 行即进入白名单模式。',
 'platform', 'aioa_agent', '/health', 'GET',
 '{"type":"object","properties":{},"required":[]}',
 '{"type":"object","properties":{"status":{"type":"string"}}}',
 'MEDIUM', 0, 0, 3000, NULL, NULL, NULL, NULL, NULL, 'status', 4096, 'ACTIVE', 'platform', 0);

-- 注：uk_tool_permission 是全局 (tool_code, role_code) 唯一，故权限行以 tenant_id=0 表达「平台级默认」。
--     租户若要覆盖，需另建行并调整该唯一键（当前一期不需，留待有真实诉求时再迁移）。
INSERT INTO `tool_permission` (`tenant_id`, `tool_code`, `role_code`, `effect`, `created_by`)
VALUES (0, 'agent_health_restricted', 'ROLE_ADMIN', 'ALLOW', 0),
       (0, 'agent_health_restricted', 'ROLE_MEMBER', 'DENY', 0);
