import { createAioaBridge, type AioaBridge } from '@aioa/sdk'

const APP_CODE = 'ticket'

/**
 * 获取（或创建）本子应用的桥接实例。
 * createAioaBridge 按 appCode 幂等，页面侧重复调用只会拿到同一个实例。
 */
export function getBridge(): AioaBridge {
  return createAioaBridge({ appCode: APP_CODE })
}

/** 主应用派发 refresh 动作时，在本窗口广播该事件 */
export const REFRESH_EVENT = 'aioa:refresh'
