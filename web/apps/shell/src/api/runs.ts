import { fetchEventSource } from '@microsoft/fetch-event-source'
import { http, unwrap, API_BASE } from './index'
import type { PageContextSnapshot } from '@/types'

export interface CreateRunPayload {
  text: string
  context?: PageContextSnapshot | null
}

export interface CreateRunResult {
  runId: string
  conversationId?: string
}

export function create(conversationId: string, payload: CreateRunPayload): Promise<CreateRunResult> {
  return http.post(`/conversations/${conversationId}/runs`, payload).then(unwrap<CreateRunResult>)
}

export function cancel(runId: string): Promise<void> {
  return http.post(`/runs/${runId}/cancel`).then(() => undefined)
}

export interface StreamHandlers {
  onDelta: (delta: string) => void
  onCompleted: (fullText?: string) => void
  onError: (message: string) => void
}

/**
 * 内部哨兵：已经收到终态帧（message.completed / run.completed）之后，传输层才关闭。
 *
 * 为什么需要它：本服务端的 SSE 响应**不发分块终止块**（`Transfer-Encoding: chunked`
 * 缺少末尾的 `0\r\n\r\n`，详见 docs/42），浏览器读流时会抛 network error。
 * 但「run 的终态」在协议上由 `run.completed` / `run.failed` 定义，不由 TCP 关闭定义 ——
 * 因此**终态帧之后**的关闭是预期收尾，不是失败。
 *
 * 之前这里没有区分：任何读流异常都走 `handlers.onError()`，于是回答明明已经完整到达，
 * 界面仍然标红并弹出「network error」——这就是「管理端 AI 助手不能用」的直接观感。
 */
class StreamEndedAfterCompletion extends Error {}

/**
 * 订阅 run 的 SSE 事件流。
 * 事件类型：message.delta（增量文本）/ message.completed（收尾）/ run.failed|error（失败）。
 */
export async function streamRun(options: {
  runId: string
  token: string
  signal: AbortSignal
  handlers: StreamHandlers
}): Promise<void> {
  const { runId, token, signal, handlers } = options
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (token) headers.Authorization = `Bearer ${token}`

  /**
   * 是否已收到「回答已完整」帧。
   * 取 `message.completed` / `run.completed` 两类：前者代表回答内容已定稿，
   * 后者代表 run 已落终态。二者任一到达之后，流的传输层怎么关闭都不算失败。
   */
  let terminal = false

  try {
    // SSE 不走 axios，必须自己拼基址 —— 与 axios 的 baseURL 同源于 API_BASE（见 index.ts）
    await fetchEventSource(`${API_BASE}/runs/${runId}/events`, {
      method: 'GET',
      headers,
      signal,
      openWhenHidden: true,
      onmessage(event) {
        const type = event.event || 'message'
        let data: Record<string, unknown> = {}
        try {
          data = event.data ? (JSON.parse(event.data) as Record<string, unknown>) : {}
        } catch {
          data = { delta: event.data, content: event.data }
        }
        switch (type) {
          case 'message.delta':
            handlers.onDelta(String(data.delta ?? data.text ?? data.content ?? ''))
            break
          case 'message.completed':
            terminal = true
            handlers.onCompleted(data.content == null ? undefined : String(data.content))
            break
          case 'run.completed':
            terminal = true
            break
          case 'run.failed':
          case 'error':
            handlers.onError(String(data.message ?? data.error ?? '生成失败，请稍后重试'))
            break
          default:
            break
        }
      },
      onerror(error) {
        // 用户点了「停止」：交给上层按 aborted 处理
        if (signal.aborted) throw error
        // 终态帧之后才断：这是本服务端 SSE 的收尾方式，不是失败。
        // 注意必须 throw 哨兵 —— 若直接 return，fetch-event-source 会按默认 1s
        // 无限重连（见其 fetch.js：onerror 返回 undefined 时用 retryInterval 重试）。
        if (terminal) throw new StreamEndedAfterCompletion()
        handlers.onError(error instanceof Error ? error.message : '事件流连接中断')
        throw error
      }
    })
  } catch (error) {
    if (error instanceof StreamEndedAfterCompletion) return
    throw error
  }
}
