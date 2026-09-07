import {
  MSG_ACTION,
  MSG_NOTIFY,
  MSG_OPEN_ASSISTANT,
  MSG_SET_CONTEXT,
  type BridgeMessage
} from './protocol'
import type {
  ActionHandler,
  ActionType,
  CreateBridgeOptions,
  NotificationKind,
  OpenAssistantOptions,
  PageContext,
  Unsubscribe
} from './types'

/**
 * AIOA 子应用桥接实例。
 *
 * - 运行在工作台内（window.parent !== window）时通过 postMessage 与主应用通信；
 * - 独立运行时全部 API 降级为 no-op，不抛错，保证子应用可脱离工作台使用。
 */
export class AioaBridge {
  /** 子应用编码 */
  readonly appCode: string
  /** 是否运行在工作台内 */
  readonly inWorkbench: boolean

  private context: Partial<PageContext>
  private handlers = new Map<string, Set<ActionHandler>>()
  private listening = false

  constructor(options: CreateBridgeOptions) {
    this.appCode = options.appCode
    this.inWorkbench = typeof window !== 'undefined' && window.parent !== window
    this.context = { appCode: options.appCode }

    if (typeof window !== 'undefined' && this.inWorkbench) {
      window.addEventListener('message', this.handleMessage, false)
      this.listening = true
    }
  }

  /**
   * 上报/更新页面上下文（增量合并到缓存）。
   * 页面切换、筛选条件变化时调用。
   */
  setContext(ctx: Partial<PageContext>): void {
    this.context = { ...this.context, ...ctx, appCode: this.appCode }
    this.post(MSG_SET_CONTEXT, { context: { ...this.context } })
  }

  /** 读取当前上下文（本地缓存快照） */
  getContext(): Partial<PageContext> {
    return { ...this.context }
  }

  /** 唤起主应用右侧 AI 助手抽屉，可预填问题 */
  openAssistant(opts?: OpenAssistantOptions): void {
    this.post(MSG_OPEN_ASSISTANT, { preset: opts?.preset })
  }

  /**
   * 注册反向动作处理器，返回取消注册函数。
   * 未注册的动作为空操作（优雅降级）。
   */
  onAction(type: ActionType, handler: ActionHandler): Unsubscribe {
    let set = this.handlers.get(type)
    if (!set) {
      set = new Set()
      this.handlers.set(type, set)
    }
    set.add(handler)
    return () => {
      set?.delete(handler)
    }
  }

  /** 在主应用右上角显示一条通知 */
  notify(message: string, kind: NotificationKind = 'info'): void {
    this.post(MSG_NOTIFY, { message, kind })
  }

  /**
   * 获取主应用登录态 token。
   * M1 返回 null：token 由主应用持有，子应用暂不直连基座 API。
   */
  getToken(): string | null {
    return null
  }

  /** 销毁实例（移除监听），一般仅在子应用卸载时使用 */
  destroy(): void {
    if (this.listening && typeof window !== 'undefined') {
      window.removeEventListener('message', this.handleMessage, false)
      this.listening = false
    }
    this.handlers.clear()
  }

  private handleMessage = (event: MessageEvent): void => {
    const data = event.data as BridgeMessage | null
    if (!data || typeof data !== 'object' || data.type !== MSG_ACTION) return
    // 指定了 appCode 但不是本应用时忽略
    if (data.appCode && data.appCode !== this.appCode) return
    this.dispatch(data.action)
  }

  private dispatch(action?: { type?: string; payload?: unknown }): void {
    if (!action?.type) return
    const set = this.handlers.get(action.type)
    if (!set || set.size === 0) return
    set.forEach((handler) => {
      try {
        handler(action.payload)
      } catch (err) {
        console.warn(`[aioa-sdk] 动作 ${action.type} 处理失败`, err)
      }
    })
  }

  private post(type: string, payload: Record<string, unknown> = {}): void {
    // 独立运行（非工作台）时静默降级
    if (typeof window === 'undefined' || !this.inWorkbench) return
    // M1：wujie/iframe 均用 '*'，M3 收紧为可控 origin 白名单
    window.parent.postMessage({ type, appCode: this.appCode, ...payload }, '*')
  }
}

const instances = new Map<string, AioaBridge>()

/**
 * 创建桥接实例（按 appCode 幂等：同一 appCode 复用同一实例）。
 * 应在子应用入口最早期调用。
 */
export function createAioaBridge(options: CreateBridgeOptions): AioaBridge {
  const cached = instances.get(options.appCode)
  if (cached) return cached
  const bridge = new AioaBridge(options)
  instances.set(options.appCode, bridge)
  return bridge
}
