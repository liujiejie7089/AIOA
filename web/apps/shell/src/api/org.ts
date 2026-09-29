/**
 * V24 企业入驻域 API：租户端（/api/v1/tenant）+ 企业端（/api/v1/org）+ 审批工作流。
 *
 * 约定：后端统一 ApiResponse<T> = { code, message, data }，用 unwrap 剥到业务数据。
 * 业务校验失败为 HTTP 200 + code != 0；403/404 才是 HTTP 状态错误。
 */
import { http, unwrap } from './index'

// ================================================================== 类型
export interface Institution {
  id?: number
  tenantId?: number
  name?: string
  code?: string
  orgType?: string
  creditCode?: string
  legalPerson?: string
  contactMobile?: string
  contactEmail?: string
  establishedAt?: string
  adminUserId?: number
  adminName?: string
  adminUsername?: string
  status?: string
  onboardStep?: number
  remark?: string
  departmentCount?: number
  memberCount?: number
  // 新建时同步开户
  adminPassword?: string
}

/** 机构类型字典项（来自 `GET /tenant/institution-types`，后端唯一权威，顺序即展示顺序）。 */
export interface InstitutionType {
  code: string
  label: string
}

export interface OrgQuota {
  id?: number
  institutionId?: number
  institutionName?: string
  period?: string
  quotaTokens?: number
  freeTokens?: number
  usedTokens?: number
  remainTokens?: number
  frozen?: boolean | number
  effectiveFrom?: string
  effectiveTo?: string
  reason?: string
}

export interface ResourcePool {
  id?: number
  tenantId?: number
  period?: string
  /** 服务端是否已交付本周期资源池（未交付时其余字段全为 0） */
  delivered?: boolean
  status?: string
  tokenTotal?: number
  tokenUsed?: number
  tokenRemain?: number
  /** 服务端字段名就是 allocatedTokens；tokenAllocated 是历史误名，保留兼容读取 */
  allocatedTokens?: number
  tokenAllocated?: number
  allocatableTokens?: number
  allocRatio?: number
  usageRatio?: number
  expertSeats?: number
  expertUsed?: number
  skillSeats?: number
  skillUsed?: number
  warnThreshold?: number
  unitPrice?: number
  expireAt?: string
}

export interface QuotaChain {
  period?: string
  level1Pool?: ResourcePool
  level2Org?: OrgQuota[]
  summary?: Record<string, number>
}

export interface QuotaLog {
  id?: number
  institutionId?: number
  institutionName?: string
  action?: string
  beforeTokens?: number
  deltaTokens?: number
  afterTokens?: number
  reason?: string
  operatorName?: string
  operatorRole?: string
  createdAt?: string
}

export interface ResourceGrant {
  id?: number
  institutionId?: number
  resType?: string
  resId?: number
  resKey?: string
  resName?: string
  extra?: string
  enabled?: boolean | number
}

export interface GrantCatalog {
  experts?: { id: number; resKey: string; name: string }[]
  skills?: { id: number; resKey: string; name: string }[]
  models?: { id: number; resKey: string; name: string; providerKey?: string }[]
  /**
   * 知识库：可授权目录 = 本租户（含平台级）**租户共享**且尚未挂载到任何机构的资料。
   * 没有 resKey（kb_document 只有自增主键），后端下发的是 `name` 而非 docName。
   */
  kb?: { id: number; name: string; resKey?: string; scope?: string; state?: string; chunkCount?: number }[]
  workers?: { id: number; tenantId?: number; name: string; status?: string }[]
  /**
   * 可授权资源类型的**唯一权威清单**（后端 ResourceGrant.ALL_TYPES 下发）。
   * 前端下拉必须从这里取，不得再硬编码 —— 此前页面自己写死了 5 个选项，
   * 而后端 grant() 的白名单只有 4 个，导致「选了数字员工点保存必被拒」。
   */
  resTypes?: { code: string; name: string }[]
}

export interface CostRule {
  id?: number
  tenantId?: number
  name?: string
  ruleType?: string
  configJson?: string
  version?: number
  status?: string
  createdAt?: string
}

export interface CostBill {
  id?: number
  serialNo?: string
  institutionId?: number
  institutionName?: string
  period?: string
  ruleVersion?: number
  usageTokens?: number
  amount?: number
  status?: string
}

export interface OrgDepartment {
  id?: number
  institutionId?: number
  parentId?: number
  name?: string
  code?: string
  level?: number
  path?: string
  sort?: number
  status?: string
  leaderUserId?: number
  leaderName?: string
  memberCount?: number
  children?: OrgDepartment[]
}

/**
 * 员工账号（V67 批次 C）。一个员工可以有**多个**账号；`isPrimary=true` 那条是主账号
 * （服务端 `org_member.user_id`，通知/审批/鉴权/机构归属都读它）。
 */
export interface MemberAccount {
  userId?: number
  username?: string
  nickname?: string
  status?: string
  isPrimary?: boolean
}

/** 「给员工绑定账号」的候选（本租户账号清单）。 */
export interface AccountCandidate extends MemberAccount {
  /** 已绑定该员工姓名；为空表示**虚拟账号**（无任何员工绑定，即规格里的虚拟管理员账号）。 */
  boundMemberName?: string
  virtual?: boolean
}

export interface OrgMember {
  id?: number
  userId?: number
  institutionId?: number
  departmentId?: number
  departmentName?: string
  name?: string
  username?: string
  employeeNo?: string
  jobTitle?: string
  mobile?: string
  email?: string
  status?: string
  /**
   * V67 批次 C·补（口令可知性）：新增员工时的**初始登录口令**（只写不读）。
   * 留空 ⇒ 服务端使用统一演示口令 `User@123`。回执里不会带回该字段，操作员需自行留档。
   */
  password?: string
  /** V67 批次 C：该员工的全部账号（主账号排在最前）。列表与详情都会回吐，形状恒定存在。 */
  accounts?: MemberAccount[]
  /**
   * 是否企业管理员。列表与详情都会回吐（服务端 `view()` 里有该字段）。
   * 企业管理员**不可直接移除**（服务端会拒绝），须先在机构管理页完成管理员交接（FR-B2）。
   */
  isOrgAdmin?: boolean
}

export interface OnboardingStep {
  step: number
  key: string
  name: string
  owner: string
  gate: string
  /** 门禁**实时判定**是否通过（事实，不是"用户点过推进"）。 */
  passed: boolean
  reason?: string
  /** 由持久化游标 `onboardStep` 推出（"已确认推进到"），与 `passed` 口径不同，仅供回看。 */
  recorded?: boolean
  /** 第一个未通过的步骤（即"你现在该做的那一步"）。8 步中至多一个为 true。 */
  current?: boolean
  /** **前序步骤全部通过**才为 true；未解锁的步骤点了也没意义（体现步骤先后顺序）。 */
  unlocked?: boolean
  /** 未解锁时指向卡住它的那一步；已解锁为 null。 */
  blockedByStep?: number | null
  /** 该步骤对应的设置页面路由（后端权威下发，前端不得复刻）。 */
  route?: string
  routeLabel?: string
}

export interface OnboardingProgress {
  institutionId: number
  institutionName?: string
  totalSteps: number
  passedCount?: number
  percent?: number
  completed?: boolean
  /** 当前所处的步骤位置（第一个未通过步）；全部通过为 null。 */
  currentStep?: number | null
  currentStepName?: string
  nextAction?: string | null
  nextStepRoute?: string | null
  steps: OnboardingStep[]
}

export interface OnboardingStepDef {
  step: number
  key: string
  name: string
  owner: string
  gate: string
  route: string
  routeLabel: string
}

export interface OnboardingStepCatalog {
  totalSteps: number
  maxDeptDepth?: number
  note?: string
  steps: OnboardingStepDef[]
}

export interface ApprovalFlowDef {
  id?: number
  tenantId?: number
  institutionId?: number
  bizType?: string
  name?: string
  stepsJson?: string
  status?: string
  remark?: string
}

export interface WorkflowTask {
  id: number
  taskId: number
  bizType?: string
  title?: string
  status?: string
  seq?: number
  applicantName?: string
  createdAt?: string
}

// ================================================================== 租户端：机构
/** 机构类型字典（后端权威五类：GOVERNMENT/ENTERPRISE/INSTITUTION/ASSOCIATION/OTHER）。 */
export function listInstitutionTypes(): Promise<InstitutionType[]> {
  return http.get('/tenant/institution-types').then((r) => unwrap<InstitutionType[]>(r))
}
/**
 * 机构清单。
 *
 * <p><b>默认不含已注销机构</b>（注销 = 不可逆终态，退出运营面）。需要「档案 / 归档」视角时
 * 显式传 {@code includeClosed: true}（或 {@code status: 'CLOSED'}）。口径唯一权威在后端
 * {@code InstitutionStatus}，前端不得自行过滤 —— 否则「后端已排除、前端又摆出来」会来回打架。</p>
 */
export function listInstitutions(
  params?: { keyword?: string; status?: string; orgType?: string; includeClosed?: boolean }
): Promise<Institution[]> {
  return http.get('/tenant/institutions', { params }).then((r) => unwrap<Institution[]>(r))
}
export function createInstitution(body: Partial<Institution>): Promise<Institution> {
  return http.post('/tenant/institutions', body).then((r) => unwrap<Institution>(r))
}
export function updateInstitution(id: number, body: Partial<Institution>): Promise<Institution> {
  return http.put('/tenant/institutions/' + id, body).then((r) => unwrap<Institution>(r))
}
/** action: suspend | resume | close */
export function institutionAction(id: number, action: string, reason?: string): Promise<Institution> {
  return http.post('/tenant/institutions/' + id + '/' + action, { reason }).then((r) => unwrap<Institution>(r))
}
export function transferInstitutionAdmin(id: number, username: string, name: string): Promise<Institution> {
  return http.post('/tenant/institutions/' + id + '/admin', { username, name }).then((r) => unwrap<Institution>(r))
}

// ================================================================== 租户端：资源池与配额
export function getResourcePool(period: string): Promise<ResourcePool> {
  return http.get('/tenant/resource-pool', { params: { period } }).then((r) => unwrap<ResourcePool>(r))
}
export function saveResourcePool(body: Partial<ResourcePool>): Promise<ResourcePool> {
  return http.post('/tenant/resource-pool', body).then((r) => unwrap<ResourcePool>(r))
}
export function listOrgQuotas(period: string): Promise<OrgQuota[]> {
  return http.get('/tenant/org-quotas', { params: { period } }).then((r) => unwrap<OrgQuota[]>(r))
}
export function createOrgQuota(body: Partial<OrgQuota>): Promise<OrgQuota> {
  return http.post('/tenant/org-quotas', body).then((r) => unwrap<OrgQuota>(r))
}
export function deltaOrgQuota(institutionId: number, body: Record<string, unknown>): Promise<OrgQuota> {
  return http.post('/tenant/org-quotas/' + institutionId + '/delta', body).then((r) => unwrap<OrgQuota>(r))
}
export function freezeOrgQuota(institutionId: number, reason?: string): Promise<OrgQuota> {
  return http.post('/tenant/org-quotas/' + institutionId + '/freeze', { reason }).then((r) => unwrap<OrgQuota>(r))
}
export function unfreezeOrgQuota(institutionId: number, reason?: string): Promise<OrgQuota> {
  return http.post('/tenant/org-quotas/' + institutionId + '/unfreeze', { reason }).then((r) => unwrap<OrgQuota>(r))
}
export function getQuotaChain(period: string): Promise<QuotaChain> {
  return http.get('/tenant/quota-chain', { params: { period } }).then((r) => unwrap<QuotaChain>(r))
}
export function getQuotaWarnings(period: string): Promise<Record<string, unknown>> {
  return http.get('/tenant/quota-warnings', { params: { period } }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function listQuotaLogs(params?: Record<string, unknown>): Promise<QuotaLog[]> {
  return http.get('/tenant/quota-logs', { params }).then((r) => unwrap<QuotaLog[]>(r))
}

// ================================================================== 租户端：资源授权
export function getGrantCatalog(): Promise<GrantCatalog> {
  return http.get('/tenant/grants/catalog').then((r) => unwrap<GrantCatalog>(r))
}
export function listGrants(institutionId?: number): Promise<ResourceGrant[]> {
  return http.get('/tenant/grants', { params: institutionId ? { institutionId } : {} }).then((r) => unwrap<ResourceGrant[]>(r))
}
export function createGrant(body: Partial<ResourceGrant>): Promise<ResourceGrant> {
  return http.post('/tenant/grants', body).then((r) => unwrap<ResourceGrant>(r))
}
export function batchGrant(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return http.post('/tenant/grants/batch', body).then((r) => unwrap<Record<string, unknown>>(r))
}
/**
 * 启用 / 停用一条资源授权。
 *
 * <p>必须**显式传目标状态**：后端在缺省时会「按当前值翻转」，前端带上期望值才能
 * 保证「我点的是停用，结果就是停用」——也可避免连点两次来回抖动。</p>
 */
export function toggleGrant(id: number, enabled: boolean): Promise<ResourceGrant> {
  return http.post('/tenant/grants/' + id + '/toggle', { enabled }).then((r) => unwrap<ResourceGrant>(r))
}
export function deleteGrant(id: number): Promise<unknown> {
  return http.delete('/tenant/grants/' + id).then((r) => unwrap<unknown>(r))
}

// ================================================================== 租户端：费用分摊
export function listCostRules(): Promise<CostRule[]> {
  return http.get('/tenant/cost-rules').then((r) => unwrap<CostRule[]>(r))
}
export function createCostRule(body: Record<string, unknown>): Promise<CostRule> {
  return http.post('/tenant/cost-rules', body).then((r) => unwrap<CostRule>(r))
}
export function updateCostRule(id: number, body: Record<string, unknown>): Promise<CostRule> {
  return http.put('/tenant/cost-rules/' + id, body).then((r) => unwrap<CostRule>(r))
}
export function simulateCostRule(id: number, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return http.post('/tenant/cost-rules/' + id + '/simulate', body).then((r) => unwrap<Record<string, unknown>>(r))
}
export function listCostBills(period: string): Promise<CostBill[]> {
  return http.get('/tenant/cost-bills', { params: { period } }).then((r) => unwrap<CostBill[]>(r))
}
export function generateCostBills(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return http.post('/tenant/cost-bills/generate', body).then((r) => unwrap<Record<string, unknown>>(r))
}
export function reconcileCostBills(period: string): Promise<Record<string, unknown>> {
  return http.get('/tenant/cost-bills/reconcile', { params: { period } }).then((r) => unwrap<Record<string, unknown>>(r))
}

// ================================================================== 租户端：总览 / 审计 / 入驻
export function getTenantOverview(period: string): Promise<Record<string, unknown>> {
  return http.get('/tenant/overview', { params: { period } }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function getOnboardingOverview(): Promise<Record<string, unknown>> {
  return http.get('/tenant/onboarding').then((r) => unwrap<Record<string, unknown>>(r))
}
/** 8 步的**静态定义**（序号/名称/责任方/门禁/目标页面），后端唯一权威。 */
export function getOnboardingSteps(): Promise<OnboardingStepCatalog> {
  return http.get('/tenant/onboarding/steps').then((r) => unwrap<OnboardingStepCatalog>(r))
}
export function getOnboardingProgress(institutionId: number): Promise<OnboardingProgress> {
  return http.get('/tenant/onboarding/' + institutionId + '/progress').then((r) => unwrap<OnboardingProgress>(r))
}
export function advanceOnboardingAll(institutionId: number): Promise<Record<string, unknown>> {
  return http.post('/tenant/onboarding/' + institutionId + '/advance-all').then((r) => unwrap<Record<string, unknown>>(r))
}
export function listApprovalFlowDefs(institutionId?: number): Promise<ApprovalFlowDef[]> {
  // 注意：用 `!= null` 而非真值判断 —— institutionId=0 是**租户级**默认流的合法取值，
  // 用真值判断会把 0 丢掉而返回全部（含机构级）流程。
  return http.get('/tenant/approval-flow-defs', { params: institutionId != null ? { institutionId } : {} })
    .then((r) => unwrap<ApprovalFlowDef[]>(r))
}
export function saveApprovalFlowDef(body: Record<string, unknown>): Promise<ApprovalFlowDef> {
  return http.post('/tenant/approval-flow-defs', body).then((r) => unwrap<ApprovalFlowDef>(r))
}

// ================================================================== 企业端：组织与员工
//
// 机构作用域（V32）：机构成员只能看本机构；租户管理员可在本租户内切换机构；
// 平台管理员可跨租户切换（只读）。所有 /org/* 接口都接受可选的 institutionId。
export interface SelectableInstitution {
  id: number
  name?: string
  code?: string
  tenantId?: number
  status?: string
}

export interface OrgScope {
  items: SelectableInstitution[]
  total?: number
  /** 当前账号是否可维护组织与员工（企业管理员 / 租户管理员为 true，平台管理员只读） */
  canWrite: boolean
  /** 机构成员硬绑定的机构 id；租户/平台管理员为 null */
  boundInstitutionId?: number | null
  /** ORG（机构成员）/ TENANT（租户管理员）/ PLATFORM（平台管理员） */
  scope?: string
}

/** 把机构 id 转成 axios params（null/undefined 时不带该参数，由后端按作用域兜底）。 */
function inst(institutionId?: number | null): Record<string, unknown> {
  return institutionId ? { institutionId } : {}
}

export function getOrgScope(): Promise<OrgScope> {
  return http.get('/org/institutions').then((r) => unwrap<OrgScope>(r))
}
export function getOrgProfile(institutionId?: number | null): Promise<Record<string, unknown>> {
  return http.get('/org/profile', { params: inst(institutionId) }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function getDepartments(institutionId?: number | null): Promise<{ tree: OrgDepartment[]; total?: number; depthLimit?: number; maxDepth?: number }> {
  return http.get('/org/departments', { params: inst(institutionId) })
    .then((r) => unwrap<{ tree: OrgDepartment[]; total?: number; depthLimit?: number; maxDepth?: number }>(r))
}
export function createDepartment(body: Partial<OrgDepartment>, institutionId?: number | null): Promise<OrgDepartment> {
  return http.post('/org/departments', body, { params: inst(institutionId) }).then((r) => unwrap<OrgDepartment>(r))
}
export function updateDepartment(id: number, body: Partial<OrgDepartment>, institutionId?: number | null): Promise<OrgDepartment> {
  return http.put('/org/departments/' + id, body, { params: inst(institutionId) }).then((r) => unwrap<OrgDepartment>(r))
}
/**
 * 申请删除部门（审批人 = 上一级）。前置：该部门下无子部门、无员工。
 *
 * ★ 这里**没有** `deleteDepartment`：需求要求「任何一层级的首次删除操作都需要经过上一级审核
 *   后方可执行」，部门也是其中一层。原先的 `DELETE /org/departments/{id}` 已下线 ——
 *   留着它就是留了一条绕过审核的快捷通道，前端只要调它就等于没审核。
 */
export function requestDepartmentDelete(
  id: number, reason?: string, institutionId?: number | null
): Promise<DeleteRequestResult> {
  return http.post('/org/departments/' + id + '/delete-request', { reason }, { params: inst(institutionId) })
    .then((r) => unwrap<DeleteRequestResult>(r))
}
export function moveDepartment(id: number, parentId: number, institutionId?: number | null): Promise<OrgDepartment> {
  return http.post('/org/departments/' + id + '/move', { parentId }, { params: inst(institutionId) })
    .then((r) => unwrap<OrgDepartment>(r))
}
export function listMembers(params?: Record<string, unknown>, institutionId?: number | null): Promise<{ items: OrgMember[]; total?: number }> {
  return http.get('/org/members', { params: { ...inst(institutionId), ...(params || {}) } })
    .then((r) => unwrap<{ items: OrgMember[]; total?: number }>(r))
}
/**
 * 新增员工（不存在则自动开户）。
 *
 * 回执多一个**只在此次新建账号时出现**的 `initialPassword`（明文，供操作员留档）。
 * 账号此前已存在时该键缺席 —— 因为那时口令并没有被改动，回显一个"初始口令"就是假话。
 */
export function createMember(body: Partial<OrgMember>, institutionId?: number | null): Promise<OrgMember & { initialPassword?: string }> {
  return http.post('/org/members', body, { params: inst(institutionId) }).then((r) => unwrap<OrgMember & { initialPassword?: string }>(r))
}
export function updateMember(id: number, body: Partial<OrgMember>, institutionId?: number | null): Promise<OrgMember> {
  return http.put('/org/members/' + id, body, { params: inst(institutionId) }).then((r) => unwrap<OrgMember>(r))
}
export function deleteMember(id: number, institutionId?: number | null): Promise<unknown> {
  return http.delete('/org/members/' + id, { params: inst(institutionId) }).then((r) => unwrap<unknown>(r))
}
/** 批量导入回执。`newAccounts > 0` 时才会带 `initialPassword`（后端权威下发，前端不得自行硬编码）。 */
export interface MemberImportResult {
  total: number
  success: number
  failedCount: number
  successRate: number
  failed: { row: number; name?: string; reason: string }[]
  /** 本次真正**新建**（或复活）的账号数 —— 已存在的账号不计入。 */
  newAccounts?: number
  /** 本次新建账号的统一初始口令。 */
  initialPassword?: string
}
export function importMembers(rows: Record<string, unknown>[], institutionId?: number | null): Promise<MemberImportResult> {
  return http.post('/org/members/import', { rows }, { params: inst(institutionId) }).then((r) => unwrap<MemberImportResult>(r))
}

/** 重置员工**主账号**的登录口令回执；`initialPassword` 为本次生效的明文口令，仅供当场留档。 */
export interface MemberPasswordReset {
  memberId: number
  userId: number
  initialPassword: string
}
/**
 * 重置员工主账号的登录口令。
 *
 * 开户口令只在创建那一刻回显一次（服务端只存哈希）；漏记后必须走这里就地重置，
 * 而不是"删掉员工重建"（那会连带丢掉审批 / 通知归属）。
 */
export function resetMemberPassword(id: number, password: string, institutionId?: number | null): Promise<MemberPasswordReset> {
  return http.post('/org/members/' + id + '/password', { password }, { params: inst(institutionId) })
    .then((r) => unwrap<MemberPasswordReset>(r))
}

// ---- V67 批次 C：员工 ↔ 账号（多对多）----
/** 本租户账号清单（绑定候选）；`virtual=true` 的是无员工绑定的「虚拟账号」。 */
export function listAccountCandidates(keyword?: string): Promise<AccountCandidate[]> {
  return http.get('/org/accounts', { params: keyword ? { keyword } : {} })
    .then((r) => unwrap<AccountCandidate[]>(r))
}
/** 给员工追加绑定一个账号（不改变主账号）；返回该员工绑定后的全部账号。 */
export function attachMemberAccount(memberId: number, userId: number, institutionId?: number | null): Promise<MemberAccount[]> {
  return http.post('/org/members/' + memberId + '/accounts', { userId }, { params: inst(institutionId) })
    .then((r) => unwrap<MemberAccount[]>(r))
}
/** 解绑员工的**附加**账号（主账号不可解绑，由服务端给出明确文案）。 */
export function detachMemberAccount(memberId: number, userId: number, institutionId?: number | null): Promise<MemberAccount[]> {
  return http.delete('/org/members/' + memberId + '/accounts/' + userId, { params: inst(institutionId) })
    .then((r) => unwrap<MemberAccount[]>(r))
}
export function listDeptQuotas(period: string, institutionId?: number | null): Promise<Record<string, unknown>[]> {
  return http.get('/org/dept-quotas', { params: { period, ...inst(institutionId) } }).then((r) => unwrap<Record<string, unknown>[]>(r))
}
export function createDeptQuota(body: Record<string, unknown>, institutionId?: number | null): Promise<Record<string, unknown>> {
  return http.post('/org/dept-quotas', body, { params: inst(institutionId) }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function getOrgQuota(period: string, institutionId?: number | null): Promise<OrgQuota> {
  return http.get('/org/org-quota', { params: { period, ...inst(institutionId) } }).then((r) => unwrap<OrgQuota>(r))
}
export function getOrgUsage(period: string, institutionId?: number | null): Promise<Record<string, unknown>> {
  return http.get('/org/usage', { params: { period, ...inst(institutionId) } }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function applyQuotaExpand(tokens: number, reason: string, institutionId?: number | null): Promise<Record<string, unknown>> {
  return http.post('/org/applications/quota-expand', { tokens, reason }, { params: inst(institutionId) })
    .then((r) => unwrap<Record<string, unknown>>(r))
}
export function applyResourceOpen(body: Record<string, unknown>, institutionId?: number | null): Promise<Record<string, unknown>> {
  return http.post('/org/applications/resource-open', body, { params: inst(institutionId) })
    .then((r) => unwrap<Record<string, unknown>>(r))
}
export function getOrgGrants(institutionId?: number | null): Promise<{ items: ResourceGrant[]; total?: number; byType?: Record<string, unknown> }> {
  return http.get('/org/grants', { params: inst(institutionId) })
    .then((r) => unwrap<{ items: ResourceGrant[]; total?: number; byType?: Record<string, unknown> }>(r))
}
export function upsertLeaveBalance(body: Record<string, unknown>, institutionId?: number | null): Promise<Record<string, unknown>> {
  return http.post('/org/leave/balances', body, { params: inst(institutionId) })
    .then((r) => unwrap<Record<string, unknown>>(r))
}

// ================================================================== 审批工作流
export function listWorkflowTasks(scope = 'todo'): Promise<WorkflowTask[]> {
  return http.get('/workflow/tasks', { params: { scope } }).then((r) => unwrap<WorkflowTask[]>(r))
}
export function decideTask(taskId: number, decision: string, note?: string): Promise<Record<string, unknown>> {
  return http.post('/workflow/tasks/' + taskId + '/decide', { decision, note }).then((r) => unwrap<Record<string, unknown>>(r))
}

// ================================================================== 删除申请（级联前置校验 + 上一级审核）
//
// ★ 这里**只有申请，没有直接删除**：需求要求「任何一层级的首次删除操作都需要经过上一级审核
//   后方可执行」。批准后由后端在审批回调里执行删除 —— 前端不提供任何绕过审批的入口。

/** 申请删除的返回：带审批单号，需等上一级批准后才真正删除。 */
export interface DeleteRequestResult {
  orderId?: number
  pendingApproval?: boolean
  hint?: string
  departmentId?: number
  departmentName?: string
  institutionId?: number
  institutionName?: string
  tenantId?: number
  tenantName?: string
}

/** 申请删除机构（审批人 = 上一级，即租户管理员）。前置：该机构下无部门、无员工。 */
export function requestInstitutionDelete(
  id: number, reason?: string, institutionId?: number | null
): Promise<DeleteRequestResult> {
  return http.post('/org/institutions/' + id + '/delete-request', { reason }, { params: inst(institutionId) })
    .then((r) => unwrap<DeleteRequestResult>(r))
}

/** 申请删除本租户（审批人 = 平台管理员）。前置：本租户下无机构、无部门、无员工。 */
export function requestTenantDelete(reason?: string): Promise<DeleteRequestResult> {
  return http.post('/tenant/delete-request', { reason }).then((r) => unwrap<DeleteRequestResult>(r))
}
