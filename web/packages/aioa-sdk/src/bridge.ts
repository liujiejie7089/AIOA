import {
  MSG_ACTION,
  MSG_NOTIFY,
  MSG_OPEN_ASSISTANT,
  MSG_REQUEST_TOKEN,
  MSG_SET_CONTEXT,
  MSG_TOKEN,
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

/** getToken 默认等待主应用应答的时间 */
const DEFAULT_TOKEN_TIMEOUT = 3000

/**
 * AIOA 子应用桥接实例。
 *
 * - 运行在工作台内（window.parent !== window）时通过 postMessage 与主应用通信；
 * - 独立运行时全部 API 降级为 no-op / null，不抛错，保证子应用可脱离工作台使用。
 */
export class AioaBridge {
  /** 子应用编码 */
  readonly appCode: string
  /** 是否运行在工作台内 */
  readonly inWorkbench: boolean

  private context: Partial<PageContext>
  private handlers = new Map<string, Set<ActionHandler>>()
  private listening = false
  /** postMessage 的 targetOrigin；'*' 仅用于未配置的降级场景 */
  private readonly targetOrigin: string
  /** event.origin 白名单；为空表示不校验（兼容旧行为，但会告警一次） */
  private readonly allowedOrigins: string[]
  private readonly tokenTimeoutMs: number
  private pendingTokens = new Map<
    string,
    { resolve: (token: string | null) => void; reject: (err: Error) => void }
  >()
  private lastToken: string | null = null
  private warnedOpenOrigin = false

  constructor(options: CreateBridgeOptions) {
    this.appCode = options.appCode
    this.inWorkbench = typeof window !== 'undefined' && window.parent !== window
    this.context = { appCode: options.appCode }
    // 父窗口 origin：显式配置优先，其次用 ancestorOrigins 推导（Chromium 系可用），
    // 都没有才退回 '*'。能确定父窗口时，白名单默认就只认它 —— 安全默认值，
    // 子应用不必逐个手工配置。
    const ancestral =
      typeof window !== 'undefined'
        ? (window.location as unknown as { ancestorOrigins?: readonly string[] }).ancestorOrigins?.[0]
        : undefined
    this.targetOrigin = options.targetOrigin || ancestral || '*'
    this.allowedOrigins =
      options.allowedOrigins?.filter(Boolean) ??
      (this.targetOrigin === '*' ? [] : [this.targetOrigin])
    this.tokenTimeoutMs = options.tokenTimeoutMs || DEFAULT_TOKEN_TIMEOUT

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
   * 索取主应用的登录态 token（真实实现：postMessage 请求/响应 + requestId 配对）。
   *
   * 改造前恒返回 null —— 子应用想调基座 API 只能自己在 localStorage 里翻，
   * 而令牌存什么键是主应用的内部实现，子应用去猜就是耦合 + 安全隐患。
   * 现在由主应用作为令牌的唯一持有方按需下发，子应用不必知道存储细节。
   *
   * @returns 主应用令牌；主应用未登录或按策略拒绝下发时为 null
   * @throws 未在/workbench 内运行、或超时未收到应答时抛错（超时是失败，不是「没有 token」）
   */
  getToken(): Promise<string | null> {
    if (!this.inWorkbench) {
      return Promise.reject(new Error('[aioa-sdk] 未运行在工作台内，无法获取主应用 token'))
    }
    const requestId = `${this.appCode}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    return new Promise<string | null>((resolve, reject) => {
      const timer = setTimeout(() => {
        if (!this.pendingTokens.delete(requestId)) return
        reject(
          new Error(
            `[aioa-sdk] 获取主应用 token 超时（${this.tokenTimeoutMs}ms）：主应用未应答，请确认工作台桥接已启用`
          )
        )
      }, this.tokenTimeoutMs)

      this.pendingTokens.set(requestId, {
        resolve: (token) => {
          clearTimeout(timer)
          this.lastToken = token
          resolve(token)
        },
        reject: (err) => {
          clearTimeout(timer)
          reject(err)
        }
      })
      this.post(MSG_REQUEST_TOKEN, { requestId })
    })
  }

  /** 上一次成功获取到的 token（无副作用、不发消息）；从未获取过时为 null */
  peekToken(): string | null {
    return this.lastToken
  }

  /** 销毁实例（移除监听），一般仅在子应用卸载时使用 */
  destroy(): void {
    if (this.listening && typeof window !== 'undefined') {
      window.removeEventListener('message', this.handleMessage, false)
      this.listening = false
    }
    this.handlers.clear()
    // 挂起的请求必须显式失败：静默丢弃会让调用方的 await 永远悬着
    this.pendingTokens.forEach(({ reject }) =>
      reject(new Error('[aioa-sdk] 桥接已销毁，token 请求被取消'))
    )
    this.pendingTokens.clear()
  }

  /** event.origin 是否在白名单内（未配置白名单时不校验，仅告警一次） */
  private isOriginAllowed(origin: string): boolean {
    if (this.allowedOrigins.length === 0) {
      if (!this.warnedOpenOrigin) {
        this.warnedOpenOrigin = true
        console.warn(
          '[aioa-sdk] 未配置 allowedOrigins，将接收任意来源的桥接消息（生产环境请显式配置）'
        )
      }
      return true
    }
    return this.allowedOrigins.includes(origin)
  }

  private handleMessage = (event: MessageEvent): void => {
    const data = event.data as BridgeMessage | null
    if (!data || typeof data !== 'object' || typeof data.type !== 'string') return
    // origin 校验要放在最前面：否则一个恶意站点可以冒充主应用下发任意动作/令牌
    if (!this.isOriginAllowed(event.origin)) {
      console.warn(`[aioa-sdk] 忽略来自非白名单来源的桥接消息：${event.origin}`)
      return
    }

    if (data.type === MSG_TOKEN) {
      const pending = data.requestId ? this.pendingTokens.get(data.requestId) : undefined
      if (!pending) return  // 不是本实例（或已超时）发起的请求
      this.pendingTokens.delete(data.requestId as string)
      pending.resolve(typeof data.token === 'string' && data.token ? data.token : null)
      return
    }

    if (data.type !== MSG_ACTION) return
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
    window.parent.postMessage({ type, appCode: this.appCode, ...payload }, this.targetOrigin)
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
