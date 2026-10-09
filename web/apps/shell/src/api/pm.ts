import { http, unwrap } from './index'

/**
 * 项目管理（PM，V71 / docs/40）。
 *
 * <p>本文件是「后端 {@code aioa-project} 模块 REST 契约」在前端的唯一映射入口。
 * 字段名与后端 {@code PmProjectController} / {@code PmTaskController} 返回的
 * {@code Map<String,Object>} **逐字对应**，不在视图里另起一套字面量。</p>
 *
 * <p><b>错误口径</b>：后端「业务失败」（如 BR-01「业务项目不支持代码仓库配置」）
 * 走的是 HTTP 200 + {@code code≠0}（400/409 都在 body 里，只有 401/403/404 才改 HTTP 状态码），
 * 由 {@code unwrap} 抛 {@link ApiError}。视图里统一用 {@link pmErrMsg} 取文案，
 * 否则「业务项目不支持…」这类关键提示会被吞成通用失败。</p>
 */

// ============================================================ 元信息

export interface PmConfig {
  projectTypes: Array<{ value: string; label: string; hint?: string }>
  statuses: Array<{ value: string; label: string }>
  projectRoleOptions: Array<{ value: string; label: string }>
}

// ============================================================ 项目

export interface PmProject {
  id: number
  projectNo: string
  name: string
  /** BUSINESS 业务项目 / DEV 开发项目。 */
  projectType: string
  status: string
  institutionId?: number
  departmentId?: number
  ownerMemberId?: number
  ownerName?: string
  budgetAmount?: number | string
  startDate?: string
  endDate?: string
  description?: string
  taskCount?: number
  taskDoneCount?: number
  memberCount?: number
  repoCount?: number
  /** 我在本项目里的角色（OWNER/PM/DEV/MEMBER/VIEWER）；非成员为 null。 */
  myRole?: string | null
  canManage?: boolean
  createdAt?: string
  /** 仅详情接口返回。 */
  boundRepos?: PmRepo[]
  /** 仅创建接口可能返回：自动建仓失败时的原因（不阻断立项）。 */
  repoWarning?: string
}

/** 已绑定的代码仓库（来自既有 gitee_project，只读映射）。 */
export interface PmRepo {
  id: number
  name?: string
  repo_name?: string
  gitee_owner?: string
  gitee_repo?: string
  gitee_html_url?: string
  default_branch?: string
  status?: string
  error_msg?: string
  pm_project_id?: number | null
}

export interface PmProjectQuery {
  keyword?: string
  projectType?: string
  status?: string
  departmentId?: number
}

export interface PmCreateProjectBody {
  projectNo: string
  name: string
  projectType: 'BUSINESS' | 'DEV'
  departmentId?: number
  ownerMemberId?: number
  budgetAmount?: number
  startDate?: string
  endDate?: string
  description?: string
  /** 绑定既有仓库（仅开发项目）。 */
  bindRepoId?: number
  /** 自动建仓（仅开发项目）；失败不阻断立项。 */
  createRepo?: boolean
  repoVisibility?: 'private' | 'public'
}

export function pmConfig() {
  return http.get('/pm/config').then((r) => unwrap<PmConfig>(r))
}

export function pmProjects(params: PmProjectQuery = {}) {
  return http.get('/pm/projects', { params }).then((r) => unwrap<PmProject[]>(r))
}

export function pmProjectDetail(projectId: number) {
  return http.get(`/pm/projects/${projectId}`).then((r) => unwrap<PmProject>(r))
}

export function pmCreateProject(body: PmCreateProjectBody) {
  return http.post('/pm/projects', body).then((r) => unwrap<PmProject>(r))
}

export function pmUpdateProject(projectId: number, body: Partial<PmCreateProjectBody> & { ownerMemberId?: number }) {
  return http.put(`/pm/projects/${projectId}`, body).then((r) => unwrap<PmProject>(r))
}

export function pmChangeProjectStatus(projectId: number, status: string) {
  return http.post(`/pm/projects/${projectId}/status`, { status }).then((r) => unwrap<PmProject>(r))
}

export function pmDeleteProject(projectId: number) {
  return http.delete(`/pm/projects/${projectId}`).then((r) => unwrap<void>(r))
}

// ============================================================ 仓库绑定

export function pmBoundRepos(projectId: number) {
  return http.get(`/pm/projects/${projectId}/repos`).then((r) => unwrap<PmRepo[]>(r))
}

export function pmBindableRepos(projectId: number) {
  return http.get(`/pm/projects/${projectId}/repos/bindable`).then((r) => unwrap<PmRepo[]>(r))
}

/** 新建流程专用：还没有项目 id 时挑可绑仓库（鉴权依据为「有新建项目权限」）。 */
export function pmBindableReposForCreate() {
  return http.get('/pm/repos/bindable').then((r) => unwrap<PmRepo[]>(r))
}

export function pmBindRepo(projectId: number, repoId: number) {
  return http
    .post(`/pm/projects/${projectId}/repos`, { repoId })
    .then((r) => unwrap<{ repoId: number; boundRepos: PmRepo[] }>(r))
}

export function pmUnbindRepo(projectId: number, repoId: number) {
  return http
    .delete(`/pm/projects/${projectId}/repos/${repoId}`)
    .then((r) => unwrap<{ repoId: number; boundRepos: PmRepo[] }>(r))
}

// ============================================================ 成员

export interface PmMember {
  id: number
  memberId: number
  userId?: number
  name?: string
  employeeNo?: string
  jobTitle?: string
  departmentId?: number
  roleCode: string
  roleLabel?: string
  repoSyncStatus?: string
  joinedAt?: string
}

export interface PmMemberList {
  items: PmMember[]
  roleOptions: Array<{ value: string; label: string }>
  canManage: boolean
  /** 开发项目专属：仓库协作者同步说明（本批次只落状态，未自动推送）。 */
  repoSyncNote?: string
}

export interface PmMemberCandidate {
  memberId: number
  name?: string
  employeeNo?: string
  jobTitle?: string
  mobile?: string
  departmentId?: number
}

export function pmMembers(projectId: number) {
  return http.get(`/pm/projects/${projectId}/members`).then((r) => unwrap<PmMemberList>(r))
}

export function pmMemberCandidates(projectId: number, keyword?: string) {
  return http
    .get(`/pm/projects/${projectId}/members/candidates`, { params: { keyword } })
    .then((r) => unwrap<PmMemberCandidate[]>(r))
}

export function pmAddMember(projectId: number, memberId: number, roleCode: string) {
  return http.post(`/pm/projects/${projectId}/members`, { memberId, roleCode }).then((r) => unwrap<PmMemberList>(r))
}

export function pmChangeMemberRole(projectId: number, rowId: number, roleCode: string) {
  return http
    .put(`/pm/projects/${projectId}/members/${rowId}`, { roleCode })
    .then((r) => unwrap<PmMemberList>(r))
}

export function pmRemoveMember(projectId: number, rowId: number) {
  return http.delete(`/pm/projects/${projectId}/members/${rowId}`).then((r) => unwrap<PmMemberList>(r))
}

// ============================================================ 任务

export interface PmTask {
  id: number
  projectId: number
  parentId?: number | null
  title: string
  description?: string
  status: string
  statusLabel?: string
  priority?: string
  assigneeMemberId?: number | null
  startDate?: string
  dueDate?: string
  progress?: number
  /** 仓库字段：业务项目恒为 null（后端同口径）。 */
  repoId?: number | null
  repoIssueNo?: string | null
  repoBranch?: string | null
  repoCommitSha?: string | null
  createdAt?: string
}

export interface PmTaskList {
  items: PmTask[]
  total: number
  canManage: boolean
  myRole?: string | null
  isDev: boolean
  statusOptions: Array<{ value: string; label: string }>
}

export interface PmTaskBody {
  title?: string
  description?: string
  priority?: string
  assigneeMemberId?: number | null
  startDate?: string | null
  dueDate?: string | null
  progress?: number
  parentId?: number | null
  repoId?: number | null
  repoIssueNo?: string | null
  repoBranch?: string | null
  repoCommitSha?: string | null
}

export function pmTasks(
  projectId: number,
  params: { status?: string; assigneeMemberId?: number; keyword?: string } = {}
) {
  return http.get(`/pm/projects/${projectId}/tasks`, { params }).then((r) => unwrap<PmTaskList>(r))
}

export function pmCreateTask(projectId: number, body: PmTaskBody) {
  return http.post(`/pm/projects/${projectId}/tasks`, body).then((r) => unwrap<PmTask>(r))
}

export function pmUpdateTask(projectId: number, taskId: number, body: PmTaskBody) {
  return http.put(`/pm/projects/${projectId}/tasks/${taskId}`, body).then((r) => unwrap<PmTask>(r))
}

export function pmChangeTaskStatus(projectId: number, taskId: number, status: string) {
  return http.post(`/pm/projects/${projectId}/tasks/${taskId}/status`, { status }).then((r) => unwrap<PmTask>(r))
}

export function pmDeleteTask(projectId: number, taskId: number) {
  return http.delete(`/pm/projects/${projectId}/tasks/${taskId}`).then((r) => unwrap<void>(r))
}

// ============================================================ 文档（V72 / docs/43）

export interface PmDocItem {
  id: number
  folderId: number
  name: string
  fileId?: number | null
  /** UPLOAD 外部上传 / AI 大模型创建。 */
  source: string
  sizeBytes?: number
  version?: number
  tags?: string
  uploadedBy?: number
  createdAt?: string
  /** 仅详情接口返回：AI 生成文档的正文。 */
  contentText?: string | null
}

export interface PmDocNode {
  id: number
  name: string
  parentId: number
  scope: 'ENTERPRISE' | 'PROJECT'
  /** 企业级公共文件夹在项目页是只读挂载。 */
  readonly: boolean
  storageKind?: string
  children: PmDocNode[]
  documents: PmDocItem[]
  documentCount: number
}

export interface PmDocTree {
  canManage: boolean
  projectRootName?: string
  enterpriseRootLabel?: string
  /** 项目页：企业级（只读挂载）+ 项目专属（可写）。 */
  enterprise?: PmDocNode[]
  project?: PmDocNode[]
  /** 企业文档页：仅企业级。 */
  roots?: PmDocNode[]
}

export function pmDocTree(projectId: number) {
  return http.get(`/pm/projects/${projectId}/docs/tree`).then((r) => unwrap<PmDocTree>(r))
}

export function pmDocEnterpriseTree() {
  return http.get('/pm/docs/enterprise').then((r) => unwrap<PmDocTree>(r))
}

export function pmCreateFolder(projectId: number, body: { name: string; parentId?: number }) {
  return http
    .post(`/pm/projects/${projectId}/docs/folders`, body)
    .then((r) => unwrap<{ id: number; name: string; parentId: number; path: string }>(r))
}

export function pmDeleteFolder(projectId: number, folderId: number) {
  return http.delete(`/pm/projects/${projectId}/docs/folders/${folderId}`).then((r) => unwrap<void>(r))
}

/**
 * 登记文档。`source=UPLOAD` 须先经 `/api/v1/files/upload` 拿 `fileId`；
 * `source=AI` 传 `contentText`（大模型创建）。
 */
export function pmCreateDocument(
  projectId: number,
  body: { folderId: number; name: string; source?: 'UPLOAD' | 'AI'; fileId?: number; contentText?: string; tags?: string }
) {
  return http.post(`/pm/projects/${projectId}/docs/documents`, body).then((r) => unwrap<PmDocItem>(r))
}

export function pmDocDetail(projectId: number, docId: number) {
  return http.get(`/pm/projects/${projectId}/docs/documents/${docId}`).then((r) => unwrap<PmDocItem>(r))
}

export function pmDeleteDocument(projectId: number, docId: number) {
  return http.delete(`/pm/projects/${projectId}/docs/documents/${docId}`).then((r) => unwrap<void>(r))
}

// ============================================================ 经费（V73 / docs/43 §4）

export interface PmExpenseItem {
  id: number
  projectId: number
  /** IN 收入 / OUT 支出。 */
  direction: string
  directionLabel?: string
  /** CONTRACT 合同款 / LABOR 人工 / PURCHASE 采购 / TRAVEL 差旅 / OTHER 其他。 */
  category: string
  categoryLabel?: string
  amount: number | string
  /** 分摊比例（「分摊」关键词）。 */
  allocRatio?: number | string | null
  occurredAt?: string
  /** 由合同收付款确认自动生成时，溯源到 pm_contract_payment.id。 */
  contractPaymentId?: number | null
  /** 红冲行指向被冲销的原行 id；非空即「这是红冲行」。 */
  reversalOf?: number | null
  isReversal?: boolean
  remark?: string
  createdAt?: string
}

export interface PmExpenseList {
  canManage: boolean
  items: PmExpenseItem[]
  total: number
  summary: {
    budgetAmount: number | string
    totalIncome: number | string
    totalOutcome: number | string
    balance: number | string
    /** 超支只警示不阻断（BR-16）。 */
    overrun: boolean
    categories: Array<{ value: string; label: string }>
    directions: Array<{ value: string; label: string }>
  }
}

export interface PmExpenseBody {
  direction: 'IN' | 'OUT'
  category: string
  amount: number
  occurredAt?: string
  allocRatio?: number
  remark?: string
}

export function pmExpenses(projectId: number, params: { direction?: string; category?: string } = {}) {
  return http.get(`/pm/projects/${projectId}/expenses`, { params }).then((r) => unwrap<PmExpenseList>(r))
}

export function pmCreateExpense(projectId: number, body: PmExpenseBody) {
  return http.post(`/pm/projects/${projectId}/expenses`, body).then((r) => unwrap<PmExpenseItem>(r))
}

/** 红冲：原行不改，追加反向流水。同一原行重复红冲 → 409。 */
export function pmReverseExpense(projectId: number, expenseId: number, reason?: string) {
  return http
    .post(`/pm/projects/${projectId}/expenses/${expenseId}/reverse`, { reason })
    .then((r) => unwrap<PmExpenseItem>(r))
}

// ============================================================ 合同 + 收付款（V73 / docs/43 §4）

export interface PmContractItem {
  id: number
  projectId: number
  contractNo: string
  name: string
  /** IN 收款合同 / OUT 采购付款合同。 */
  direction: string
  directionLabel?: string
  category: string
  partyName?: string
  amount: number | string
  status: string
  statusLabel?: string
  signedAt?: string
  startDate?: string
  endDate?: string
  fileId?: number | null
  createdAt?: string
}

export interface PmContractList {
  canManage: boolean
  items: PmContractItem[]
  total: number
  statuses: Array<{ value: string; label: string }>
  directions: Array<{ value: string; label: string }>
}

export interface PmContractPaymentItem {
  id: number
  contractId: number
  seq: number
  planAmount: number | string
  planDate?: string
  actualAmount?: number | string
  actualDate?: string
  /** PLANNED 计划 / CONFIRMED 已确认 / REVERSED 已红冲。 */
  status: string
  statusLabel?: string
  milestoneId?: number | null
}

export interface PmContractPayments {
  contract: PmContractItem
  items: PmContractPaymentItem[]
  total: number
}

export interface PmContractBody {
  contractNo: string
  name: string
  direction: 'IN' | 'OUT'
  category?: string
  partyName?: string
  amount?: number
  signedAt?: string
  startDate?: string
  endDate?: string
  fileId?: number
}

export function pmContracts(projectId: number, params: { direction?: string } = {}) {
  return http.get(`/pm/projects/${projectId}/contracts`, { params }).then((r) => unwrap<PmContractList>(r))
}

export function pmCreateContract(projectId: number, body: PmContractBody) {
  return http.post(`/pm/projects/${projectId}/contracts`, body).then((r) => unwrap<PmContractItem>(r))
}

export function pmUpdateContract(projectId: number, contractId: number, body: Partial<PmContractBody>) {
  return http.put(`/pm/projects/${projectId}/contracts/${contractId}`, body).then((r) => unwrap<PmContractItem>(r))
}

export function pmChangeContractStatus(projectId: number, contractId: number, status: string) {
  return http
    .post(`/pm/projects/${projectId}/contracts/${contractId}/status`, { status })
    .then((r) => unwrap<PmContractItem>(r))
}

export function pmContractPayments(projectId: number, contractId: number) {
  return http.get(`/pm/projects/${projectId}/contracts/${contractId}/payments`).then((r) => unwrap<PmContractPayments>(r))
}

export function pmAddContractPayment(projectId: number, contractId: number, body: { planAmount: number; planDate?: string }) {
  return http
    .post(`/pm/projects/${projectId}/contracts/${contractId}/payments`, body)
    .then((r) => unwrap<PmContractPayments>(r))
}

/**
 * 确认实收/实付 —— BR-09：后端在同一事务内自动生成一条经费流水。
 * 前端**不要**再另行登记经费，否则同笔业务记两遍。
 */
export function pmConfirmContractPayment(
  projectId: number,
  contractId: number,
  paymentId: number,
  body: { actualAmount?: number; actualDate?: string } = {}
) {
  return http
    .post(`/pm/projects/${projectId}/contracts/${contractId}/payments/${paymentId}/confirm`, body)
    .then((r) => unwrap<PmContractPayments>(r))
}

/** 红冲已确认的收付款（置 REVERSED + 追加反向流水）。 */
export function pmReverseContractPayment(projectId: number, contractId: number, paymentId: number, reason?: string) {
  return http
    .post(`/pm/projects/${projectId}/contracts/${contractId}/payments/${paymentId}/reverse`, { reason })
    .then((r) => unwrap<PmContractPayments>(r))
}

// ============================================================ 数字人 + 上下文（V74/V76 / docs/43 §5）

export interface PmWorkerItem {
  /** 分配记录 id（pm_project_worker.id），非 workerId。 */
  id: number
  /** 既有数字员工 id（agent_worker.id）。 */
  workerId: number
  name?: string | null
  workerType?: string | null
  status?: string | null
  /** 该数字员工已被删除（不在候选中）时置真，界面应显示「已移除」。 */
  workerMissing?: boolean
  assignRole?: string
  enabled: boolean
  assignedBy?: number
  createdAt?: string
}

export interface PmWorkerCandidate {
  workerId: number
  name: string
  workerType?: string
  status?: string
}

export interface PmWorkerList {
  canManage: boolean
  items: PmWorkerItem[]
  candidates: PmWorkerCandidate[]
}

export interface PmContextSourceItem {
  id: number
  /** UPLOAD 后台上传 / WEB_SEARCH 网上搜索 / POLICY 政策。 */
  sourceType: string
  typeLabel?: string
  name: string
  /** 0 = 项目级默认（对全体已分配数字人生效）。 */
  workerId: number
  workerName?: string
  folderId?: number | null
  fileId?: number | null
  kbDocumentId?: number | null
  /** WEB_SEARCH：JSON 字符串 {"keywords":[],"domains":[],"maxResults":N}。 */
  config?: string | null
  enabled: boolean
  createdBy?: number
  createdAt?: string
}

export interface PmContextSourceList {
  canManage: boolean
  items: PmContextSourceItem[]
  workers: Array<{ workerId: number; name: string; enabled: boolean }>
  types: Array<{ value: string; label: string }>
}

export interface PmAiScope {
  projectId: number
  workerId: number
  projectDefault: PmContextSourceItem[]
  workerSpecific: PmContextSourceItem[]
  effective: PmContextSourceItem[]
  effectiveCount: number
}

export function pmWorkers(projectId: number) {
  return http.get(`/pm/projects/${projectId}/workers`).then((r) => unwrap<PmWorkerList>(r))
}

export function pmAssignWorker(projectId: number, body: { workerId: number; assignRole?: string }) {
  return http.post(`/pm/projects/${projectId}/workers`, body).then((r) => unwrap<PmWorkerItem>(r))
}

export function pmUpdateWorker(projectId: number, workerRowId: number, body: { assignRole?: string; enabled?: boolean }) {
  return http.put(`/pm/projects/${projectId}/workers/${workerRowId}`, body).then((r) => unwrap<PmWorkerItem>(r))
}

/** 移除数字员工：后端会一并软删「仅属于该员工」的上下文来源。 */
export function pmUnassignWorker(projectId: number, workerRowId: number) {
  return http
    .delete(`/pm/projects/${projectId}/workers/${workerRowId}`)
    .then((r) => unwrap<{ workerId: number; removedContextSources: number }>(r))
}

export function pmContextSources(projectId: number) {
  return http.get(`/pm/projects/${projectId}/context-sources`).then((r) => unwrap<PmContextSourceList>(r))
}

export interface PmContextSourceBody {
  sourceType: 'UPLOAD' | 'WEB_SEARCH' | 'POLICY'
  name?: string
  workerId?: number
  folderId?: number
  fileId?: number
  kbDocumentId?: number
  /** WEB_SEARCH：{keywords, domains?, maxResults?}（对象或 JSON 字符串均可）。 */
  config?: { keywords: string[]; domains?: string[]; maxResults?: number } | string
}

export function pmCreateContextSource(projectId: number, body: PmContextSourceBody) {
  return http.post(`/pm/projects/${projectId}/context-sources`, body).then((r) => unwrap<PmContextSourceItem>(r))
}

export function pmUpdateContextSource(projectId: number, sourceId: number, body: Partial<PmContextSourceBody> & { enabled?: boolean }) {
  return http.put(`/pm/projects/${projectId}/context-sources/${sourceId}`, body).then((r) => unwrap<PmContextSourceItem>(r))
}

export function pmDeleteContextSource(projectId: number, sourceId: number) {
  return http.delete(`/pm/projects/${projectId}/context-sources/${sourceId}`).then((r) => unwrap<void>(r))
}

/** 某数字员工在本项目实际生效的上下文（项目级默认 + 员工专属，仅 enabled=1）。 */
export function pmAiScope(projectId: number, workerId?: number) {
  return http
    .get(`/pm/projects/${projectId}/ai-scope`, { params: workerId ? { workerId } : {} })
    .then((r) => unwrap<PmAiScope>(r))
}

// ============================================================ 错误文案

/**
 * 统一取 PM 接口的错误文案。
 *
 * <p>必须同时处理两类异常：{@code ApiError}（HTTP 200 + code≠0，message 即后端业务文案，
 * 如「业务项目不支持代码仓库配置」）与 axios 错误（读 {@code response.data.message}）。
 * 只处理后者会把所有业务规则提示吞成「操作失败」。</p>
 */
export function pmErrMsg(e: unknown, fallback = '操作失败'): string {
  const any = e as {
    response?: { status?: number; data?: { message?: string } }
    message?: string
  } | null
  const fromBody = any?.response?.data?.message
  if (fromBody) return fromBody
  if (any?.message && !/^Request failed with status code/.test(any.message)) {
    return any.message
  }
  const status = any?.response?.status
  if (status === 403) return '没有权限执行该操作'
  if (status === 404) return '资源不存在或不属于当前企业'
  if (status === 401) return '登录态已失效，请重新登录'
  return fallback
}
