import { http, unwrap } from './index'
import type { LoginPayload, LoginResult, UserInfo } from '@/types'

export function login(payload: LoginPayload): Promise<LoginResult> {
  return http.post('/auth/login', payload).then(unwrap<LoginResult>)
}

export function me(): Promise<UserInfo> {
  return http.get('/auth/me').then(unwrap<UserInfo>)
}

/**
 * 退出登录（后端仅做审计留痕，令牌吊销由客户端丢弃完成）。
 *
 * <p>`accessToken` 需由调用方显式传入：登出时本地会话已经先被清空，公共请求拦截器
 * 取不到令牌，只能在这里把令牌带上，后端才能把登出事件正确归属到人。</p>
 */
export function logout(accessToken?: string): Promise<void> {
  const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined
  return http.post('/auth/logout', undefined, { headers }).then(() => undefined)
}
