import type { AioaAction } from './protocol'

/** 子应用页面上下文（agent 感知"用户在哪"的依据） */
export interface PageContext {
  /** 子应用编码，与 app_registry.app_code 一致 */
  appCode: string
  /** 页面标识，英文且稳定（如 ticket-list），不随语言/版本变化 */
  page: string
  /** 展示用页面标题 */
  pageTitle?: string
  /** 当前实体类型，如 ticket */
  entityType?: string
  /** 当前实体 ID，详情页必填 */
  entityId?: string
  /** 当前筛选条件，扁平 key-value，避免深层嵌套 */
  filters?: Record<string, unknown>
  /** 当前选中行 ID */
  selection?: string[]
}

/** 通知级别 */
export type NotificationKind = 'info' | 'success' | 'warning' | 'error'

/** 内置动作类型，可扩展任意字符串 */
export type ActionType = 'openPage' | 'fillForm' | 'refresh' | 'highlight' | (string & {})

/** 动作处理函数；子应用未注册的动作会被忽略 */
export type ActionHandler<P = any> = (payload: P) => void

/** 取消监听函数 */
export type Unsubscribe = () => void

export interface OpenAssistantOptions {
  /** 预填到助手输入框的问题 */
  preset?: string
}

export interface CreateBridgeOptions {
  /** 子应用编码 */
  appCode: string
}

/** 动作负载（主应用派发下来的原始结构） */
export type ActionPayload = AioaAction['payload']
