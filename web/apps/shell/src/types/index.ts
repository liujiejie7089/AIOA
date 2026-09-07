import type { PageContext } from '@aioa/sdk'

/** 应用注册表条目（对应后端 app_registry） */
export interface AppEntry {
  id: string
  appCode: string
  appName: string
  /** 接入方式：wujie 微前端 / iframe 直嵌 */
  hostType: 'wujie' | 'iframe'
  entryUrl: string
  icon?: string
  description?: string
  enabled?: boolean
  sort?: number
}

export interface UserInfo {
  id: string
  username: string
  displayName?: string
  tenantCode?: string
  tenantName?: string
  avatar?: string
}

export interface LoginPayload {
  username: string
  password: string
}

export interface LoginResult {
  accessToken: string
  refreshToken?: string
  user: UserInfo
}

export interface Conversation {
  id: string
  title: string
  updatedAt?: string
  createdAt?: string
}

export interface ChatMessage {
  id: string
  conversationId?: string
  role: 'user' | 'assistant'
  content: string
  createdAt?: string
  /** 生成失败的消息标记 */
  error?: boolean
}

export type PageContextSnapshot = Partial<PageContext>
