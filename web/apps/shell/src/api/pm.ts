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
