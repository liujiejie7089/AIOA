import type { NotificationKind, PageContext } from './types'

/** 消息协议类型（主应用 ⇄ 子应用，见 docs/02-子应用接入规范.md） */
export const MSG_SET_CONTEXT = 'AIOA_SET_CONTEXT'
export const MSG_OPEN_ASSISTANT = 'AIOA_OPEN_ASSISTANT'
export const MSG_ACTION = 'AIOA_ACTION'
export const MSG_NOTIFY = 'AIOA_NOTIFY'
/** 子应用 → 主应用：索取登录态 token（带 requestId 做请求/响应配对） */
export const MSG_REQUEST_TOKEN = 'AIOA_REQUEST_TOKEN'
/** 主应用 → 子应用：token 应答（requestId 与请求一致；token 为 null 表示未登录或拒绝下发） */
export const MSG_TOKEN = 'AIOA_TOKEN'

export type BridgeMessageType =
  | typeof MSG_SET_CONTEXT
  | typeof MSG_OPEN_ASSISTANT
  | typeof MSG_ACTION
  | typeof MSG_NOTIFY
  | typeof MSG_REQUEST_TOKEN
  | typeof MSG_TOKEN

/** 子应用 → 主应用消息体 */
export interface BridgeMessage {
  type: string
  appCode?: string
  context?: Partial<PageContext>
  preset?: string
  action?: AioaAction
  message?: string
  kind?: NotificationKind
  /** 请求/响应配对 id（getToken 用） */
  requestId?: string
  /** 仅 MSG_TOKEN：登录态令牌；null 表示主应用未登录或按策略拒绝下发 */
  token?: string | null
}

/** 反向动作（主应用 → 子应用） */
export interface AioaAction {
  type: string
  payload?: unknown
}
