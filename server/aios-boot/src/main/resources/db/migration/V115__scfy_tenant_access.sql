-- ============================================================================
-- V115 非遗（scfy）能力按租户接入（docs/92 阶段 1）
--
-- 背景：V113 把 scfy 作为「平台级统一接入」——connector_def / mcp_server 都是
-- tenant_id=0，config_keys='[]' 使 ConnectorCatalogService.configReadyInternal()
-- 恒 ready=true（L199-201），hub 侧零鉴权。结果是「平台 trust 一次，全员可用」。
--
-- 本迁移做三件事，全部可回滚：
--   1) connector_def 增加「接入模式」列：数据驱动地声明哪些连接器需要租户先接入，
--      而不是在 Java 里硬编码 code 集合 —— 以后接入其它系统只需插一行 def，
--      不必再改判权代码（对应最初「再接其它系统不必大规模改造」的诉求）。
--   2) 新建通用 connector_tenant_access（tenant_id + connector_code 唯一键）。
--      与 connector_tenant_config 正交：那张表存「租户级应用凭据（密文）」，
--      这张表存「租户是否授权接入 + 机构范围 + 租户级数据源配置」，
--      语义不同，不构成两套开关源（scfy 无凭据，走本表而不碰 config 表）。
--   3) 存量平移：把「当前全系统已接入」等价改写为「每个现存租户都已启用」，
--      现网零中断；此后**新建租户默认无行 = 未接入**，必须管理员显式启用。
--
-- 判据落点（阶段 2/3 实装）：
--   ConnectorCatalogService.configReadyInternal() → TENANT 时查本表 enabled
--   McpRegistryService.usableForAgent()/manifest() → TENANT 时按 user 再判机构/权限
--   mcp-hub scfy server → 每次 tools/call 回调 Java /api/v1/mcp/access/{code}/check
--
-- 回滚：把 scfy 的 access_mode 改回 'OPEN' 即恢复平台级统一接入（本表保留不删）。
-- ============================================================================

-- 1) 接入模式：OPEN = 平台统一接入（历史行为，全员可用）；
--    TENANT = 仅完成接入配置并启用的租户可用（本改造目标）。
ALTER TABLE connector_def
  ADD COLUMN access_mode VARCHAR(32) NOT NULL DEFAULT 'OPEN'
  COMMENT '接入模式：OPEN=平台统一接入（全员可用）；TENANT=需租户完成接入配置后该租户才可用'
  AFTER auth_mode;

UPDATE connector_def
   SET access_mode = 'TENANT',
       updated_at  = NOW(6)
 WHERE tenant_id = 0
   AND code = 'scfy'
   AND access_mode <> 'TENANT';

-- 2) 租户接入授权表（通用，非 scfy 专属）。
--    scope_institutions：JSON 数组文本，空 / '[]' = 不限制机构（全租户可用）；
--      多机构兼职用户按 AuthUser.institutionId（primary 机构）判定，见 docs/92 D3①。
--    config_json：租户级接入配置（如自建 16060 的 baseUrl 覆盖），空 = 用平台默认。
--    enabled=0 且已有配置行 ⇒ 状态「已配置待启用 / 已停用」；无行 ⇒「未接入」。
CREATE TABLE connector_tenant_access (
  id                  BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id           BIGINT NOT NULL DEFAULT 0,
  connector_code      VARCHAR(64) NOT NULL,
  enabled             TINYINT(1) NOT NULL DEFAULT 0,
  scope_institutions  TEXT COMMENT '允许调用的机构 ID 白名单（JSON 数组文本，空/[] = 全租户）',
  config_json         TEXT COMMENT '租户级接入配置（JSON 文本，如 baseUrl 覆盖；空 = 平台默认）',
  enabled_by          BIGINT,
  enabled_at          DATETIME(6),
  created_by          BIGINT,
  updated_by          BIGINT,
  created_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at          DATETIME(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_tenant_access (tenant_id, connector_code),
  KEY idx_tenant_access_code (connector_code, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3) 存量平移。表刚建、必为空，故不做 NOT EXISTS 子查询（MySQL 1093：
--    INSERT ... SELECT 的目标表不能同时出现在子查询 FROM 里），用 DISTINCT 防 sys_tenant 重号。
--    只平移未软删且 ENABLED 的租户；禁用租户不自动获得接入。
INSERT INTO connector_tenant_access
  (tenant_id, connector_code, enabled, enabled_by, enabled_at, created_by)
SELECT DISTINCT t.tenant_id, 'scfy', 1, 0, NOW(6), 0
  FROM sys_tenant t
 WHERE t.deleted_at IS NULL
   AND t.status = 'ENABLED';
