import { http, unwrap } from './index'

/**
 * 模型账号与共享（2026-11-03，docs/71）。
 *
 * <p>三类账号在同一个接口里分开返回（{@code mine / company / shared}），前端按 tab 展示：
 * 混在一张表里会出现「把公司的 Key 当成自己的」这种归属错乱，而归属正是本功能的全部意义。</p>
 *
 * <p><b>接口一律不返回明文 Key</b>：只有 {@code keyHint} 掩码（前 3 后 4）。
 * 明文只在后端下发 agent 的那一条链路上存在。</p>
 */

/** 账号来源：PERSONAL 自行注册（供应商计费，公司不收费）/ COMPANY 公司提供（公司收费）。 */
export type OwnerType = 'PERSONAL' | 'COMPANY'

/** 账号（凭证）视图。 */
export interface ModelCredentialView {
  id: number
  ownerType: OwnerType
  ownerUserId: number | null
  providerKey: string
  providerType: string
  name: string
  baseUrl: string | null
  modelName: string | null
  keyHint: string | null
  shareEnabled: boolean
  enabled: boolean
  remark: string | null
  shareCount: number
  createdAt: string
}

/** 共享关系。 */
export interface ShareView {
  id: number
  credentialId: number
  credentialName: string
  providerKey: string | null
  ownerUserId: number
  ownerName: string
  granteeUserId: number
  granteeName: string
  status: 'ACTIVE' | 'PENDING' | 'REVOKED' | 'EXPIRED'
  quotaTokens: number
  usedTokens: number
  expiresAt: string | null
  createdAt: string
  exhausted: boolean
}

/** 三类账号清单。 */
export interface MyAccounts {
  mine: ModelCredentialView[]
  company: ModelCredentialView[]
  shared: ModelCredentialView[]
}

export interface StatsRow {
  key: string
  name: string
  ownerType: OwnerType | null
  companyCharged: number | null
  tokens: number
  calls: number
  members: number
}

/** 归属统计：三分组 + 分维度行。 */
export interface StatsView {
  dim: string
  since: string
  until: string
  rows: StatsRow[]
  split: {
    companyCharged: number
    personalCharged: number
    unmarked: number
    total: number
    calls: number
  }
}

export function myAccounts(): Promise<MyAccounts> {
  return http.get('/model-credentials').then((r) => unwrap<MyAccounts>(r))
}

export function createCredential(body: {
  ownerType?: OwnerType
  providerKey: string
  name: string
  apiKey: string
  baseUrl?: string
  modelName?: string
  shareEnabled?: boolean
  remark?: string
}): Promise<ModelCredentialView> {
  return http.post('/model-credentials', body).then((r) => unwrap<ModelCredentialView>(r))
}

export function updateCredential(
  id: number,
  body: Partial<{
    name: string
    baseUrl: string
    modelName: string
    remark: string
    apiKey: string
    shareEnabled: boolean
    status: 'ENABLED' | 'DISABLED'
  }>,
): Promise<ModelCredentialView> {
  return http.put(`/model-credentials/${id}`, body).then((r) => unwrap<ModelCredentialView>(r))
}

export function deleteCredential(id: number): Promise<void> {
  return http.delete(`/model-credentials/${id}`).then((r) => unwrap<void>(r))
}

export function myInvites(): Promise<ShareView[]> {
  return http.get('/model-credentials/invites').then((r) => unwrap<ShareView[]>(r))
}

export function incomingInvites(): Promise<ShareView[]> {
  return http.get('/model-credentials/invites/incoming').then((r) => unwrap<ShareView[]>(r))
}

/** 邀请同事共用：token 由邀请者承担（后端记账时 charge_user_id = 邀请者）。 */
export function inviteShare(
  credentialId: number,
  body: { granteeUserId?: number; granteeUsername?: string; quotaTokens?: number; expiresAt?: string },
): Promise<ShareView> {
  return http.post(`/model-credentials/${credentialId}/shares`, body).then((r) => unwrap<ShareView>(r))
}

export function revokeShare(shareId: number): Promise<void> {
  return http.delete(`/model-credentials/shares/${shareId}`).then((r) => unwrap<void>(r))
}

export function leaveShare(shareId: number): Promise<void> {
  return http.post(`/model-credentials/shares/${shareId}/leave`).then((r) => unwrap<void>(r))
}

/** 归属统计：dim=credential 按账号 / bearer 按使用者 / charge 按付费人。 */
export function billingStats(dim: 'credential' | 'bearer' | 'charge', period?: string): Promise<StatsView> {
  return http
    .get('/billing/stats', { params: { dim, period } })
    .then((r) => unwrap<StatsView>(r))
}

/** 账本明细（scope=charge 是「作为付费人」看：邀请者看被邀请人的消耗）。 */
export function ledger(scope?: 'bearer' | 'charge', limit = 50): Promise<LedgerRow[]> {
  return http.get('/ledger', { params: { scope, limit } }).then((r) => unwrap<LedgerRow[]>(r))
}

export interface LedgerRow {
  id: number
  runId: string
  bizType: string
  bizTitle: string
  promptTokens: number
  completionTokens: number
  totalTokens: number
  balanceAfter: number
  createdAt: string
  credentialId: number | null
  bearerUserId: number | null
  chargeUserId: number | null
  chargeOwnerType: OwnerType | null
  /** 1 公司收费 / 0 个人自付 / null 未标注 */
  companyCharged: number | null
  providerKey: string | null
  modelName: string | null
}
