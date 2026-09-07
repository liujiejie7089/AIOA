import { ElMessage } from 'element-plus'
import {
  MSG_NOTIFY,
  MSG_OPEN_ASSISTANT,
  MSG_SET_CONTEXT,
  type BridgeMessage,
  type NotificationKind
} from '@aioa/sdk'
import type { AioaAction } from '@aioa/sdk'
import { useAssistantStore } from '@/stores/assistant'

let inited = false

function isBridgeMessage(data: unknown): data is BridgeMessage {
  return !!data && typeof data === 'object' && typeof (data as BridgeMessage).type === 'string'
}

function onMessage(event: MessageEvent): void {
  const data: unknown = event.data
  // M1 不做 origin 校验：wujie/iframe 子应用可能跨域；M3 收紧为可控 origin 白名单
  if (!isBridgeMessage(data) || !data.type.startsWith('AIOA_')) return

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
 * M1 直接向所有子窗口广播并带上 appCode，由子应用自行判断是否处理；
 * wujie 子应用的 iframe name 即为 appCode，这里优先精确匹配。
 */
export function sendAction(appCode: string, action: AioaAction): void {
  if (!appCode) return
  const payload: BridgeMessage = {
    type: 'AIOA_ACTION',
    appCode,
    action
  }
  // M1：统一 '*'，M3 收紧为可控 origin 白名单
  const frames = Array.from(document.querySelectorAll('iframe'))
  const matched = frames.filter((frame) => frame.name === appCode || frame.dataset.appCode === appCode)
  const targets = matched.length ? matched : frames
  targets.forEach((frame) => {
    frame.contentWindow?.postMessage(payload, '*')
  })
}
