import { http, unwrap } from './index'

/**
 * Gitee 仓库联动（V48）。
 *
 * <p>本文件是「后端 {@code aioa-gitee} 模块 REST 契约」在前端的唯一映射入口。
 * 字段名与后端 {@code GiteeController} / {@code GiteeOauthController} 返回的
 * {@code Map<String,Object>} **逐字对应**，不在视图里另起一套类型或字面量。</p>
 *
 * <p><b>错误口径</b>：Gitee 侧失败（限流 429 / 令牌失效 424 / 服务不可达 503）
 * 被 {@code GiteeExceptionAdvice} 映射成<b>业务错误</b> —— HTTP 200 + {@code code≠0}，
 * 由 {@code unwrap} 抛出 {@link ApiError}。因此视图里的 catch 必须同时处理两类异常：
 * {@code ApiError}（读 {@code .message}）与 axios 错误（读 {@code .response.data.message}）。
 * 用 {@link giteeErrMsg} 统一取文案，否则限流提示会被吞成通用失败。</p>
 */

// ============================================================ 元信息

/** 前端初始化信息，决定「仓库联动」入口与按钮可用性。 */
export interface GiteeConfig {
  /**
   * 当前生效的托管方标识（`gitee` / `gitea`）。
   *
   * <p>界面文案必须用它，不能写死「Gitee」：本平台可挂 Gitee 与 Gitea 两个托管方，
   * 写死会让页面在 gitea 接线下**谎报**托管方（见 `providerLabel`）。</p>
   */
  provider?: string
  /** 托管方展示名（`Gitee` / `Gitea`），与 `provider` 同源，由后端给出。 */
  providerLabel?: string
  /** 该托管方在后端的配置前缀（`aioa.gitee` / `aioa.gitea`），用于「未启用」提示。 */
  configKey?: string
  /**
   * 企业初始化时对访问令牌权限的要求（整句文案）。
   *
   * <p>两个平台的权限模型不同：Gitee 的 PAT 讲 `projects` 这类 scope，
   * Gitea 的个人令牌是「仓库 / 组织 / 用户 / 其他」勾选项。写死 Gitee 的说法
   * 会让 Gitea 用户在令牌页上找不到对应选项。</p>
   */
  tokenRequirementHint?: string
  /** 模块总开关；false 时整块功能不可用。 */
  enabled: boolean
  /** 后端是否配置了 Gitee 组织（建仓的 owner 来源）。 */
  orgConfigured: boolean
  /** 是否配置了 Webhook 回调基址；否则建仓后无法自动挂 Webhook。 */
  webhookBaseUrlConfigured: boolean
  /** 定时校准是否开启。 */
  syncEnabled: boolean
  /** 删除项目时是否默认连仓删除（生产默认 false）。 */
  purgeRepoOnDelete: boolean
  /** 可选仓库角色，与后端 {@code /config} 同源。 */
  roleOptions: Array<{ value: string; label: string }>
}

/** 建项目时可选的归属部门（受组织作用域限制）。 */
export interface GiteeDepartment {
  id: number
  name?: string
  institutionId?: number
  /** 仓库名命名空间前缀，如 `dept11-`，体现部门隔离。 */
  namespace?: string
}

/** 异步任务队列概况（排障用，仅租户管理员可读）。 */
export interface GiteeTaskStats {
  PENDING?: number
  RUNNING?: number
  DONE?: number
  FAILED?: number
  /** 处理该队列的 worker 标识。 */
  worker?: string
}

// ============================================================ 项目

export interface GiteeProject {
  id: number
  departmentId?: number
  teamId?: number
  name?: string
  /** 仓库 path（含部门命名空间前缀）。 */
  repoName?: string
  description?: string
  /** private | public */
  visibility?: string
  /** CREATING | ACTIVE | FAILED | DELETED */
  status?: string
  /** 建仓失败原因（status=FAILED 时有值）。 */
  errorMsg?: string
  purgeRepo?: boolean
  giteeOwner?: string
  giteeRepo?: string
  defaultBranch?: string
  /** Gitee 网页地址，用于「跳转 Gitee」。 */
  htmlUrl?: string
  sshUrl?: string
  httpsUrl?: string
  createdBy?: number
  createdAt?: string
}

export interface GiteeRepository {
  owner?: string
  repo?: string
  htmlUrl?: string
  sshUrl?: string
  httpsUrl?: string
  defaultBranch?: string
  /** `git clone <ssh>`，仅建仓成功后返回。 */
  cloneCommand?: string
}

export interface GiteeWebhook {
  /** Webhook 是否已挂上。 */
  configured: boolean
  hookId?: number
  /** 已订阅事件（字符串数组）。 */
  events?: string[] | string
  secretConfigured?: boolean
}

export interface GiteeProjectDetail {
  project: GiteeProject
  repository: GiteeRepository
  webhook: GiteeWebhook
  members: GiteeMember[]
  /** 当前用户对该项目是否可管理（后端按部门作用域判定）。 */
  canManage: boolean
}

// ============================================================ 成员

export interface GiteeMember {
  id: number
  projectId?: number
  userId?: number
  giteeUid?: number
  /** 未绑定 Gitee 的成员为 null（占位不造假值）。 */
  giteeUsername?: string | null
  /** READ | WRITE | ADMIN */
  role?: string
  /** PLATFORM（由平台授予） | GITEE（在 Gitee 侧直接添加）。 */
  source?: string
  /** SYNCED | PENDING | FAILED */
  syncStatus?: string
  lastError?: string
  syncedAt?: string
  createdAt?: string
  /** 是否来自 Gitee 侧直接操作（external=true 表示平台未登记）。 */
  external?: boolean
}

/** 可添加成员候选（本租户已绑定 Gitee 的成员）。 */
export interface GiteeMemberCandidate {
  userId: number
  name?: string
  departmentId?: number
  institutionId?: number
  jobTitle?: string
  employeeNo?: string
  giteeUsername?: string
  giteeName?: string
  alreadyMember: boolean
  /** alreadyMember=true 时的既有成员行 id。 */
  memberId?: number | null
  role?: string | null
}

// ============================================================ 内容与事件

export interface GiteeBranch {
  name?: string
  protected?: boolean
  lastSha?: string
}

export interface GiteeBranchesResult {
  projectId: number
  defaultBranch?: string
  items: GiteeBranch[]
  total: number
  /** Gitee 不可用时的降级标记：只回默认分支，页面应提示而非报错。 */
  degraded?: boolean
  degradedReason?: string
}

/** 目录条目（kind='dir' 时的 items 元素）。 */
export interface GiteeContentEntry {
  name?: string
  path?: string
  /** file | dir */
  type?: string
  size?: number
  sha?: string
}

export interface GiteeContentsResult {
  projectId: number
  path: string
  ref?: string
  /** dir = 目录列表（看 items）；file = 单文件（看 name/text）。 */
  kind: 'dir' | 'file'
  items?: GiteeContentEntry[]
  total?: number
  name?: string
  size?: number
  sha?: string
  downloadUrl?: string
  /** 二进制/过大文件不回正文。 */
  binary?: boolean
  contentOmitted?: boolean
  text?: string | null
  /**
   * 路径在该 ref 上不存在（典型：新建仓库还是空的）。后端把 Gitee 的 404 **降级为空目录**
   * 而不是抛错，所以这里是一个正常空态、不是故障 —— 不要用它弹错误提示。
   */
  empty?: boolean
  /** 空态的中文说明（后端给的原因）。 */
  note?: string
}

export interface GiteeCommitItem {
  sha?: string
  shortSha?: string
  branch?: string
  message?: string
  authorName?: string
  authorEmail?: string
  /** 映射到的平台用户 id（本地 push 的提交为 null）。 */
  authorUserId?: number | null
  /** WEB（网页上传） | GIT（本地推送）。 */
  source?: string
  committedAt?: string
}

export interface GiteeEventItem {
  id: number
  /** PUSH | MERGE_REQUEST | ISSUE | NOTE | OTHER */
  eventType?: string
  /** Gitee 原始事件名（如 Push Hook）。 */
  giteeEvent?: string
  action?: string
  title?: string
  summary?: string
  refName?: string
  commitSha?: string
  shortSha?: string
  actorLogin?: string
  actorGiteeUid?: number
  /** 身份映射结果：映射到平台用户的 id，未映射为 null。 */
  actorUserId?: number | null
  actorMapped?: boolean
  occurredAt?: string
  receivedAt?: string
}

export interface GiteePage<T> {
  projectId: number
  items: T[]
  total: number
  page: number
  size: number
}

/** 网页上传提交的返回。 */
export interface GiteeUploadResult {
  projectId: number
  path: string
  branch: string
  sha: string
  shortSha: string
  commitId?: number
  /** 恒为 WEB。 */
  source: string
  htmlUrl?: string
}

// ============================================================ 绑定

export interface GiteeBinding {
  /** 模块总开关。 */
  enabled: boolean
  bound: boolean
  giteeUid?: number
  giteeUsername?: string
  giteeName?: string
  avatarUrl?: string
  scope?: string
  boundAt?: string
  refreshedAt?: string
  tokenExpiresAt?: string
  /** 令牌已过期（等待自动刷新或需重新绑定）。 */
  tokenExpired?: boolean
  hasRefreshToken?: boolean
}

export interface GiteeAuthorizeResult {
  /** 授权跳转地址（前端整页跳转）。 */
  url: string
  state: string
  expiresInSeconds: number
  note?: string
  /** 授权跳转落地的域名（如 gitee.com 或 127.0.0.1）。 */
  authorizeHost?: string
  /** true = 授权域不是 gitee.com（本地桩/代理），本次不会到达真实 Gitee。 */
  sandbox?: boolean
  /** sandbox 为 true 时的显式告警文案（后端给出，前端勿另起一份）。 */
  warning?: string
}

// ============================================================ 企业（租户）级 Gitee 组织

/**
 * 企业（租户）维度的 Gitee 组织配置。
 *
 * <p>隔离口径：**每个入驻企业一个 Gitee 组织**。同一企业内各部门仍用仓库命名空间
 * （`dept<id>-` 前缀）隔离；跨企业则落到各自的组织里。</p>
 *
 * <p>回落规则：租户未配置时回落到平台默认组织（`aioa.gitee.org`），
 * 因此 `source=DEFAULT` 是正常状态而不是"未配置错误"——既有租户与演示环境零改动。</p>
 *
 * <p>OAuth 应用仍是**平台统一**一套（`client_id`/`client_secret` 不按租户区分），
 * 所以这里没有凭据字段：企业只需要填自己的组织名。</p>
 */
export interface GiteeTenantConfig {
  tenantId: number
  /** 当前**生效**的组织（自配置优先，否则平台默认）。 */
  orgName?: string
  /** TENANT = 企业自配置；DEFAULT = 回落平台默认。 */
  source?: 'TENANT' | 'DEFAULT' | string
  /** 企业是否已单独配置组织。 */
  configured?: boolean
  /** 企业级开关（关闭后该企业建仓等写操作被拒）。 */
  enabled?: boolean
  /** 平台默认组织（`aioa.gitee.org`），用于提示"未配置时会落到这里"。 */
  defaultOrg?: string
  /** 保存后返回的校验结论：组织是否存在且当前账号可见（**仅提示，不阻断保存**）。 */
  orgVerified?: boolean
  verifyMessage?: string
}

// ============================================================ 企业（租户）级 Gitee 初始化

/**
 * 企业（租户）维度的 Gitee 初始化状态视图。
 *
 * <p>与「本企业 Gitee 组织」不同，这里走的是<b>企业主动初始化</b>：企业用自己的
 * <b>访问令牌 + 组织登录名</b>初始化，不依赖个人 OAuth 绑定。后端契约已冻结，字段名
 * 一字不差；业务错误口径同 {@link giteeErrMsg}（HTTP 200 + {@code code≠0} →
 * {@link ApiError}）。</p>
 *
 * <p>注意：状态视图<b>不返回令牌本身</b>；{@code tokenConfigured} 仅表示是否已配置企业令牌。</p>
 */
export interface GiteeInitStatus {
  /** 租户 id。 */
  tenantId?: number
  /**
   * 是否已成功初始化（等价于 {@code initStatus === 'ACTIVE'}）。
   *
   * <p>PENDING（未初始化/已撤销）与 FAILED（初始化失败）均为 false。</p>
   */
  initialized?: boolean
  /** PENDING | ACTIVE | FAILED。无配置行的租户也归一化为 PENDING（后端不留 null）。 */
  initStatus?: 'PENDING' | 'ACTIVE' | 'FAILED' | string
  /** 初始化完成时间。 */
  initAt?: string
  /** 初始化操作人。 */
  initBy?: string
  /** 生效组织登录名。 */
  orgName?: string
  /** TENANT = 企业自配置；DEFAULT = 回落平台默认。 */
  source?: 'TENANT' | 'DEFAULT' | string
  /** 是否已配置组织。 */
  configured?: boolean
  /** 企业级联动开关。 */
  enabled?: boolean
  /** 令牌所属 Gitee 账号（仅展示，不回令牌）。 */
  tokenOwner?: string
  /** 令牌范围。 */
  tokenScope?: string
  /** 组织校验是否通过。 */
  orgVerified?: boolean
  /** 失败原因（initStatus=FAILED 时有值，后端已把失败步骤原因写在这里）。 */
  lastError?: string
  /** 最近一次检查时间。 */
  lastCheckAt?: string
  /** 平台默认组织（回落基址）。 */
  defaultOrg?: string
  /** 是否已配置企业令牌（仅展示）。 */
  tokenConfigured?: boolean
}

/** 初始化/校验的逐步结论（steps 中的单步）。 */
export interface GiteeInitStep {
  /** 步骤编码。 */
  code?: string
  /** 步骤名（中文）。 */
  label?: string
  /** 该步是否通过。 */
  ok?: boolean
  /** 该步说明（失败时有原因）。 */
  message?: string
}

/** verify / initialize 的返回：状态视图 + 逐步 steps + 顶层诊断结论。 */
export type GiteeInitResult = GiteeInitStatus & {
  /** 逐步结论（与 passed 同源）。 */
  steps?: GiteeInitStep[]
  /** 顶层判据：steps 全 ok 才为 true。权威，优先于前端本地推导。 */
  passed?: boolean
  /** 首个失败步的 code（passed=true 时为 null）。 */
  failedStep?: string | null
  /** 首个失败步的原因。 */
  failedMessage?: string | null
  /** true = 仅校验未落库（verify）；false = 已落库（initialize）。 */
  verifyOnly?: boolean
}

// ============================================================ 错误文案

/**
 * 统一取错误文案。
 *
 * <p>必须先看 {@code response}（axios HTTP 错误）再看 {@code message}：
 * {@code ApiError} 没有 {@code response}，而 axios 错误的 {@code message}
 * 恒为 "Request failed with status code xxx"，直接取会丢掉后端真实原因。</p>
 */
export function giteeErrMsg(e: unknown, fallback = '操作失败'): string {
  const any = e as {
    response?: { status?: number; data?: { message?: string } }
    message?: string
  } | null
  const fromBody = any?.response?.data?.message
  if (fromBody) return fromBody
  // ApiError：message 是后端业务文案（如「Gitee 接口被限流，请稍后重试」）
  if (any?.message && !/^Request failed with status code/.test(any.message)) {
    return any.message
  }
  const status = any?.response?.status
  if (status === 403) return '没有权限执行该操作'
  if (status === 404) return '资源不存在或不属于当前租户'
  if (status === 401) return '登录态已失效，请重新登录'
  return fallback
}

// ============================================================ API

/** 模块与组织配置概况。 */
export function giteeConfig() {
  return http.get('/gitee/config').then((r) => unwrap<GiteeConfig>(r))
}

/** 建项目时可选的归属部门。 */
export function giteeDepartments() {
  return http.get('/gitee/departments').then((r) => unwrap<GiteeDepartment[]>(r))
}

/** 异步任务队列概况（仅租户管理员）。 */
export function giteeTaskStats() {
  return http.get('/gitee/tasks/stats').then((r) => unwrap<GiteeTaskStats>(r))
}

/** 手动触发一次成员校准（仅租户管理员；平台管理员为全租户）。 */
export function giteeCalibrate() {
  return http.post('/gitee/calibrate').then((r) =>
    unwrap<{ enqueued: number; scope: string; note: string }>(r)
  )
}

/** 项目列表（一次回全量，无分页；支持部门与关键字过滤）。 */
export function giteeProjects(params: { departmentId?: number; keyword?: string } = {}) {
  return http
    .get('/gitee/projects', { params })
    .then((r) => unwrap<{ items: GiteeProject[]; total: number; canCreate: boolean }>(r))
}

/** 新建项目：同步返回「创建中」，建仓与挂 Webhook 在后台完成。 */
export function giteeCreateProject(body: {
  name: string
  departmentId: number
  description?: string
  /** 默认 private。 */
  visibility?: 'private' | 'public'
  purgeRepo?: boolean
}) {
  return http
    .post('/gitee/projects', body)
    .then((r) =>
      unwrap<{ id: number; status: string; repoName: string; project: GiteeProject; note: string }>(r)
    )
}

/** 项目详情：项目 + 仓库 + Webhook + 成员。 */
export function giteeProjectDetail(projectId: number) {
  return http.get(`/gitee/projects/${projectId}`).then((r) => unwrap<GiteeProjectDetail>(r))
}

/** 建仓失败后重试。 */
export function giteeRetryProject(projectId: number) {
  return http.post(`/gitee/projects/${projectId}/retry`).then((r) => unwrap<GiteeProject>(r))
}

/** 删除项目（软删；purgeRepo=true 时同时删 Gitee 仓库，不可恢复）。 */
export function giteeDeleteProject(projectId: number, purgeRepo?: boolean) {
  return http
    .delete(`/gitee/projects/${projectId}`, { params: purgeRepo == null ? {} : { purgeRepo } })
    .then((r) => unwrap<{ deleted: boolean; purgeRepo: boolean; note: string }>(r))
}

/** 项目成员列表。 */
export function giteeMembers(projectId: number) {
  return http
    .get(`/gitee/projects/${projectId}/members`)
    .then((r) => unwrap<{ items: GiteeMember[]; total: number }>(r))
}

/** 可添加成员候选。 */
export function giteeMemberCandidates(projectId: number, keyword?: string) {
  return http
    .get(`/gitee/projects/${projectId}/members/candidates`, { params: { keyword } })
    .then((r) => unwrap<{ items: GiteeMemberCandidate[]; total: number }>(r))
}

/** 添加成员（异步同步 Gitee 协作者权限）。 */
export function giteeAddMember(
  projectId: number,
  body: { userId: number; role: string; giteeUsername?: string }
) {
  return http
    .post(`/gitee/projects/${projectId}/members`, body)
    .then((r) => unwrap<GiteeMember & { note?: string }>(r))
}

/** 移除成员（异步回收 Gitee 协作者权限）。 */
export function giteeRemoveMember(projectId: number, memberId: number) {
  return http
    .delete(`/gitee/projects/${projectId}/members/${memberId}`)
    .then((r) => unwrap<{ removed: boolean; memberId: number; note: string }>(r))
}

/** 分支列表（Gitee 不可用时 degraded=true，只回默认分支）。 */
export function giteeBranches(projectId: number) {
  return http.get(`/gitee/projects/${projectId}/branches`).then((r) => unwrap<GiteeBranchesResult>(r))
}

/** 目录 / 文件内容。 */
export function giteeContents(projectId: number, params: { path?: string; ref?: string } = {}) {
  return http
    .get(`/gitee/projects/${projectId}/contents`, { params })
    .then((r) => unwrap<GiteeContentsResult>(r))
}

/** 网页上传提交（提交方式①）。 */
export function giteeUpload(
  projectId: number,
  body: { path: string; content: string; message?: string; branch?: string }
) {
  return http
    .post(`/gitee/projects/${projectId}/contents`, body)
    .then((r) => unwrap<GiteeUploadResult>(r))
}

/** 提交记录（网页上传 + 本地 push 合流）。 */
export function giteeCommits(
  projectId: number,
  params: { branch?: string; page?: number; size?: number } = {}
) {
  return http
    .get(`/gitee/projects/${projectId}/commits`, { params })
    .then((r) => unwrap<GiteePage<GiteeCommitItem>>(r))
}

/** 事件流（push / 合并请求 / 任务 / 评论）。 */
export function giteeEvents(
  projectId: number,
  params: { eventType?: string; page?: number; size?: number } = {}
) {
  return http
    .get(`/gitee/projects/${projectId}/events`, { params })
    .then((r) => unwrap<GiteePage<GiteeEventItem>>(r))
}

/** 我的 Gitee 绑定状态。 */
export function giteeMyBinding() {
  return http.get('/gitee/bind').then((r) => unwrap<GiteeBinding>(r))
}

/** 生成授权跳转地址（拿到 url 后整页跳转，回调页会自动跳回平台）。 */
export function giteeAuthorize() {
  return http.post('/gitee/bind/authorize').then((r) => unwrap<GiteeAuthorizeResult>(r))
}

/** 解绑（删除本地令牌）。 */
export function giteeUnbind() {
  return http.delete('/gitee/bind').then((r) => unwrap<{ bound: boolean }>(r))
}

// ============================================================ 企业级组织配置

/**
 * 读取本企业的 Gitee 组织配置（租户管理员）。
 * `tenantId` 仅平台管理员可传（跨租户运维）；租户管理员省略即可，后端按登录租户取。
 */
export function giteeTenantConfig(tenantId?: number) {
  return http
    .get('/gitee/tenant-config', { params: tenantId == null ? {} : { tenantId } })
    .then((r) => unwrap<GiteeTenantConfig>(r))
}

/** 保存/更新本企业的 Gitee 组织。 */
export function giteeSaveTenantConfig(
  body: { orgName: string; enabled?: boolean },
  tenantId?: number
) {
  return http
    .post('/gitee/tenant-config', body, { params: tenantId == null ? {} : { tenantId } })
    .then((r) => unwrap<GiteeTenantConfig>(r))
}

/** 清除企业自配置，回落到平台默认组织。 */
export function giteeClearTenantConfig(tenantId?: number) {
  return http
    .delete('/gitee/tenant-config', { params: tenantId == null ? {} : { tenantId } })
    .then((r) => unwrap<GiteeTenantConfig>(r))
}

// ============================================================ 企业级初始化

/**
 * 读取企业 Gitee 初始化状态视图（租户管理员）。
 * 后端契约：GET /gitee/init。接口暂未部署时会 404（预期内），不应改契约或加兜底。
 */
export function giteeInitStatus() {
  return http.get('/gitee/init').then((r) => unwrap<GiteeInitStatus>(r))
}

/**
 * 校验企业令牌 + 组织名（不落库，可安全反复点）。
 * 后端契约：POST /gitee/init/verify  body { accessToken?, orgName }。
 */
export function giteeInitVerify(body: { accessToken?: string; orgName: string }) {
  return http.post('/gitee/init/verify', body).then((r) => unwrap<GiteeInitResult>(r))
}

/**
 * 正式初始化 / 重新初始化。
 * 后端契约：POST /gitee/init  body { accessToken?, orgName, enabled?, note?, rotateToken? }。
 * 填了令牌 → rotateToken=true（轮换）；留空 → rotateToken=false（沿用已有令牌）。
 */
export function giteeInitInitialize(body: {
  accessToken?: string
  orgName: string
  enabled?: boolean
  note?: string
  rotateToken?: boolean
}) {
  return http.post('/gitee/init', body).then((r) => unwrap<GiteeInitResult>(r))
}

/** 撤销企业初始化（清除企业令牌；不影响组织名与开关设置）。后端契约：DELETE /gitee/init。 */
export function giteeInitRevoke() {
  return http.delete('/gitee/init').then((r) => unwrap<GiteeInitStatus>(r))
}
