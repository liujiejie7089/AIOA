import { ElMessage } from 'element-plus'
import {
  MSG_NOTIFY,
  MSG_OPEN_ASSISTANT,
  MSG_REQUEST_TOKEN,
  MSG_SET_CONTEXT,
  MSG_TOKEN,
  type BridgeMessage,
  type NotificationKind
} from '@aioa/sdk'
import type { AioaAction } from '@aioa/sdk'
import { useAssistantStore } from '@/stores/assistant'
import { useAuthStore } from '@/stores/auth'
import type { AppEntry } from '@/types'

let inited = false

/**
 * 允许与工作台通信的 origin 白名单。
 *
 * 来源：应用注册表里各子应用 entryUrl 的 origin + 工作台自身 origin。
 * 用 '*' 收发消息等于把「打开助手 / 上报上下文 / 下发令牌」的能力开放给任何站点，
 * 因此这里改为按注册表收敛；注册表未加载完时为空集，此时**不接收**任何消息
 * （宁可暂时不联动，也不放行未知来源）。
 */
const allowedOrigins = new Set<string>()
/** appCode → origin，用于向子应用定向投递（不再广播 + '*'） */
const appOrigins = new Map<string, string>()
let warnedUnknownOrigin = false

/** origin(字符串 URL) → 归一化 origin；非法 URL 返回 '' */
function originOf(url: string): string {
  try {
    return new URL(url, window.location.href).origin
  } catch {
    return ''
  }
}

function isBridgeMessage(data: unknown): data is BridgeMessage {
  return !!data && typeof data === 'object' && typeof (data as BridgeMessage).type === 'string'
}

/** 用应用注册表刷新白名单（应用列表加载后调用；幂等） */
export function registerAppOrigins(apps: AppEntry[]): void {
  allowedOrigins.add(window.location.origin)
  apps.forEach((app) => {
    const origin = originOf(app.entryUrl || '')
    if (!origin) return
    allowedOrigins.add(origin)
    appOrigins.set(app.appCode, origin)
  })
}

/** 额外放行的 origin（如子应用走反向代理后 origin 与 entryUrl 不一致） */
export function allowOrigin(origin: string): void {
  const normalized = originOf(origin)
  if (normalized) allowedOrigins.add(normalized)
}

function isOriginAllowed(origin: string): boolean {
  // 白名单为空说明注册表还没加载：此时一律拒绝，避免"未配置即全放行"
  if (allowedOrigins.size === 0) return false
  return allowedOrigins.has(origin)
}

function onMessage(event: MessageEvent): void {
  const data: unknown = event.data
  if (!isBridgeMessage(data) || !data.type.startsWith('AIOA_')) return
  if (!isOriginAllowed(event.origin)) {
    if (!warnedUnknownOrigin) {
      warnedUnknownOrigin = true
      console.warn(`[shell] 忽略来自非白名单来源的桥接消息：${event.origin}`)
    }
    return
  }

  const assistant = useAssistantStore()
  switch (data.type) {
    case MSG_SET_CONTEXT: {
      if (data.appCode) assistant.setContext(data.appCode, data.context || {})
      break
    }
    case MSG_OPEN_ASSISTANT: {
      assistant.openDrawer(data.preset)
      break
    }
    case MSG_NOTIFY: {
      const kind = (data.kind || 'info') as NotificationKind
      ElMessage({
        type: kind === 'error' || kind === 'success' || kind === 'warning' ? kind : 'info',
        message: data.message || ''
      })
      break
    }
    case MSG_REQUEST_TOKEN: {
      // 令牌由主应用持有并按需下发：子应用不必知道存储键，也不必自己翻 localStorage。
      // 只回给发起方（event.source + 已校验的 origin），不广播。
      const auth = useAuthStore()
      const reply: BridgeMessage = {
        type: MSG_TOKEN,
        appCode: data.appCode,
        requestId: data.requestId,
        token: auth.token || null
      }
      ;(event.source as Window | null)?.postMessage(reply, event.origin)
      break
    }
    default:
      break
  }
}

/** 在主应用安装子应用消息监听（幂等） */
export function initBridge(): void {
  if (inited) return
  inited = true
  window.addEventListener('message', onMessage, false)
}

export function destroyBridge(): void {
  if (!inited) return
  inited = false
  window.removeEventListener('message', onMessage, false)
}

/**
 * 向指定子应用派发反向动作（refresh / openPage / fillForm / highlight ...）。
 * 优先按 appCode 精确匹配 iframe（wujie 子应用的 iframe name 即为 appCode），
 * 并按该应用注册表中的 origin 定向投递；拿不到 origin 时不投递（不再用 '*' 广播）。
 */
export function sendAction(appCode: string, action: AioaAction): void {
  if (!appCode) return
  const payload: BridgeMessage = {
    type: 'AIOA_ACTION',
    appCode,
    action
  }
  const frames = Array.from(document.querySelectorAll('iframe'))
  const matched = frames.filter((frame) => frame.name === appCode || frame.dataset.appCode === appCode)
  const targets = matched.length ? matched : frames
  targets.forEach((frame) => {
    frame.contentWindow?.postMessage(payload, frameOrigin(frame, appCode))
  })
}

/**
 * 投递目标 origin：优先取框架的**真实** origin。
 *
 * 直接按注册表的 entryUrl 定向会漏掉 wujie —— 它把子应用代理到主应用同域下运行，
 * 此时框架实际 origin 是主应用 origin，而 entryUrl 指向另一个端口；按 entryUrl
 * 投递会被浏览器直接丢弃（表现为「反向动作时灵时不灵」）。
 * 跨域 iframe 读 location 会抛异常，那种情况才回落到注册表的 origin。
 */
function frameOrigin(frame: HTMLIFrameElement, appCode: string): string {
  try {
    const origin = frame.contentWindow?.location.origin
    if (origin && origin !== 'null') return origin
  } catch {
    // 跨域：读不到，回落到注册表登记的地址
  }
  return appOrigins.get(appCode) || window.location.origin
}
