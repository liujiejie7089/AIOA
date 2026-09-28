import { computed, ref } from 'vue'
import { http, unwrap } from './index'
import { institutionState, resetInstitutionScope } from './institutionScope'

/**
 * 租户端作用域（V33）。
 *
 * <p>背景：`/api/v1/tenant/*` 此前一律按登录账号自身的 `tenant_id` 过滤。平台管理员的
 * `tenant_id` 恒为 0（平台自身租户），而机构/配额/授权/分摊数据都挂在 2..N 号业务租户下，
 * 于是平台管理员打开「机构管理 / 入驻进度 / 资源授权 / 费用分摊」四个页面全是空态。</p>
 *
 * <p>解法与 `/org/*` 的三级作用域同构：后端新增 `GET /tenant/scope` 返回可操作租户清单，
 * 前端用「当前租户」全局态 + axios 请求拦截器，对**已声明的作用域前缀**统一附 `?tenantId=`。
 * 因此「哪些页面随顶部选择器变化」= `SCOPE_PARAMS` 表里的前缀 —— 新增页面先在这里声明，
 * 后端同一端点必须真的接 `tenantId`，否则就是「声明了却不生效」（铁律 #1）。</p>
 *
 * <p>2026-09-28 补：`/admin/quotas`（配额管理）。它的接口族独立挂在 `/admin/` 下，
 * 原先不在表里 ⇒ 顶部切换租户后本页数据不变（用户反馈「配额管理不能切换租户」）。</p>
 *
 * <p>本文件同时是<b>作用域注入的唯一出口</b>：机构作用域（`institutionScope.ts`）的全局态
 * 也由这里的 {@code SCOPE_PARAMS} 表声明并注入 —— 注入逻辑只有一份，
 * 不会出现「租户生效、机构不生效」这类两套口径打架。</p>
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
  /**
   * 服务端当前统计期（yyyy-MM）。
   *
   * <p>资源池 / 机构配额 / 分摊 / 账本一律按 {@code (tenant_id, period)} 定位，
   * 而 period 只能由服务端裁决：此前各页各自用 {@code new Date()} 推导，
   * 与服务器时钟或时区一旦不一致，就会去查一个根本不存在的周期，
   * 页面表现为全空、或「资源池尚未交付」。这里把它作为唯一权威下发。</p>
   */
  currentPeriod?: string
}

/** 仅对已声明的作用域前缀附作用域参数，避免污染全局目录接口 */
const STORAGE_KEY = 'aioa.tenantId'

/**
 * 声明式作用域参数表（<b>单一入口</b>）。
 *
 * <p>「哪个接口族吃哪个作用域参数」在这里<b>一处声明</b> —— 而不是靠 URL 前缀在各调用点各自推断。
 * 历史上只有一条隐式规则「URL 以 `/tenant/` 开头才附 tenantId」，于是 `/org/*`
 * 完全不参与顶部选择器，用户反馈的「选择机构后页面和数据没有随之改变」即由此而来。</p>
 *
 * <p>新增一个吃机构参数的接口族时，只改这张表；要判断某页面是否「随选择变化」，
 * 也只需对照这张表看它的请求前缀 —— 展示与事实同源（铁律 #1）。</p>
 */
const SCOPE_PARAMS: readonly { prefix: string; param: 'tenantId' | 'institutionId' }[] = [
  { prefix: '/tenant/', param: 'tenantId' },
  { prefix: '/org/', param: 'institutionId' },
  // 配额管理是租户级管理页，但接口挂在 /admin/quotas —— 不声明就在这里，顶部切了租户它也纹丝不动
  // （实测：平台管理员在 t2/t3 之间切换，本页始终返回同一份数据，因为后端只认 JWT 里的 tenantId=0）。
  // 只声明这一个具体前缀，不整族放开 /admin/：/admin/models、/admin/apps、/admin/configs 等
  // 有的是平台级、有的后端根本不接 tenantId —— 声明了却不生效，比不声明更坏（铁律 #1）。
  { prefix: '/admin/quotas', param: 'tenantId' }
]

/** 作用域端点自身不吃作用域参数（它的职责就是回答「我有哪些可选项」）。 */
const SCOPE_ENDPOINTS: readonly string[] = ['/org/institutions']

/** 顶部「当前租户」选择器实际驱动的接口族；供文档与静态守卫比对，避免文案写出「全站生效」。 */
export const SCOPE_DRIVEN_PREFIXES: readonly string[] = SCOPE_PARAMS.map((r) => r.prefix)

const tenants = ref<ScopeTenant[]>([])
const canSwitch = ref(false)
const scopeKind = ref<'' | 'PLATFORM' | 'TENANT'>('')
const loaded = ref(false)
const currentId = ref<number | null>(readStored())
/** 服务端当前统计期（yyyy-MM）；未加载时为空串 —— 空串不下发给后端，由后端同口径兜底。 */
const currentPeriod = ref('')

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
  currentPeriod,
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
    currentPeriod.value = s.currentPeriod || ''

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

/** 退出登录 / 切换账号时清空，避免跨账号串租户（机构作用域同批清空）。 */
export function resetTenantScope(): void {
  currentId.value = null
  tenants.value = []
  canSwitch.value = false
  scopeKind.value = ''
  currentPeriod.value = ''
  loaded.value = false
  localStorage.removeItem(STORAGE_KEY)
  resetInstitutionScope()
}

// 全局请求拦截（作用域注入的<b>唯一</b>出口）：
//   1) 剔除空的 period —— 周期只能由服务端裁决（后端 Vals.nowPeriod() 兜底），
//      前端传空串会让后端按「字面空周期」查询，查到的是不存在的周期；
//   2) 按上面那张声明式作用域表注入 tenantId / institutionId，
//      调用方显式传了同名字段则以调用方为准。
http.interceptors.request.use((cfg) => {
  const params = { ...((cfg.params || {}) as Record<string, unknown>) }
  for (const [k, v] of Object.entries(params)) {
    if (k === 'period' && (v == null || v === '')) {
      delete params[k]
    }
  }
  const url = cfg.url || ''
  if (!SCOPE_ENDPOINTS.includes(url)) {
    for (const rule of SCOPE_PARAMS) {
      if (!url.startsWith(rule.prefix)) continue
      if (!(rule.param in params)) {
        const v = rule.param === 'tenantId' ? currentId.value : institutionState.currentId.value
        if (v != null) params[rule.param] = v
      }
      break
    }
  }
  cfg.params = params
  return cfg
})
