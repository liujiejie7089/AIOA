import { defineStore } from 'pinia'
import * as appsApi from '@/api/apps'
import type { AppEntry } from '@/types'

export const useAppsStore = defineStore('apps', {
  state: () => ({
    items: [] as AppEntry[],
    loading: false,
    loaded: false,
    error: ''
  }),
  getters: {
    enabled(): AppEntry[] {
      return this.items.filter((item) => item.enabled !== false)
    },
    byCode(): Record<string, AppEntry> {
      return this.items.reduce<Record<string, AppEntry>>((acc, item) => {
        acc[item.appCode] = item
        return acc
      }, {})
    },
    /** 菜单里的「我的应用」分组 */
    menuItems(): AppEntry[] {
      return this.enabled
    }
  },
  actions: {
    async list(force = false): Promise<void> {
      if (this.loading) return
      if (this.loaded && !force) return
      this.loading = true
      this.error = ''
      try {
        this.items = await appsApi.list()
        this.loaded = true
      } catch (error) {
        // 后端未启动时降级为空列表，页面按空态展示
        this.error = error instanceof Error ? error.message : '应用列表加载失败'
        this.items = []
      } finally {
        this.loading = false
      }
    },
    getByCode(appCode: string): AppEntry | undefined {
      return this.byCode[appCode]
    }
  }
})
