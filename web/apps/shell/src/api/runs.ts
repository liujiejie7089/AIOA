import { fetchEventSource } from '@microsoft/fetch-event-source'
import { http, unwrap } from './index'
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
  return http.post(`/conversations/${conversationId}/runs`, payload).then(unwrap)
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

  await fetchEventSource(`/api/v1/runs/${runId}/events`, {
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
          handlers.onCompleted(data.content == null ? undefined : String(data.content))
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
      if (signal.aborted) throw error
      handlers.onError(error instanceof Error ? error.message : '事件流连接中断')
      throw error
    }
  })
}
