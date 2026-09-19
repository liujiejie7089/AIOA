import { ApiError, http, unwrap } from './index'

/**
 * 消息中心（V5x）。
 *
 * <p>本文件是「通知模块」在前端的唯一映射入口。字段名与后端
 * {@code NotificationController} / 通道配置 / 投递记录 / 偏好四类契约<b>逐字对应</b>，
 * 不在视图里另起一套类型或字面量。</p>
 *
 * <p><b>错误口径</b>：后端「业务失败」走 HTTP 200 + {@code code≠0}，由 {@code unwrap}
 * 抛出 {@link ApiError}；4xx/5xx 走 axios 异常。视图里的 catch 必须同时处理两类，
 * 统一用 {@link notiErrMsg} 取文案，否则失败提示会被吞成通用错误。</p>
 *
 * <p>「我的通知」三个接口已在 {@code NotificationController} 落地；通道配置 / 投递记录 /
 * 个人偏好三类接口由后端另一 worker 实现（契约已冻结），未部署时会返回 404 —— 属预期，
 * 前端<b>不加假数据兜底、不改契约</b>，仅做 try/catch 隔离，一个块失败不拖垮整页。</p>
 */

// ============================================================ 常量

/** 通道码（后端枚举，固定四种）。 */
export type ChannelCode = 'INAPP' | 'EMAIL' | 'SMS' | 'PUSH'

/** 通道码 → 中文名（菜单、表单、列表回显共用，勿在视图里另起字面量）。 */
export const CHANNEL_LABELS: Record<ChannelCode, string> = {
  INAPP: '站内信',
  EMAIL: '邮件',
  SMS: '短信',
  PUSH: '推送'
}

/** 全部通道码（个人偏好多选、表单遍历用）。 */
export const CHANNEL_CODES: ChannelCode[] = ['INAPP', 'EMAIL', 'SMS', 'PUSH']

/** 通道配置项（按通道码取必填/可选键；与后端契约一致）。 */
export const CHANNEL_CONFIG_SCHEMA: Record<
  ChannelCode,
  { required: string[]; optional: string[] }
> = {
  INAPP: { required: [], optional: [] },
  EMAIL: { required: ['url', 'token', 'from'], optional: [] },
  SMS: { required: ['url', 'token', 'signName'], optional: [] },
  PUSH: { required: ['url', 'token'], optional: ['titleTemplate'] }
}

/** 投递状态（与后端枚举一致）。 */
export type DeliveryStatus = 'PENDING' | 'SENT' | 'FAILED' | 'SKIPPED'

export const DELIVERY_STATUS_LABEL: Record<DeliveryStatus, string> = {
  PENDING: '待发送',
  SENT: '已发送',
  FAILED: '失败',
  SKIPPED: '已跳过'
}

export const DELIVERY_STATUS_TAG: Record<DeliveryStatus, string> = {
  PENDING: 'warning',
  SENT: 'success',
  FAILED: 'danger',
  SKIPPED: 'info'
}

/** 站内通知类型 → 中文名 / el-tag 类型（与后端 Notification.TYPE_* 一致）。 */
export const NOTI_TYPE_LABEL: Record<string, string> = {
  APPROVAL: '审批',
  SYSTEM: '系统',
  WORKER: '数字员工'
}

export const NOTI_TYPE_TAG: Record<string, string> = {
  APPROVAL: 'warning',
  SYSTEM: 'info',
  WORKER: 'success'
}

// ============================================================ 类型

/** 我的通知条目（GET /notifications 的 items 元素）。 */
export interface NotificationItem {
  id: number
  type: string
  title?: string
  content?: string
  refId?: number
  unread: boolean
  readAt?: string | null
  createdAt?: string
}

export interface NotificationsResult {
  items: NotificationItem[]
  unread: number
}

/** 通道配置（GET /notifications/channels 的 items 元素）。 */
export interface ChannelConfig {
  url?: string
  token?: string
  from?: string
  signName?: string
  titleTemplate?: string
}

export interface ChannelInfo {
  code: ChannelCode
  label: string
  enabled: boolean
  configured: boolean
  /**
   * 网关配置；**可能缺键**。
   *
   * <p>后端响应体走全局 {@code non_null} 策略，未配置通道（含恒可用的 INAPP）
   * 不回 {@code config} 键 —— 实测 INAPP / 未配置通道的 GET 响应里没有该字段。
   * 因此这里必须是可选，消费方用 {@code c.config?.url} 读；勿写成必填，
   * 否则类型比线上严格，会诱使调用方省掉空值防御。</p>
   */
  config?: ChannelConfig
}

export interface ChannelListResult {
  items: ChannelInfo[]
}

/** PUT /notifications/channels/{code} 请求体。 */
export interface ChannelUpdateBody {
  enabled: boolean
  config: ChannelConfig
}

/** POST /notifications/channels/{code}/test 返回。 */
export interface ChannelTestResult {
  channelCode: ChannelCode
  status: string
  message: string
  sentAt?: string | null
}

/** 投递记录条目（GET /notifications/deliveries 的 items 元素）。 */
export interface DeliveryItem {
  id: number
  notificationId: number
  channelCode: ChannelCode
  status: DeliveryStatus
  attempts: number
  lastError?: string | null
  sentAt?: string | null
  createdAt?: string
}

export interface DeliveryListResult {
  items: DeliveryItem[]
  total: number
}

export interface DeliveryQuery {
  status?: DeliveryStatus | ''
  notificationId?: number | ''
  limit?: number
}

/** POST /notifications/deliveries/{id}/retry 返回。后端实际回 {channelCode,status,message,sentAt}。 */
export interface RetryResult {
  channelCode?: ChannelCode
  status: string
  message: string
  sentAt?: string | null
}

/** 个人偏好（GET / PUT /notifications/preferences）。 */
export interface NotificationPreferences {
  defaultChannels: ChannelCode[]
  byType: Record<string, ChannelCode[]>
}

// ============================================================ 错误文案

/** 统一取后端错误文案：优先响应体 message，其次 ApiError.message，再按 HTTP 状态降级。 */
export function notiErrMsg(e: unknown, fallback = '操作失败'): string {
  const any = e as {
    response?: { status?: number; data?: { message?: string } }
    message?: string
  } | null
  const fromBody = any?.response?.data?.message
  if (fromBody) return fromBody
  // ApiError：message 是后端业务文案
  if (any?.message && !/^Request failed with status code/.test(any.message)) {
    return any.message
  }
  const status = any?.response?.status
  if (status === 403) return '没有权限执行该操作'
  if (status === 404) return '资源不存在或尚未启用'
  if (status === 401) return '登录态已失效，请重新登录'
  return fallback
}

// ============================================================ API：我的通知（既有）

export function listNotifications(limit = 20) {
  return http
    .get('/notifications', { params: { limit } })
    .then((r) => unwrap<NotificationsResult>(r))
}

export function markNotificationRead(id: number) {
  return http.post(`/notifications/${id}/read`).then((r) => unwrap<boolean>(r))
}

export function markAllNotificationsRead() {
  return http.post('/notifications/read-all').then((r) => unwrap<number>(r))
}

// ============================================================ API：通道配置（新）

/**
 * 通道配置 / 投递记录是**租户级**管理动作：平台管理员必须显式带 `tenantId`
 * （后端 NotificationTenantGuard 对平台管理员强制校验），租户管理员可不带（硬绑定本租户）。
 */
export function listChannels(tenantId?: number | null) {
  return http
    .get('/notifications/channels', { params: tenantId ? { tenantId } : {} })
    .then((r) => unwrap<ChannelListResult>(r))
}

export function updateChannel(code: ChannelCode, body: ChannelUpdateBody, tenantId?: number | null) {
  return http
    .put(`/notifications/channels/${code}`, body, { params: tenantId ? { tenantId } : {} })
    .then((r) => unwrap<ChannelInfo>(r))
}

export function testChannel(code: ChannelCode, tenantId?: number | null) {
  return http
    .post(`/notifications/channels/${code}/test`, {}, { params: tenantId ? { tenantId } : {} })
    .then((r) => unwrap<ChannelTestResult>(r))
}

// ============================================================ API：投递记录（新）

export function listDeliveries(q: DeliveryQuery = {}, tenantId?: number | null) {
  const params: Record<string, unknown> = {}
  if (q.status) params.status = q.status
  if (q.notificationId) params.notificationId = q.notificationId
  if (q.limit) params.limit = q.limit
  if (tenantId) params.tenantId = tenantId
  return http
    .get('/notifications/deliveries', { params })
    .then((r) => unwrap<DeliveryListResult>(r))
}

export function retryDelivery(id: number, tenantId?: number | null) {
  return http
    .post(`/notifications/deliveries/${id}/retry`, {}, { params: tenantId ? { tenantId } : {} })
    .then((r) => unwrap<RetryResult>(r))
}

// ============================================================ API：个人偏好（新）

export function getPreferences() {
  return http
    .get('/notifications/preferences')
    .then((r) => unwrap<NotificationPreferences>(r))
}

export function updatePreferences(body: NotificationPreferences) {
  return http
    .put('/notifications/preferences', body)
    .then((r) => unwrap<NotificationPreferences>(r))
}

export { ApiError }
