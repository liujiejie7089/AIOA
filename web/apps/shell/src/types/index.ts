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
  /** 角色码，如 ROLE_ADMIN / ROLE_TENANT_ADMIN / ROLE_ORG_ADMIN / ROLE_DEPT_LEADER / ROLE_MEMBER */
  roles?: string[]
  /** 租户 ID（数据锚点：所有租户级数据的归属依据） */
  tenantId?: number
  /** 机构 ID（企业端数据锚点，仅机构成员有） */
  institutionId?: number
  /** 机构名称（企业端展示用） */
  institutionName?: string
}

export interface LoginPayload {
  username: string
  password: string
  /**
   * 租户名称（管理端登录必填）。
   *
   * <p>用于防止「账号密码正确但登错租户」：平台/运维同时持有多个租户账号时容易看错。
   * 后端为兼容用户端 H5 与自动化脚本，字段缺省时跳过校验（详见 AuthService.login）。</p>
   */
  tenantName?: string
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
