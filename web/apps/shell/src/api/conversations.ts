import { http, unwrap } from './index'
import type { ChatMessage, Conversation } from '@/types'

export function list(): Promise<Conversation[]> {
  return http.get('/conversations').then(unwrap)
}

export function create(title: string): Promise<Conversation> {
  return http.post('/conversations', { title }).then(unwrap)
}

export function messages(conversationId: string): Promise<ChatMessage[]> {
  return http.get(`/conversations/${conversationId}/messages`).then(unwrap)
}
