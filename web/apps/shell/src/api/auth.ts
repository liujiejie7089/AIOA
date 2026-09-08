import { http, unwrap } from './index'
import type { LoginPayload, LoginResult, UserInfo } from '@/types'

export function login(payload: LoginPayload): Promise<LoginResult> {
  return http.post('/auth/login', payload).then(unwrap<LoginResult>)
}

export function me(): Promise<UserInfo> {
  return http.get('/auth/me').then(unwrap<UserInfo>)
}

export function logout(): Promise<void> {
  return http.post('/auth/logout').then(() => undefined)
}
