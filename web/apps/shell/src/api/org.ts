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
  tokenTotal?: number
  tokenUsed?: number
  tokenAllocated?: number
  allocatableTokens?: number
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
  kb?: { id: number; resKey: string; name: string }[]
  workers?: { id: number; resKey: string; name: string }[]
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
}

export interface OnboardingStep {
  step: number
  key: string
  name: string
  owner: string
  gate: string
  passed: boolean
  reason?: string
  recorded?: boolean
  current?: boolean
}

export interface OnboardingProgress {
  institutionId: number
  institutionName?: string
  totalSteps: number
  passedCount?: number
  percent?: number
  completed?: boolean
  steps: OnboardingStep[]
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
export function listInstitutions(): Promise<Institution[]> {
  return http.get('/tenant/institutions').then((r) => unwrap<Institution[]>(r))
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
export function toggleGrant(id: number): Promise<ResourceGrant> {
  return http.post('/tenant/grants/' + id + '/toggle').then((r) => unwrap<ResourceGrant>(r))
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
export function getOnboardingProgress(institutionId: number): Promise<OnboardingProgress> {
  return http.get('/tenant/onboarding/' + institutionId + '/progress').then((r) => unwrap<OnboardingProgress>(r))
}
export function advanceOnboardingAll(institutionId: number): Promise<Record<string, unknown>> {
  return http.post('/tenant/onboarding/' + institutionId + '/advance-all').then((r) => unwrap<Record<string, unknown>>(r))
}
export function listApprovalFlowDefs(institutionId?: number): Promise<ApprovalFlowDef[]> {
  return http.get('/tenant/approval-flow-defs', { params: institutionId ? { institutionId } : {} })
    .then((r) => unwrap<ApprovalFlowDef[]>(r))
}
export function saveApprovalFlowDef(body: Record<string, unknown>): Promise<ApprovalFlowDef> {
  return http.post('/tenant/approval-flow-defs', body).then((r) => unwrap<ApprovalFlowDef>(r))
}

// ================================================================== 企业端：组织与员工
export function getOrgProfile(): Promise<Record<string, unknown>> {
  return http.get('/org/profile').then((r) => unwrap<Record<string, unknown>>(r))
}
export function getDepartments(): Promise<{ tree: OrgDepartment[]; total?: number; depthLimit?: number; maxDepth?: number }> {
  return http.get('/org/departments').then((r) => unwrap<{ tree: OrgDepartment[]; total?: number; depthLimit?: number; maxDepth?: number }>(r))
}
export function createDepartment(body: Partial<OrgDepartment>): Promise<OrgDepartment> {
  return http.post('/org/departments', body).then((r) => unwrap<OrgDepartment>(r))
}
export function updateDepartment(id: number, body: Partial<OrgDepartment>): Promise<OrgDepartment> {
  return http.put('/org/departments/' + id, body).then((r) => unwrap<OrgDepartment>(r))
}
export function deleteDepartment(id: number): Promise<unknown> {
  return http.delete('/org/departments/' + id).then((r) => unwrap<unknown>(r))
}
export function moveDepartment(id: number, parentId: number): Promise<OrgDepartment> {
  return http.post('/org/departments/' + id + '/move', { parentId }).then((r) => unwrap<OrgDepartment>(r))
}
export function listMembers(params?: Record<string, unknown>): Promise<{ items: OrgMember[]; total?: number }> {
  return http.get('/org/members', { params }).then((r) => unwrap<{ items: OrgMember[]; total?: number }>(r))
}
export function createMember(body: Partial<OrgMember>): Promise<OrgMember> {
  return http.post('/org/members', body).then((r) => unwrap<OrgMember>(r))
}
export function updateMember(id: number, body: Partial<OrgMember>): Promise<OrgMember> {
  return http.put('/org/members/' + id, body).then((r) => unwrap<OrgMember>(r))
}
export function importMembers(rows: Record<string, unknown>[]): Promise<Record<string, unknown>> {
  return http.post('/org/members/import', { rows }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function listDeptQuotas(period: string): Promise<Record<string, unknown>[]> {
  return http.get('/org/dept-quotas', { params: { period } }).then((r) => unwrap<Record<string, unknown>[]>(r))
}
export function createDeptQuota(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return http.post('/org/dept-quotas', body).then((r) => unwrap<Record<string, unknown>>(r))
}
export function getOrgQuota(period: string): Promise<OrgQuota> {
  return http.get('/org/org-quota', { params: { period } }).then((r) => unwrap<OrgQuota>(r))
}
export function getOrgUsage(period: string): Promise<Record<string, unknown>> {
  return http.get('/org/usage', { params: { period } }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function applyQuotaExpand(tokens: number, reason: string): Promise<Record<string, unknown>> {
  return http.post('/org/applications/quota-expand', { tokens, reason }).then((r) => unwrap<Record<string, unknown>>(r))
}
export function applyResourceOpen(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return http.post('/org/applications/resource-open', body).then((r) => unwrap<Record<string, unknown>>(r))
}
export function getOrgGrants(): Promise<{ items: ResourceGrant[]; total?: number; byType?: Record<string, unknown> }> {
  return http.get('/org/grants').then((r) => unwrap<{ items: ResourceGrant[]; total?: number; byType?: Record<string, unknown> }>(r))
}
export function upsertLeaveBalance(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  return http.post('/org/leave/balances', body).then((r) => unwrap<Record<string, unknown>>(r))
}

// ================================================================== 审批工作流
export function listWorkflowTasks(scope = 'todo'): Promise<WorkflowTask[]> {
  return http.get('/workflow/tasks', { params: { scope } }).then((r) => unwrap<WorkflowTask[]>(r))
}
export function decideTask(taskId: number, decision: string, note?: string): Promise<Record<string, unknown>> {
  return http.post('/workflow/tasks/' + taskId + '/decide', { decision, note }).then((r) => unwrap<Record<string, unknown>>(r))
}
