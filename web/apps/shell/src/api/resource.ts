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

/* ============ 多级审批引擎（aioa-org WorkflowController） ============
 *
 * 与上面单级审批的分工：
 *   · 多级引擎按「审批流定义」把单据展开成 N 个节点（部门负责人 → 企业管理员 → …），
 *     待办按「节点指派人」返回 —— 机构管理员的待办只能从这里拿到；
 *   · 单级审批（历史）的待办池是同租户全部 PENDING，只有租户/平台管理员可见，
 *     目前承载成果 / 公文这类没有多级流程的业务。
 */

/** 审批流节点（流转路径上的一级）。 */
export interface ApprovalTaskNode {
  taskId: number
  seq: number
  /** DEPT_LEADER / DEPT_DUTY / UNIT_DUTY / ORG_ADMIN / TENANT_ADMIN / PLATFORM_ADMIN / SPECIFIC / APPLICANT_SUPERIOR */
  approverType: string
  approverId: number | null
  approverName: string | null
  /** 五期：节点处理模式 single / parallel / grab（同 seq 多条任务 = 一个节点组） */
  nodeMode?: string | null
  /** 四期：职务型节点（DEPT_DUTY / UNIT_DUTY）求值用的职务码 */
  nodeDuty?: string | null
  /** 职务码的中文名（由后端按租户职务字典解析，前端不硬编码） */
  dutyName?: string | null
  /** PENDING / APPROVED / REJECTED / SKIPPED */
  status: string
  note: string | null
  skipReason: string | null
  decidedAt: string | null
}

/** 待办计数（菜单红点用，不下发明细）。 */
export interface WorkflowTaskSummary {
  /** 待我处理（点亮红点） */
  todo: number
  /** 我发起且仍在途 */
  mine: number
  /** 抄送我的**总条数**（一期语义，不因已读减少） */
  cc?: number
  /** 未读知会数（三期 C-06） */
  ccUnread?: number
  generatedAt: string
}

/** 待我审批 / 我发起的（多级引擎）。带 timeline 与「当前流转到谁」。 */
export interface WorkflowTask {
  id: number
  taskId: number
  bizType: string
  title: string
  content?: string | null
  formData?: string | null
  attachment?: string | null
  status: string
  applicantName?: string
  /** 二期主体：USER 个人 / DEPARTMENT 部门 */
  applicantType?: string
  applicantDepartmentId?: number | null
  applicantDepartmentName?: string | null
  /** 三期：知会已读态（仅 scope=cc 有意义） */
  read?: boolean
  readAt?: string | null
  creatorName?: string
  userId?: number
  approver?: string | null
  decisionNote?: string | null
  decidedAt?: string | null
  createdAt: string
  seq?: number
  approverType?: string
  approverName?: string
  totalNodes?: number
  currentSeq?: number
  currentApproverName?: string | null
  timeline?: ApprovalTaskNode[]
}

export function listWorkflowTodo(): Promise<WorkflowTask[]> {
  return http.get('/workflow/tasks', { params: { scope: 'todo' } }).then((r) => unwrap<WorkflowTask[]>(r))
}

/** 抄送我的（知会 / 待阅）。已读条目仍在列表，仅 read=true / readAt 有值（可回查）。 */
export function listWorkflowCc(): Promise<WorkflowTask[]> {
  return http.get('/workflow/tasks', { params: { scope: 'cc' } }).then((r) => unwrap<WorkflowTask[]>(r))
}

/** 标记知会已读（幂等；点开知会详情即调用）。 */
export function markWorkflowCcRead(taskId: number): Promise<{
  taskId: number
  orderId: number
  read: boolean
  readAt: string | null
  ccUnread: number
}> {
  return http.post(`/workflow/cc/${taskId}/read`, {}).then((r) => unwrap(r))
}

/** 我发起的（含请假 / 扩容 / 成果 / 公文），任何登录用户可读，带完整流转路径。 */
export function listMyApplications(): Promise<WorkflowTask[]> {
  return http.get('/workflow/mine').then((r) => unwrap<WorkflowTask[]>(r))
}

/**
 * 待办计数 —— 管理端菜单红点的唯一数据源。
 *
 * <p>刻意不复用 {@link listWorkflowTodo}：红点会被轮询，回整棵待办树（含每单 timeline）
 * 代价过高；后端用一条聚合 SQL 给出同口径的数字。</p>
 */
export function workflowTodoSummary(): Promise<WorkflowTaskSummary> {
  return http.get('/workflow/tasks/summary').then((r) => unwrap<WorkflowTaskSummary>(r))
}

export function decideWorkflowTask(
  taskId: number,
  decision: 'APPROVE' | 'REJECT',
  note?: string
): Promise<{ taskId: number; orderId: number; finalDone: boolean; orderStatus: string }> {
  return http.post(`/workflow/tasks/${taskId}/decide`, { decision, note }).then((r) => unwrap(r))
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
  /** 入库流水线阶段：PARSING/CHUNKING/EMBEDDING/OK/FAILED */
  stage?: string
  /** 入库进度 0-100 */
  progress?: number
  /** 失败重试次数 */
  retryCount?: number
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

/* ---------- 人员管理：按权限作用域取数 + 自动分类（V37） ---------- */

/** 人员档位：与后端 PersonnelService 的 scopeClass 一一对应。 */
export type PersonnelClass = 'PLATFORM' | 'TENANT' | 'ORG' | 'DEPT' | 'MEMBER'

export interface PersonnelMember {
  id: number
  username: string
  nickname: string
  mobile?: string | null
  email?: string | null
  status: string
  tenantId?: number | null
  tenantName?: string | null
  institutionId?: number | null
  institutionName?: string | null
  departmentId?: number | null
  departmentName?: string | null
  jobTitle?: string | null
  employeeNo?: string | null
  lastLoginAt?: string | null
  createdAt?: string | null
  roles: string[]
  scopeClass: PersonnelClass
  scopeLabel: string
  /** 花名册标记的机构管理员（org_member.is_org_admin） */
  orgAdmin: boolean
  /** 是否担任某部门负责人（org_department.leader_user_id） */
  deptLeader: boolean
}

export interface PersonnelGroup {
  key: string
  label: string
  count: number
  members: PersonnelMember[]
}

export interface PersonnelView {
  /** 调用者作用域：平台 / 租户 / 机构 / 部门 */
  scope: 'PLATFORM' | 'TENANT' | 'ORG' | 'DEPT'
  /** 作用域名称（租户全称 / 机构全称 / 部门名称） */
  scopeName: string
  /** 自动分类维度：平台=租户，租户=机构，机构/部门=档位 */
  groupBy: 'TENANT' | 'INSTITUTION' | 'TIER'
  total: number
  groups: PersonnelGroup[]
  classCounts: Record<string, number>
  /** 写操作能力（角色分配 / 账号启停仅平台管理员）；readOnly=true 时前端应收起操作列 */
  capability: { canAssignRole: boolean; canChangeStatus: boolean; readOnly: boolean }
  tenantId?: number | null
  institutionId?: number | null
  departmentId?: number | null
  keyword: string
  /** 面向当前账号的范围说明（直接展示给用户，避免「为什么我只能看到这些人」的疑问） */
  hint: string
}

/**
 * 人员管理列表（已按调用者权限作用域过滤并按档位 / 机构 / 租户分组）。
 *
 * @param keyword  用户名或昵称模糊搜索
 * @param tenantId 仅平台管理员有效：把结果收窄到指定租户
 */
export function listPersonnel(params?: { keyword?: string; tenantId?: number }): Promise<PersonnelView> {
  return http.get('/admin/personnel', { params }).then((r) => unwrap<PersonnelView>(r))
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
  /** 模型标识（唯一，如 minimax / deepseek） */
  providerKey: string
  /** 大模型类型：minimax / deepseek / dashscope / vllm / ollama / custom */
  providerType: string
  name: string
  baseUrl: string
  modelName: string
  apiKeyEnv: string
  /** 后端只回掩码；apiKey 字段仅用于提交，列表里恒为空 */
  apiKeyMasked: string
  /** DB=管理端填写 / ENV=环境变量 / NONE=未配置 */
  apiKeySource: string
  enabled: boolean
  isDefault: boolean
  sort: number
  temperature: number
  maxContext: number
  /** 提交专用：留空或原样回传掩码 = 不修改密钥 */
  apiKey?: string
  [key: string]: unknown
}

/** 大模型类型预设：选中后自动带出接入地址 / 模型名 / 密钥环境变量名 */
export interface ModelPreset {
  type: string
  label: string
  baseUrl: string
  defaultModel: string
  apiKeyEnv: string
  temperature: number
  maxContext: number
}

/** 连通性校验结果：ok=false 时 message 是可直接展示给用户的失败原因 */
export interface ModelCheckResult {
  providerKey: string
  ok: boolean
  message: string
  latencyMs: number
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

export function listModelPresets(): Promise<{ presets: ModelPreset[]; keyEncryptionWeak: boolean }> {
  return http.get('/admin/models/presets').then((r) =>
    unwrap<{ presets: ModelPreset[]; keyEncryptionWeak: boolean }>(r),
  )
}

/** 启停：启用时后端先做连通性校验，不通过会返回明确原因（抛 ApiError） */
export function setModelStatus(key: string, enabled: boolean): Promise<ModelCheckResult> {
  return http.put(`/admin/models/${key}/status`, { enabled }).then((r) => unwrap<ModelCheckResult>(r))
}

/** 只做连通性校验，不改启用状态 */
export function testModel(key: string): Promise<ModelCheckResult> {
  return http.post(`/admin/models/${key}/test`, {}).then((r) => unwrap<ModelCheckResult>(r))
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

/** V33：按当前口径的真实指标调用模型生成解读（非预置文案），生成结果直接落库。 */
export interface KpiInsightResult {
  insight: string
  source: string
  model: string
  period: string
  generatedAt: string
  promptTokens: number
}
export function generateKpiInsight(period: string): Promise<KpiInsightResult> {
  return http.post('/kpi/board/insight', null, { params: { period } }).then((r) => unwrap<KpiInsightResult>(r))
}

/* ============ V34 内容审核台（平台管理员审租户管理员创建的内容） ============ */
/** V36：类型扩到 expert_config（专家配置片段，需求⑤）。 */
export type ContentReviewType = 'worker' | 'expert' | 'expert_config'
export interface ContentReviewItem {
  type: ContentReviewType
  id: number
  tenantId: number
  name: string
  summary?: string
  auditStatus: string
  auditNote?: string
  createdBy?: number
  createdByName?: string
  createdAt?: string
  /** V36：处理方双边留痕（需求④） */
  reviewedBy?: number
  reviewerName?: string
  reviewedAt?: string
  scopeType?: string
  scopeId?: number
  expertKey?: string
}
export function listContentReviews(
  status = 'PENDING',
  type = 'all'
): Promise<{
  items: ContentReviewItem[]
  total: number
  status: string
  type?: string
  switchOn: boolean
}> {
  return http.get('/admin/content-reviews', { params: { status, type } }).then((r) => unwrap(r))
}
export function reviewContent(
  type: string,
  id: number,
  approve: boolean,
  note?: string
): Promise<Record<string, unknown>> {
  return http
    .post(`/admin/content-reviews/${type}/${id}/review`, { approve, note })
    .then((r) => unwrap<Record<string, unknown>>(r))
}

/* ============ V36 审核记录中心（需求④：提交方 + 处理方双边留痕） ============ */
export interface ReviewRecord {
  type: 'worker' | 'expert' | 'expert_config' | 'permission_grant'
  id: number
  tenantId: number
  institutionId?: number
  name: string
  summary?: string
  /** 内容审核为 PENDING/APPROVED/REJECTED；权限授权为 PENDING/ACTIVE/REJECTED/REVOKED */
  auditStatus: string
  auditNote?: string
  createdBy?: number
  createdByName?: string
  createdAt?: string
  reviewedBy?: number
  reviewerName?: string
  reviewedAt?: string
  permissionCode?: string
  targetWorkerType?: string
  orderId?: number
  scopeType?: string
  expertKey?: string
}
export function listReviewRecords(params: {
  type?: string
  status?: string
  keyword?: string
  tenantId?: number
  page?: number
  size?: number
}): Promise<{
  items: ReviewRecord[]
  total: number
  page: number
  size: number
  stats: Record<string, number>
  scope: string
  tenantId?: number
}> {
  return http.get('/admin/review-records', { params }).then((r) => unwrap(r))
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

/* ---------- 数字员工模板与可见范围（V29 · 部门分发） ---------- */

export interface WorkerTemplate {
  id: number
  name: string
  icon: string
  description: string
  workerType: string
  roleName: string
  runMode: string
  taskPrompt: string
}

/** 平台全局模板（tenant_id=0），租户可据此一键创建，避免开通后面对空白页。 */
export function listWorkerTemplates(): Promise<WorkerTemplate[]> {
  return http.get('/workers/templates').then((r) => unwrap<WorkerTemplate[]>(r))
}

/** 从模板复制到本租户。 */
export function createWorkerFromTemplate(
  templateId: number,
  body: { name?: string }
): Promise<AgentWorker> {
  return http.post(`/workers/from-template/${templateId}`, body).then((r) => unwrap<AgentWorker>(r))
}

/** 设置可见范围：TENANT=全租户可见；DEPT=仅指定部门可见（部门分发）。 */
export function setWorkerVisibleScope(
  id: number,
  scope: 'TENANT' | 'DEPT',
  deptIds?: number[]
): Promise<AgentWorker> {
  return http
    .put(`/workers/${id}/visible-scope`, { scope, deptIds })
    .then((r) => unwrap<AgentWorker>(r))
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

/* ---------- 业务工具网关（数据分析师闭环） ---------- */

export interface ToolDef {
  type?: string
  function?: {
    name: string
    description: string
    parameters?: Record<string, unknown>
  }
}

export function listTools(): Promise<ToolDef[]> {
  return http.get('/tools').then((r) => unwrap<ToolDef[]>(r))
}

export function invokeTool(name: string, arguments_: Record<string, unknown>): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  return http.post('/tools/invoke', { name, arguments: arguments_ }).then((r) => unwrap(r))
}
