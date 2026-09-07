import { http, unwrap } from './index'
import type { LoginPayload, LoginResult, UserInfo } from '@/types'

export function login(payload: LoginPayload): Promise<LoginResult> {
  return http.post('/auth/login', payload).then(unwrap)
}

export function me(): Promise<UserInfo> {
  return http.get('/auth/me').then(unwrap)
}

export function logout(): Promise<void> {
  return http.post('/auth/logout').then(() => undefined)
}
