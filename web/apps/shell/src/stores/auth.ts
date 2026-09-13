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
    tenantName: (state) => state.user?.tenantName || state.user?.tenantCode || '默认租户',
    /** 角色码集合（菜单与按钮级权限的判定依据） */
    roles: (state): string[] => state.user?.roles || [],
    hasRole: (state) => (role: string): boolean => (state.user?.roles || []).includes(role),
    /** 平台管理员：跨租户视角 */
    isPlatformAdmin: (state): boolean => (state.user?.roles || []).includes('ROLE_ADMIN'),
    /** 租户管理员：管理本租户机构、资源池、授权、分摊 */
    isTenantAdmin: (state): boolean => (state.user?.roles || []).includes('ROLE_TENANT_ADMIN'),
    /** 企业管理员：管理本机构部门与员工 */
    isOrgAdmin: (state): boolean => (state.user?.roles || []).includes('ROLE_ORG_ADMIN')
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
      const token = this.token
      // 先清本地会话，再best-effort 通知后端 —— 顺序不能反：
      // MainLayout 的 router-view 以登录态为渲染闸门，令牌一旦清空当前页面立即卸载，
      // 不会再在「无令牌」状态下重新挂载并打出一发注定 401 的请求（退出登录时报 401 的根因）。
      this.clearSession()
      try {
        await authApi.logout(token)
      } catch {
        // 后端不可用时也要完成登出（本地态已清）
      }
    },

    /** 清空登录态（登出、令牌失效时共用）。 */
    clearSession(): void {
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
