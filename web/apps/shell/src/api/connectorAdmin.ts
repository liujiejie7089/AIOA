import { http, unwrap } from './index'

// ---------------------------------------------------------------------------
// 连接器「按租户接入」（docs/92）。
// 本组 API 管理的是「该租户是否授权接入 + 机构范围 + 租户级数据源配置」，
// 四态由后端 connector_tenant_access 计算，前端只渲染、不自行推断。
// 旧「租户级凭据配置」（/admin/connector-configs）的页面入口已下线：凭据型
// 连接器的接入统一走本页 + hub 侧授权，前端不再维护第二套配置表单。
// ---------------------------------------------------------------------------

export type ConnectorAccessStatus =
  | 'NOT_CONNECTED'
  | 'CONFIGURED_DISABLED'
  | 'ENABLED'
  | 'DISABLED'

export interface ConnectorAccessView {
  code: string
  requiresTenantAccess: boolean
  status: ConnectorAccessStatus
  enabled: boolean
  scopeInstitutions: number[]
  config: {
    baseUrl?: string
    allowedUserIds?: number[]
    [key: string]: unknown
  }
  enabledAt: string | null
  enabledBy: number | null
}

export interface ConnectorAccessConfigPut {
  /** null = 不修改；[] = 清空白名单（全租户可用） */
  scopeInstitutions?: number[] | null
  /** null = 不修改；{} = 清空租户级配置 */
  config?: Record<string, unknown> | null
}

export function listConnectorAccess() {
  return http.get('/connector-access').then((r) => unwrap<ConnectorAccessView[]>(r))
}

export function getConnectorAccess(code: string) {
  return http.get(`/connector-access/${code}`).then((r) => unwrap<ConnectorAccessView>(r))
}

export function enableConnectorAccess(code: string) {
  return http.post(`/admin/connector-access/${code}/enable`).then((r) => unwrap<ConnectorAccessView>(r))
}

export function disableConnectorAccess(code: string) {
  return http.post(`/admin/connector-access/${code}/disable`).then((r) => unwrap<ConnectorAccessView>(r))
}

export function configureConnectorAccess(code: string, body: ConnectorAccessConfigPut) {
  return http.put(`/admin/connector-access/${code}/config`, body)
    .then((r) => unwrap<ConnectorAccessView>(r))
}

/** GET /connectors：连接器目录（真实名称/分组/摘要/accessMode），接入页用它把 code 显示成中文名。 */
export interface ConnectorCatalogEntry {
  code: string
  name: string
  group?: string | null
  summary?: string | null
  accessMode?: string | null
}

export function listConnectorCatalog(): Promise<ConnectorCatalogEntry[]> {
  return http.get('/connectors').then((r) => unwrap<ConnectorCatalogEntry[]>(r))
}
