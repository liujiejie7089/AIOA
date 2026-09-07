import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'
import { REFRESH_TOKEN_KEY, TOKEN_KEY, USER_KEY } from '@/api'
import type { LoginPayload, UserInfo } from '@/types'

function readUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as UserInfo) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY) || '',
    user: readUser(),
    permissions: [] as string[],
    loading: false
  }),
  getters: {
    isLogin: (state) => !!state.token,
    displayName: (state) => state.user?.displayName || state.user?.username || '未登录',
    tenantName: (state) => state.user?.tenantName || state.user?.tenantCode || '默认租户'
  },
  actions: {
    async login(payload: LoginPayload): Promise<void> {
      this.loading = true
      try {
        const result = await authApi.login(payload)
        this.token = result.accessToken
        this.refreshToken = result.refreshToken || ''
        this.user = result.user
        localStorage.setItem(TOKEN_KEY, this.token)
        localStorage.setItem(REFRESH_TOKEN_KEY, this.refreshToken)
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      } finally {
        this.loading = false
      }
    },

    async me(): Promise<void> {
      const user = await authApi.me()
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },

    async logout(): Promise<void> {
      try {
        await authApi.logout()
      } catch {
        // 后端不可用时也要清理本地态
      }
      this.token = ''
      this.refreshToken = ''
      this.user = null
      this.permissions = []
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    }
  }
})
