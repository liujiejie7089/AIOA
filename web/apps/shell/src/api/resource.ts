import { http, unwrap } from './index'

/* ============ 审批工作流（aioa-resource ApprovalController） ============ */

export interface ApprovalOrder {
  id: number
  bizType: string
  title: string
  content: string
  /** 结构化表单 JSON（请假：{leaveType,start,end,reason} 等） */
  formData?: string | null
  /** 附件 JSON 数组 [{name,url}] */
  attachment?: string | null
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | string
  /** 发起人姓名（提交时快照） */
  applicantName: string
  /** 发起人 id */
  userId: number
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

/* ---------- 通用文件上传（请假证明等附件） ---------- */

export interface UploadedFile {
  id: number
  name: string
  url: string
  size: number
}

/** 上传任意文件，返回可访问的 url（由后端 /api/v1/files/{id} 提供） */
export function uploadFile(file: File, onProgress?: (percent: number) => void): Promise<UploadedFile> {
  const fd = new FormData()
  fd.append('file', file)
  return http
    .post('/files/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
    .then((r) => unwrap<UploadedFile>(r))
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
  /** PERSONAL 个人可见 / TENANT 租户共享 */
  scope?: 'PERSONAL' | 'TENANT' | string
  /** 切片数量，>0 表示已可被检索 */
  chunkCount?: number
  /** 解析失败原因 */
  errorMsg?: string
}

/** 不传 scope=我的资料；scope=tenant=租户全部（仅租户管理员） */
export function listKbDocs(scope?: 'tenant'): Promise<KbDoc[]> {
  return http.get('/kb/documents', { params: scope ? { scope } : {} }).then((r) => unwrap<KbDoc[]>(r))
}

export function registerKbDoc(name: string, icon?: string, sizeBytes?: number): Promise<KbDoc> {
  return http.post('/kb/documents', { name, icon, sizeBytes }).then((r) => unwrap<KbDoc>(r))
}

/* ---------- 文件上传入库（pdf/docx/doc/xlsx/xls/txt/md/csv） ---------- */

export const KB_ACCEPT = '.pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv'
export const KB_MAX_MB = 50

/** 上传文件，后端解析正文后切片入库；scope=PERSONAL（默认）| TENANT */
export function uploadKbFile(
  file: File,
  scope?: 'PERSONAL' | 'TENANT',
  onProgress?: (percent: number) => void,
): Promise<KbDoc> {
  const fd = new FormData()
  fd.append('file', file)
  return http
    .post('/kb/documents/upload', fd, {
      params: scope ? { scope } : {},
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
    .then((r) => unwrap<KbDoc>(r))
}

/** 解析失败后重试入库 */
export function retryKbDoc(id: number): Promise<KbDoc> {
  return http.post(`/kb/documents/${id}/retry`, {}).then((r) => unwrap<KbDoc>(r))
}

/** 删除资料（连带删除切片） */
export function deleteKbDoc(id: number): Promise<{ id: number; deleted: boolean }> {
  return http.delete(`/kb/documents/${id}`).then((r) => unwrap<{ id: number; deleted: boolean }>(r))
}

/** 重命名 / 切换可见范围 */
export function updateKbDoc(id: number, body: { name?: string; scope?: 'PERSONAL' | 'TENANT' }): Promise<KbDoc> {
  return http.put(`/kb/documents/${id}`, body).then((r) => unwrap<KbDoc>(r))
}

export interface KbHit {
  docId: number
  docName: string
  snippet: string
  chunkIndex: number
}

/** 检索测试：返回命中的原文片段 */
export function searchKb(q: string, limit = 5): Promise<KbHit[]> {
  return http.get('/kb/search', { params: { q, limit } }).then((r) => unwrap<KbHit[]>(r))
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
  /** 每日执行时刻 HH:mm（如 08:00），空=不定时 */
  scheduleTime: string | null
  /** 到点执行的任务内容（交给模型真实执行） */
  taskPrompt: string | null
  /** 最近一次定时执行时间 */
  lastRunAt: string | null
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

export interface WorkerRun {
  id: number
  workerId: number
  workerName: string
  triggerType: 'SCHEDULE' | 'MANUAL' | string
  status: 'SUCCESS' | 'FAILED' | string
  output: string | null
  errorMsg: string | null
  model: string | null
  durationMs: number
  startedAt: string
  finishedAt: string | null
}

export function adminListWorkerRuns(id: number, limit = 20): Promise<WorkerRun[]> {
  return http.get(`/admin/workers/${id}/runs`, { params: { limit } }).then((r) => unwrap<WorkerRun[]>(r))
}
export function adminRunWorkerNow(id: number): Promise<WorkerRun> {
  return http.post(`/admin/workers/${id}/run`).then((r) => unwrap<WorkerRun>(r))
}

/* ============ 业务系统注册与配置管理（V15 · 管理端） ============ */

export interface BizSystem {
  id: number
  systemCode: string
  name: string
  description: string | null
  baseUrl: string | null
  authType: 'NONE' | 'API_KEY' | 'BASIC' | 'BEARER' | string
  /** 出参敏感字段已掩码（******）；入参传掩码值则保留库中原值 */
  authConfig: string | null
  docUrl: string | null
  docContent: string | null
  status: 'ENABLED' | 'DISABLED' | string
  createdAt: string
}

export function listBizSystems(q?: string): Promise<BizSystem[]> {
  return http.get('/admin/biz-systems', { params: q ? { q } : {} }).then((r) => unwrap<BizSystem[]>(r))
}
export function createBizSystem(body: Partial<BizSystem>): Promise<BizSystem> {
  return http.post('/admin/biz-systems', body).then((r) => unwrap<BizSystem>(r))
}
export function updateBizSystem(id: number, body: Partial<BizSystem>): Promise<BizSystem> {
  return http.put(`/admin/biz-systems/${id}`, body).then((r) => unwrap<BizSystem>(r))
}
export function toggleBizSystem(id: number): Promise<BizSystem> {
  return http.post(`/admin/biz-systems/${id}/toggle`).then((r) => unwrap<BizSystem>(r))
}
export function deleteBizSystem(id: number): Promise<{ id: number; deleted: boolean }> {
  return http.delete(`/admin/biz-systems/${id}`).then((r) => unwrap<{ id: number; deleted: boolean }>(r))
}

/* ============ 配额管理（管理端 · 技术方案 5.2 一期） ============ */

export interface QuotaOverviewUser {
  userId: number
  nickname: string
  quotaTokens: number
  usedTokens: number
  freeTokens: number
  updatedAt: string | null
}

export interface QuotaOverview {
  totalQuota: number
  totalUsed: number
  totalFree: number
  memberCount: number
  users: QuotaOverviewUser[]
}

export function getQuotaOverview(): Promise<QuotaOverview> {
  return http.get('/admin/quotas').then((r) => unwrap<QuotaOverview>(r))
}
export function assignQuota(userId: number, quotaTokens: number): Promise<{ userId: number; quotaTokens: number }> {
  return http.put(`/admin/quotas/${userId}`, { quotaTokens }).then((r) => unwrap<{ userId: number; quotaTokens: number }>(r))
}
export interface UsageRow {
  bizType: string
  cnt: number
  totalTokens: number
  promptTokens: number
  completionTokens: number
}
export interface LedgerRow {
  id: number
  userId: number
  userName: string
  bizType: string
  bizTitle: string | null
  totalTokens: number
  createdAt: string
}
export function getQuotaUsage(days = 30): Promise<{ since: string; byBizType: UsageRow[]; recentLedger: LedgerRow[] }> {
  return http.get('/admin/quotas/usage', { params: { days } }).then((r) => unwrap<{ since: string; byBizType: UsageRow[]; recentLedger: LedgerRow[] }>(r))
}

/* ============ 操作审计（管理端 · 权限变更审计） ============ */

export interface AuditRow {
  id: number
  userId: number
  userName: string
  action: string
  status: string
  label: string
  createdAt: string
}

export function listAuditLogs(limit = 100): Promise<AuditRow[]> {
  return http.get('/admin/audit-logs', { params: { limit } }).then((r) => unwrap<AuditRow[]>(r))
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

/* ============ 系统参数配置（管理端 · V18 AdminConfigController） ============ */

export interface SysConfigItem {
  id: number
  tenantId: number
  configKey: string
  configValue: string
  /** INT / DECIMAL / BOOL / STRING / JSON */
  valueType: string
  /** CONVERSATION / QUOTA / KNOWLEDGE / SECURITY / COMMON */
  groupCode: string
  configName: string
  description: string
  unit: string
  defaultValue: string
  minValue: number | null
  maxValue: number | null
  editable: boolean
  sortNo: number
  updatedAt: string
}

export interface SysConfigResult {
  groups: Record<string, string>
  items: SysConfigItem[]
  grouped: Record<string, SysConfigItem[]>
  total: number
}

export function listConfigs(params?: { q?: string; group?: string }): Promise<SysConfigResult> {
  return http.get('/admin/configs', { params }).then((r) => unwrap<SysConfigResult>(r))
}

export function updateConfig(key: string, value: string): Promise<SysConfigItem> {
  return http.put('/admin/configs/' + encodeURIComponent(key), { value }).then((r) => unwrap<SysConfigItem>(r))
}

export function updateConfigs(items: { key: string; value: string }[]): Promise<{ changed: string[]; rejected: string[] }> {
  return http.put('/admin/configs', { items }).then((r) => unwrap<{ changed: string[]; rejected: string[] }>(r))
}

export function resetConfig(key: string): Promise<SysConfigItem> {
  return http.post('/admin/configs/' + encodeURIComponent(key) + '/reset').then((r) => unwrap<SysConfigItem>(r))
}

export function resetAllConfigs(): Promise<{ reseted: number }> {
  return http.post('/admin/configs/reset').then((r) => unwrap<{ reseted: number }>(r))
}
