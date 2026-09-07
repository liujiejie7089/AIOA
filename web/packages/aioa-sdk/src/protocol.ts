import type { NotificationKind, PageContext } from './types'

/** 消息协议类型（主应用 ⇄ 子应用，见 docs/02-子应用接入规范.md） */
export const MSG_SET_CONTEXT = 'AIOA_SET_CONTEXT'
export const MSG_OPEN_ASSISTANT = 'AIOA_OPEN_ASSISTANT'
export const MSG_ACTION = 'AIOA_ACTION'
export const MSG_NOTIFY = 'AIOA_NOTIFY'

export type BridgeMessageType =
  | typeof MSG_SET_CONTEXT
  | typeof MSG_OPEN_ASSISTANT
  | typeof MSG_ACTION
  | typeof MSG_NOTIFY

/** 子应用 → 主应用消息体 */
export interface BridgeMessage {
  type: string
  appCode?: string
  context?: Partial<PageContext>
  preset?: string
  action?: AioaAction
  message?: string
  kind?: NotificationKind
}

/** 反向动作（主应用 → 子应用） */
export interface AioaAction {
  type: string
  payload?: unknown
}
