import { http, unwrap } from './index'

/**
 * 租户级连接器配置管理（管理员）。
 *
 * <p>后端契约：`/api/v1/admin/connector-configs/{code}`
 * （cn.aios.resource.connector.controller.ConnectorTenantConfigController）。
 * GET/PUT 返回**掩码视图**，绝不回明文密钥；PUT 提交掩码值或空串 = 保留旧值。</p>
 */

/** GET 返回体（掩码视图）。corpSecret 恒为固定占位，是否已配看 corpSecretSet。 */
export interface ConnectorTenantConfigView {
  code: string
  corpId: string
  agentId: string
  corpSecretSet: boolean
  corpSecret: string
  enabled: boolean
  configured: boolean
  configReady: boolean
  configHint: string | null
}

/** PUT 请求体。values 里留空/保持掩码 = 保留旧值。 */
export interface ConnectorTenantConfigPut {
  values: { corpId?: string; agentId?: string; corpSecret?: string }
  enabled?: boolean
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
