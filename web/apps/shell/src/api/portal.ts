/**
 * 工作台首页数据层。
 *
 * ★ 原则：首页**不另造门户表、不读演示种子**，每一格都对接管理端已有模块的同一个接口，
 *   因此「管理端页面看到什么，首页就显示什么」，并且随业务数据变化即时更新。
 *
 *   1. 最新信息            ← 消息中心      GET /notifications                （按当前用户过滤；含审批通知）
 *   2. 我的会议/会议邀请    ← OA 表单机制   GET /form-submissions?code=meeting_book   （会议助手数字人提交的会议）
 *   3. 日历                 ← OA 表单机制   GET /form-submissions?code=calendar_event（工作日历数字人提交的日程）
 *   4. 待办/待阅/已办/已阅/拟稿/草稿 ← 审批中心 GET /workflow/tasks?scope=... + /workflow/tasks/summary
 *   5. 知识库文件           ← 知识库        GET /kb/documents                  （与知识库页同一接口）
 *   6. 日程管理             ← OA 表单机制   GET /form-submissions?code=calendar_event（当日）
 *   发起流程               ← 表单设计器     GET /forms?policy=APPROVAL + /forms/{code} + /forms/{code}/submit
 *
 * 后端返回形状不统一（数组 / IPage{records} / {list}），本层统一归一成 `PageResult`，
 * 视图层只认 `{ list, total }`，避免「接口有数据但首页空着」这类形状错配缺陷。
 */
import { http, unwrap } from './index'
import { getForm as getFormRender } from './forms'
import type { FormRender, FormTemplate } from './forms'
import type { NotificationItem } from './notifications'
import type { KbDoc } from './resource'

export type { FormRender, FormTemplate, NotificationItem, KbDoc }

/** 首页统一分页形状。 */
export interface PageResult<T> {
  list: T[]
  total: number
}

/** 把「裸数组 / {list} / IPage{records}」三种后端形态归一。 */
function toPage<T>(raw: unknown): PageResult<T> {
  if (Array.isArray(raw)) return { list: raw as T[], total: raw.length }
  if (raw && typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    const list = (Array.isArray(obj.list) ? obj.list : Array.isArray(obj.records) ? obj.records : []) as T[]
    const total = typeof obj.total === 'number' ? obj.total : list.length
    return { list, total }
  }
  return { list: [], total: 0 }
}

// ================================================================== 1. 最新信息（消息中心）
/** 通知类型 → 首页标签文案（与消息中心同一套 type 常量）。 */
export const NOTICE_TYPE_LABEL: Record<string, string> = {
  APPROVAL: '审批',
  SYSTEM: '系统',
  WORKER: '数字员工',
  FEEDBACK: '反馈',
  NEWS: 'NEWS',
  NOTICE: 'NOTICE'
}

/**
 * 最新信息 = 站内通知（消息中心同源）。
 * 后端 `GET /api/v1/notifications` 返回 `{items, unread}`，items 已按时间倒序。
 */
export function listNotices(limit = 6): Promise<{ items: NotificationItem[]; unread: number }> {
  return http.get('/notifications', { params: { limit } }).then((r) => {
    const data = unwrap<{ items?: NotificationItem[]; unread?: number }>(r)
    return { items: data?.items || [], unread: Number(data?.unread || 0) }
  })
}

// ================================================================== 2/3/6. OA 表单提交（会议 / 日历 / 日程）
/**
 * 表单提交记录（`GET /api/v1/form-submissions`）。
 * 权限语义在后端一处判定：持有 `form:manage` 看全租户，否则只看自己。
 * 会议/日程没有独立的管理页面，它们的真实业务数据就存在这里（数字人「会议助手」「工作日历」提交）。
 */
export interface FormSubmissionRow {
  id: number
  code: string
  bizType?: string
  applicantId: number
  status: string
  /** 业务字段原文（JSON 字符串，需 parseFormData 解析）。 */
  dataJson?: string
  /** 兼容部分序列化实现把 dataJson 展开成 data 的情况。 */
  data?: string | Record<string, unknown>
  submittedAt?: string
}

export function listFormSubmissions(
  code: string,
  page = 1,
  size = 50
): Promise<PageResult<FormSubmissionRow>> {
  return http
    .get('/form-submissions', { params: { code, page, size } })
    .then((r) => toPage<FormSubmissionRow>(unwrap<unknown>(r)))
}

/** 解析提交记录里的业务字段（无效 JSON 一律返回空对象，不抛）。 */
export function parseFormData(row: FormSubmissionRow): Record<string, unknown> {
  const raw = row.dataJson ?? row.data
  if (!raw) return {}
  if (typeof raw === 'object') return raw as Record<string, unknown>
  try {
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? (obj as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

/** 会议行（会议助手表单：title / meeting_type / start_time / end_time / attendees / agenda）。 */
export interface MeetingRow {
  id: number
  title: string
  startAt?: string
  endAt?: string
  meetingType?: string
  meetingTypeLabel?: string
  attendees?: string
  applicantId: number
  status: string
  mine: boolean
  invited: boolean
}

const MEETING_TYPE_LABEL: Record<string, string> = {
  REGULAR: '例会',
  THEME: '专题会',
  DECISION: '决策会',
  TRAIN: '培训会'
}

export function toMeetingRow(
  row: FormSubmissionRow,
  me: { id?: string | number; name?: string }
): MeetingRow {
  const d = parseFormData(row)
  const attendees = String(d.attendees ?? '')
  const myId = me.id == null ? '' : String(me.id)
  const myName = (me.name || '').trim()
  return {
    id: row.id,
    title: String(d.title ?? '（未填写会议主题）'),
    startAt: d.start_time ? String(d.start_time) : undefined,
    endAt: d.end_time ? String(d.end_time) : undefined,
    meetingType: d.meeting_type ? String(d.meeting_type) : undefined,
    meetingTypeLabel: d.meeting_type ? MEETING_TYPE_LABEL[String(d.meeting_type)] || String(d.meeting_type) : undefined,
    attendees,
    applicantId: row.applicantId,
    status: row.status,
    mine: myId !== '' && String(row.applicantId) === myId,
    // 参会人字段是自由文本（列明参会人员/部门），包含我的显示名即视为「邀请我」
    invited: myName !== '' && attendees.includes(myName) && String(row.applicantId) !== myId
  }
}

/** 日程行（工作日历表单：event_title / start_time / end_time / all_day / remark）。 */
export interface ScheduleRow {
  id: number
  title: string
  startAt?: string
  endAt?: string
  allDay: boolean
  remark?: string
  applicantId: number
  mine: boolean
}

export function toScheduleRow(
  row: FormSubmissionRow,
  me: { id?: string | number }
): ScheduleRow {
  const d = parseFormData(row)
  return {
    id: row.id,
    title: String(d.event_title ?? '（未填写日程标题）'),
    startAt: d.start_time ? String(d.start_time) : undefined,
    endAt: d.end_time ? String(d.end_time) : undefined,
    allDay: d.all_day === true,
    remark: d.remark ? String(d.remark) : undefined,
    applicantId: row.applicantId,
    mine: me.id != null && String(row.applicantId) === String(me.id)
  }
}

/** 从 ISO/`yyyy-MM-dd HH:mm:ss` 取 `yyyy-MM-dd`（无效返回空串）。 */
export function dateKey(s?: string): string {
  if (!s) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  return m ? `${m[1]}-${m[2]}-${m[3]}` : ''
}

// ================================================================== 4. 审批中心（六 tab）
export interface WorkflowHomeSummary {
  todo: number
  ccUnread: number
  done: number
  cc?: number
  mine?: number
  [key: string]: unknown
}

export function getWorkflowSummary(): Promise<WorkflowHomeSummary> {
  return http.get('/workflow/tasks/summary').then((r) => unwrap<WorkflowHomeSummary>(r))
}

/** 首页审批列表项（只取卡片要展示的字段，避免拉整棵 timeline 渲染）。 */
export interface WorkflowTaskLite {
  id: number
  title: string
  bizType?: string
  status?: string
  applicantName?: string
  createdAt?: string
  /** 抄送已读态（scope=cc 才有意义）。 */
  read?: boolean
}

/** 审批任务列表：后端返回裸数组，这里归一后按 tab 过滤已读态。 */
export function listWorkflowTasks(
  scope: 'todo' | 'cc' | 'done' | 'mine',
  size = 50
): Promise<WorkflowTaskLite[]> {
  return http.get('/workflow/tasks', { params: { scope, page: 1, size } }).then((r) => {
    const { list } = toPage<Record<string, unknown>>(unwrap<unknown>(r))
    return list.map((x) => ({
      id: Number(x.taskId ?? x.id ?? 0),
      title: String(x.title ?? x.bizType ?? '—'),
      bizType: x.bizType ? String(x.bizType) : undefined,
      status: x.orderStatus ? String(x.orderStatus) : x.taskStatus ? String(x.taskStatus) : undefined,
      applicantName: x.applicantName ? String(x.applicantName) : x.creatorName ? String(x.creatorName) : undefined,
      createdAt: x.createdAt ? String(x.createdAt) : x.completedAt ? String(x.completedAt) : undefined,
      read: typeof x.read === 'boolean' ? x.read : undefined
    }))
  })
}

// ================================================================== 5. 知识库文件
/**
 * 知识库文件列表（与「知识库」页同一个接口 `GET /kb/documents`）。
 * 不传 scope = 我的资料；scope='tenant' = 租户全部（仅租户管理员，越权时后端 403）。
 */
export function listKbFiles(scope?: 'tenant'): Promise<KbDoc[]> {
  return http.get('/kb/documents', { params: scope ? { scope } : {} }).then((r) => unwrap<KbDoc[]>(r))
}

/** 知识库条目类型文案：优先用切片/解析状态，其次用图标名。 */
export function kbTypeLabel(doc: KbDoc): string {
  const icon = (doc.icon || '').toLowerCase()
  if (icon) return icon
  return doc.state === 'ok' ? '文档' : doc.state === 'wait' ? '解析中' : '失败'
}

// ================================================================== 发起流程（动态表单）
/**
 * 取「可发起的审批表单」列表。复用 /forms 端点（与表单设计器同源），
 * 按 policy=APPROVAL 过滤。后端可能返回 IPage{records} / {list} / 裸数组三种形态，这里统一归一。
 */
export function listApprovalForms(): Promise<FormTemplate[]> {
  return http.get('/forms', { params: { policy: 'APPROVAL' } }).then((r) => {
    const { list } = toPage<FormTemplate>(unwrap<unknown>(r))
    return list
  })
}

/** 取单张表单的渲染定义（字段 + 选项），复用 api/forms 既有封装。 */
export function getApprovalForm(code: string): Promise<FormRender> {
  return getFormRender(code)
}

/** 提交发起流程：body 形态严格按契约 { data:{...} }。 */
export function submitForm(code: string, data: Record<string, unknown>): Promise<unknown> {
  return http.post(`/forms/${code}/submit`, { data }).then((r) => unwrap(r))
}
