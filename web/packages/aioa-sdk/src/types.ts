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
  /**
   * 主应用（父窗口）的 origin，postMessage 的 targetOrigin。
   * 不传则沿用 '*'（调试方便但任何站点都能收到消息）—— 生产环境务必显式配置。
   */
  targetOrigin?: string
  /**
   * 允许接收其消息的 origin 白名单（校验 event.origin）。
   * 不传则不做校验（向后兼容），并在首次收到消息时告警一次。
   */
  allowedOrigins?: string[]
  /** getToken 的等待超时（毫秒，默认 3000）。超时按失败抛出，不静默返回 null。 */
  tokenTimeoutMs?: number
}

/** 动作负载（主应用派发下来的原始结构） */
export type ActionPayload = AioaAction['payload']
