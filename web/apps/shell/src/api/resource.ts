import { http, unwrap } from './index'

/* ============ 审批工作流（aioa-resource ApprovalController） ============ */

export interface ApprovalOrder {
  id: number
  bizType: string
  title: string
  content: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | string
  approver: string
  decisionNote: string
  decidedAt: string
  createdAt: string
  mine: boolean
}

/** scope=mine 我发起的；scope=todo 待我审批（仅租户管理员，后端校验 403） */
export function listApprovals(scope: 'mine' | 'todo'): Promise<ApprovalOrder[]> {
  return http.get('/approvals', { params: { scope } }).then((r) => unwrap<ApprovalOrder[]>(r))
}

export function decideApproval(id: number, decision: 'APPROVE' | 'REJECT', note?: string): Promise<ApprovalOrder> {
  return http.post(`/approvals/${id}/decision`, { decision, note }).then((r) => unwrap<ApprovalOrder>(r))
}

/* ============ 知识库（aioa-resource KbController） ============ */

export interface KbDoc {
  id: number
  name: string
  icon: string
  /** ok 已入库 / wait 解析中 / failed 失败 */
  state: string
  sizeBytes: number
  ownerUserId: number
  createdAt: string
}

/** 不传 scope=我的资料；scope=tenant=租户全部（仅租户管理员） */
export function listKbDocs(scope?: 'tenant'): Promise<KbDoc[]> {
  return http.get('/kb/documents', { params: scope ? { scope } : {} }).then((r) => unwrap<KbDoc[]>(r))
}

export function registerKbDoc(name: string, icon?: string, sizeBytes?: number): Promise<KbDoc> {
  return http.post('/kb/documents', { name, icon, sizeBytes }).then((r) => unwrap<KbDoc>(r))
}

/* ============ 系统管理（aioa-admin AdminController，仅租户管理员） ============ */

export interface SysUser {
  id: number
  username: string
  nickname: string
  status: string
  tenantId: number
  createdAt?: string
  roles?: string[]
  [key: string]: unknown
}

export interface SysRole {
  id: number
  roleCode: string
  roleName: string
  [key: string]: unknown
}

export interface SysPermission {
  id: number
  permCode: string
  permName: string
  [key: string]: unknown
}

export interface PageResult<T> {
  records: T[]
  total: number
  current: number
  size: number
}

export function listUsers(page = 1, size = 20): Promise<PageResult<SysUser>> {
  return http.get('/admin/users', { params: { page, size } }).then((r) => unwrap<PageResult<SysUser>>(r))
}

export function listRoles(): Promise<SysRole[]> {
  return http.get('/admin/roles').then((r) => unwrap<SysRole[]>(r))
}

export function listPermissions(): Promise<SysPermission[]> {
  return http.get('/admin/permissions').then((r) => unwrap<SysPermission[]>(r))
}

export function assignUserRoles(userId: number, roleIds: number[]): Promise<{ userId: number; roles: string[] }> {
  return http.put(`/admin/users/${userId}/roles`, { roleIds }).then((r) => unwrap<{ userId: number; roles: string[] }>(r))
}

export function changeUserStatus(userId: number, status: 'ENABLED' | 'DISABLED'): Promise<{ userId: number; status: string }> {
  return http.put(`/admin/users/${userId}/status`, { status }).then((r) => unwrap<{ userId: number; status: string }>(r))
}

// ---------- 功能管理（应用/模块） ----------

export interface AppItem {
  id: number
  appCode: string
  name: string
  entryUrl: string
  hostType: string
  enabled: boolean
  visibleScope: string
  sort: number
  [key: string]: unknown
}

export function listAllApps(): Promise<AppItem[]> {
  return http.get('/admin/apps').then((r) => unwrap<AppItem[]>(r))
}

export function updateApp(
  code: string,
  body: { enabled?: boolean; visibleScope?: 'ALL' | 'ADMIN'; name?: string; sort?: number },
): Promise<AppItem> {
  return http.put(`/admin/apps/${code}`, body).then((r) => unwrap<AppItem>(r))
}

// ---------- 模型管理 ----------

export interface ModelItem {
  id: number
  providerKey: string
  name: string
  baseUrl: string
  modelName: string
  apiKeyEnv: string
  enabled: boolean
  isDefault: boolean
  sort: number
  [key: string]: unknown
}

export function listModels(): Promise<ModelItem[]> {
  return http.get('/admin/models').then((r) => unwrap<ModelItem[]>(r))
}

export function saveModel(body: Partial<ModelItem>): Promise<ModelItem> {
  if (body.id) {
    return http.put(`/admin/models/${body.providerKey}`, body).then((r) => unwrap<ModelItem>(r))
  }
  return http.post('/admin/models', body).then((r) => unwrap<ModelItem>(r))
}

export function deleteModel(key: string): Promise<unknown> {
  return http.delete(`/admin/models/${key}`).then((r) => unwrap(r))
}

export function setDefaultModel(key: string): Promise<unknown> {
  return http.put(`/admin/models/${key}/default`, {}).then((r) => unwrap(r))
}

export interface QuotaView {
  quota: number
  used: number
  free: number
  left: number
  percent: number
  exhausted: boolean
}

export function myQuota(): Promise<QuotaView> {
  return http.get('/quota').then((r) => unwrap<QuotaView>(r))
}

export interface HomeStats {
  todoApprovals: number
  myApprovals: number
  aiConversations: number
  aiRuns: number
}

export function homeStats(): Promise<HomeStats> {
  return http.get('/stats/home').then((r) => unwrap<HomeStats>(r))
}

/* ============ 经营数据看板（V1.2 · 管理端维护，用户端 /kpi/board 只读） ============ */

export interface KpiMetric {
  id: number
  period: string
  label: string
  valueText: string
  deltaText: string
  up: number
  compareLabel: string
  sortNo: number
}

export function adminListKpiMetrics(period: string): Promise<KpiMetric[]> {
  return http.get('/admin/kpi/metrics', { params: { period } }).then((r) => unwrap<KpiMetric[]>(r))
}
export function adminCreateKpiMetric(body: Partial<KpiMetric>): Promise<KpiMetric> {
  return http.post('/admin/kpi/metrics', body).then((r) => unwrap<KpiMetric>(r))
}
export function adminUpdateKpiMetric(id: number, body: Partial<KpiMetric>): Promise<KpiMetric> {
  return http.put(`/admin/kpi/metrics/${id}`, body).then((r) => unwrap<KpiMetric>(r))
}
export function adminDeleteKpiMetric(id: number): Promise<boolean> {
  return http.delete(`/admin/kpi/metrics/${id}`).then((r) => unwrap<boolean>(r))
}

export interface KpiTrendPoint {
  id: number
  period: string
  pointLabel: string
  numValue: number
  hot: number
  sortNo: number
}

export function adminListKpiTrend(period: string): Promise<KpiTrendPoint[]> {
  return http.get('/admin/kpi/trend', { params: { period } }).then((r) => unwrap<KpiTrendPoint[]>(r))
}
export function adminCreateKpiTrend(body: Partial<KpiTrendPoint>): Promise<KpiTrendPoint> {
  return http.post('/admin/kpi/trend', body).then((r) => unwrap<KpiTrendPoint>(r))
}
export function adminUpdateKpiTrend(id: number, body: Partial<KpiTrendPoint>): Promise<KpiTrendPoint> {
  return http.put(`/admin/kpi/trend/${id}`, body).then((r) => unwrap<KpiTrendPoint>(r))
}
export function adminDeleteKpiTrend(id: number): Promise<boolean> {
  return http.delete(`/admin/kpi/trend/${id}`).then((r) => unwrap<boolean>(r))
}

export interface KpiInsight {
  id?: number
  period: string
  content: string
  sourceText: string
}

export function adminGetKpiInsight(period: string): Promise<KpiInsight> {
  return http.get('/admin/kpi/insight', { params: { period } }).then((r) => unwrap<KpiInsight>(r))
}
export function adminUpsertKpiInsight(period: string, body: Partial<KpiInsight>): Promise<KpiInsight> {
  return http.put('/admin/kpi/insight', body, { params: { period } }).then((r) => unwrap<KpiInsight>(r))
}

/* ============ 数字员工（V1.2 · 管理端维护） ============ */

export interface AgentWorker {
  id: number
  name: string
  icon: string
  description: string
  status: string
  lastOutput: string
  scheduleText: string
  enabled: number
}

export function adminListWorkers(): Promise<AgentWorker[]> {
  return http.get('/admin/workers').then((r) => unwrap<AgentWorker[]>(r))
}
export function adminCreateWorker(body: Partial<AgentWorker>): Promise<AgentWorker> {
  return http.post('/admin/workers', body).then((r) => unwrap<AgentWorker>(r))
}
export function adminUpdateWorker(id: number, body: Partial<AgentWorker>): Promise<AgentWorker> {
  return http.put(`/admin/workers/${id}`, body).then((r) => unwrap<AgentWorker>(r))
}
export function adminToggleWorker(id: number): Promise<AgentWorker> {
  return http.post(`/admin/workers/${id}/toggle`).then((r) => unwrap<AgentWorker>(r))
}
export function adminDeleteWorker(id: number): Promise<boolean> {
  return http.delete(`/admin/workers/${id}`).then((r) => unwrap<boolean>(r))
}

/* ============ 成果沉淀（V1.2 · 管理端查看） ============ */

export interface UserResultItem {
  id: number
  userId: number
  title: string
  icon: string
  meta: string
  body: string
  status: string
  createdAt: string
}

export function adminListResults(): Promise<UserResultItem[]> {
  return http.get('/admin/results').then((r) => unwrap<UserResultItem[]>(r))
}
export function adminDeleteResult(id: number): Promise<boolean> {
  return http.delete(`/admin/results/${id}`).then((r) => unwrap<boolean>(r))
}
