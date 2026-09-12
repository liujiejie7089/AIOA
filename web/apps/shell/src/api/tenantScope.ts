import { computed, ref } from 'vue'
import { http, unwrap } from './index'

/**
 * 租户端作用域（V33）。
 *
 * <p>背景：`/api/v1/tenant/*` 此前一律按登录账号自身的 `tenant_id` 过滤。平台管理员的
 * `tenant_id` 恒为 0（平台自身租户），而机构/配额/授权/分摊数据都挂在 2..N 号业务租户下，
 * 于是平台管理员打开「机构管理 / 入驻进度 / 资源授权 / 费用分摊」四个页面全是空态。</p>
 *
 * <p>解法与 `/org/*` 的三级作用域同构：后端新增 `GET /tenant/scope` 返回可操作租户清单，
 * 前端用「当前租户」全局态 + axios 请求拦截器，对**租户端前缀**的请求统一附 `?tenantId=`。
 * 这样四个页面与后续新增页面都自动生效，无需逐个改造。</p>
 */

export interface ScopeTenant {
  id: number
  code?: string
  name?: string
  status?: string
  institutionCount?: number
}

export interface TenantScope {
  items: ScopeTenant[]
  total: number
  /** 平台管理员 true（可切换租户）；租户管理员 false（硬绑定本租户） */
  canSwitch: boolean
  boundTenantId: number | null
  defaultTenantId: number | null
  scope: 'PLATFORM' | 'TENANT'
}

/** 仅对租户端前缀附租户参数，避免污染 /org/*（那套用 institutionId）与全局目录接口 */
const TENANT_API_PREFIX = '/tenant/'
const STORAGE_KEY = 'aioa.tenantId'

const tenants = ref<ScopeTenant[]>([])
const canSwitch = ref(false)
const scopeKind = ref<'' | 'PLATFORM' | 'TENANT'>('')
const loaded = ref(false)
const currentId = ref<number | null>(readStored())

function readStored(): number | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  const n = raw ? Number(raw) : NaN
  return Number.isFinite(n) && n > 0 ? n : null
}

function persist(): void {
  if (currentId.value == null) {
    localStorage.removeItem(STORAGE_KEY)
  } else {
    localStorage.setItem(STORAGE_KEY, String(currentId.value))
  }
}

export const tenantState = {
  tenants,
  canSwitch,
  scopeKind,
  loaded,
  currentId,
  current: computed(() => tenants.value.find((t) => t.id === currentId.value) || null),
  currentName: computed(() => {
    const t = tenants.value.find((x) => x.id === currentId.value)
    return t ? t.name || t.code || `租户 ${t.id}` : ''
  })
}

/** 拉取当前账号可操作的租户清单，并把「当前租户」落到一个有效值。 */
export async function loadTenantScope(): Promise<void> {
  try {
    const s = await http.get('/tenant/scope').then((r) => unwrap<TenantScope>(r))
    tenants.value = s.items || []
    canSwitch.value = !!s.canSwitch
    scopeKind.value = s.scope || ''

    if (!s.canSwitch) {
      // 租户管理员：租户是硬边界，忽略本地缓存。
      // 否则上一个平台管理员留下的 tenantId 会让本账号被判越界（404），页面再次变空。
      currentId.value = s.boundTenantId ?? tenants.value[0]?.id ?? null
    } else {
      const valid = new Set(tenants.value.map((t) => t.id))
      if (currentId.value != null && !valid.has(currentId.value)) {
        currentId.value = null
      }
      if (currentId.value == null) {
        currentId.value = s.defaultTenantId ?? tenants.value[0]?.id ?? null
      }
    }
    persist()
  } finally {
    // 失败也标记就绪，调用方据此放行子路由，避免页面永久空白
    loaded.value = true
  }
}

/** 平台管理员切换当前租户。 */
export function setCurrentTenant(id: number | null): void {
  currentId.value = id
  persist()
}

/** 退出登录 / 切换账号时清空，避免跨账号串租户。 */
export function resetTenantScope(): void {
  currentId.value = null
  tenants.value = []
  canSwitch.value = false
  scopeKind.value = ''
  loaded.value = false
  localStorage.removeItem(STORAGE_KEY)
}

// 全局请求拦截：租户端接口统一带 ?tenantId=，调用方无需感知。
http.interceptors.request.use((cfg) => {
  const url = cfg.url || ''
  if (!url.startsWith(TENANT_API_PREFIX) || currentId.value == null) {
    return cfg
  }
  const params = (cfg.params || {}) as Record<string, unknown>
  // 调用方显式传了 tenantId 时以调用方为准
  cfg.params = 'tenantId' in params ? params : { ...params, tenantId: currentId.value }
  return cfg
})
