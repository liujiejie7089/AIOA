import { http, unwrap } from './index'

/**
 * 租户级连接器配置管理（管理员）。
 *
 * <p>后端契约：`/api/v1/admin/connector-configs`（cn.aios.resource.connector.controller.ConnectorTenantConfigController）。
 * 字段集合由 `connector_def.config_keys` 决定（schema 驱动），前端不再写死 corpId/agentId/corpSecret；
 * GET/PUT 返回**掩码视图**，绝不回明文密钥；PUT 提交掩码值或空串 = 保留旧值。</p>
 */

/** GET /admin/connector-configs：可选连接器清单。 */
export interface ConnectorConfigItem {
  code: string
  name: string
  authMode: string
  configKeys: string[]
  enabled: boolean
  configured: boolean
}

/** GET /admin/connector-configs/{code}：掩码视图（values 里敏感键恒为空串，是否已配看 `${key}Set`）。 */
export interface ConnectorTenantConfigView {
  code: string
  configKeys: string[]
  values: Record<string, string | boolean>
  enabled: boolean
  configured: boolean
  configReady: boolean
  configHint: string | null
  /** hub = 权威来源（凭据已进运行时）；legacy = 运行时不可达，仅回显影子记录 */
  source?: 'hub' | 'legacy'
  hubAvailable?: boolean
  // 兼容旧字段（企业微信页历史契约）
  corpId?: string
  agentId?: string
  corpSecret?: string
  corpSecretSet?: boolean
}

/** PUT 请求体：values 里留空/保持掩码 = 保留旧值。 */
export interface ConnectorTenantConfigPut {
  values: Record<string, string>
  enabled?: boolean
}

export function listConnectorTenantConfigs() {
  return http.get('/admin/connector-configs').then((r) => unwrap<ConnectorConfigItem[]>(r))
}

export function getConnectorTenantConfig(code: string) {
  return http.get(`/admin/connector-configs/${code}`).then((r) => unwrap<ConnectorTenantConfigView>(r))
}

export function putConnectorTenantConfig(code: string, body: ConnectorTenantConfigPut) {
  return http.put(`/admin/connector-configs/${code}`, body).then((r) => unwrap<ConnectorTenantConfigView>(r))
}

export function deleteConnectorTenantConfig(code: string) {
  return http.delete(`/admin/connector-configs/${code}`).then((r) => unwrap<{ status: string }>(r))
}
