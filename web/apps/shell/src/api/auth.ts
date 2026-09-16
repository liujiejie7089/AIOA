import { http, unwrap } from './index'
import type { LoginPayload, LoginResult, UserInfo } from '@/types'

export function login(payload: LoginPayload): Promise<LoginResult> {
  return http.post('/auth/login', payload).then(unwrap<LoginResult>)
}

export function me(): Promise<UserInfo> {
  return http.get('/auth/me').then(unwrap<UserInfo>)
}

/**
 * 退出登录。
 *
 * <p>V46 起后端会**服务端吊销令牌**（D-1）：把 access / refresh 两个令牌的 jti 写库，
 * 旧令牌立刻失效。因此两个令牌都要带上 —— 只带 access 的话，refresh 仍能换出新令牌，
 * 登出等于没登出。</p>
 *
 * <p>`accessToken` 需由调用方显式传入：登出时本地会话已经先被清空，公共请求拦截器
 * 取不到令牌，只能在这里把令牌带上，后端才能把登出事件正确归属到人并把令牌加入吊销表。</p>
 */
export function logout(accessToken?: string, refreshToken?: string): Promise<void> {
  const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined
  const body = refreshToken ? { refreshToken } : undefined
  return http.post('/auth/logout', body, { headers }).then(() => undefined)
}
