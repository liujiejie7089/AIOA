import { computed, ref } from 'vue'
import { http, unwrap } from './index'

/**
 * 机构作用域全局态（V66）。
 *
 * <h3>为什么需要它</h3>
 * <p>顶部原先只有一个<b>租户</b>选择器，而 `tenantScope.ts` 的注入只对 `/tenant/` 前缀生效。
 * 于是「组织与部门」「人员管理」「专家配置」等页面在切换顶部控件后<b>纹丝不动</b> ——
 * 用户反馈的「选择机构后页面和数据没有随之改变」就是这件事。</p>
 *
 * <p>根因不是「少了一个下拉框」，而是<b>没有机构这一层的全局态</b>：
 * 每个页面各持一个本地 `instId`，谁也影响不了谁。这里把它提升为与 `tenantState`
 * 同构的全局态，注入交由 `tenantScope.ts` 中的<b>声明式作用域表</b>统一处理。</p>
 *
 * <h3>语义定稿（两级联动）</h3>
 * <ul>
 *   <li><b>平台管理员</b>：先选租户（顶部租户选择器），再选该租户下属机构；</li>
 *   <li><b>租户管理员</b>：租户是硬边界，顶部只出机构下拉（本租户全部机构）；</li>
 *   <li><b>机构成员</b>：机构硬绑定，选择器隐藏，只显示一个只读标签。</li>
 * </ul>
 */

export interface ScopeInstitution {
  id: number
  name?: string
  code?: string
  tenantId?: number
  status?: string
}

export interface InstitutionScope {
  items: ScopeInstitution[]
  total?: number
  /** 企业管理员 / 租户管理员 true；平台管理员 false（只读运维视角） */
  canWrite: boolean
  /** 机构成员硬绑定的机构 id；租户 / 平台管理员为 null */
  boundInstitutionId?: number | null
  /** ORG（机构成员）/ TENANT（租户管理员）/ PLATFORM（平台管理员） */
  scope?: 'ORG' | 'TENANT' | 'PLATFORM'
}

const institutions = ref<ScopeInstitution[]>([])
const canWrite = ref(false)
const scopeKind = ref<'' | 'ORG' | 'TENANT' | 'PLATFORM'>('')
const boundInstitutionId = ref<number | null>(null)
const loaded = ref(false)
/**
 * 当前机构。注意<b>不做 localStorage 持久化</b>（与租户不同）：
 * 机构 id 是全局唯一的业务实体，跨账号残留它会直接命中「机构不存在或无权访问」（404），
 * 而机构成员本就被硬绑定、平台管理员每次进入都该从「当前租户的第一个机构」重新起步。
 */
const currentId = ref<number | null>(null)

export const institutionState = {
  institutions,
  canWrite,
  scopeKind,
  boundInstitutionId,
  loaded,
  currentId,
  current: computed(() => institutions.value.find((i) => i.id === currentId.value) || null),
  currentName: computed(() => {
    const i = institutions.value.find((x) => x.id === currentId.value)
    return i ? i.name || i.code || `机构 ${i.id}` : ''
  }),
  /** 机构成员：机构是硬边界，前端不提供切换。 */
  canSwitch: computed(() => scopeKind.value !== 'ORG'),
  /** 按租户过滤后的可选机构（平台管理员先选租户再选机构；租户管理员的清单本就只含本租户）。 */
  optionsOfTenant(tenantId: number | null): ScopeInstitution[] {
    if (tenantId == null) return institutions.value
    const hit = institutions.value.filter((i) => i.tenantId === tenantId)
    // 过滤后为空说明该租户下暂无启用机构：此时退回全集不如给空数组（让 UI 明说「本租户暂无机构」）
    return hit
  }
}

/** 拉取当前账号可操作的机构清单，并把「当前机构」落到一个有效值。 */
export async function loadInstitutionScope(): Promise<void> {
  try {
    const s = await http.get('/org/institutions').then((r) => unwrap<InstitutionScope>(r))
    institutions.value = s.items || []
    canWrite.value = !!s.canWrite
    scopeKind.value = s.scope || ''
    boundInstitutionId.value = s.boundInstitutionId ?? null

    if (scopeKind.value === 'ORG') {
      // 机构成员：机构硬绑定，忽略入参与历史残留
      currentId.value = s.boundInstitutionId ?? institutions.value[0]?.id ?? null
    } else {
      const valid = new Set(institutions.value.map((i) => i.id))
      if (currentId.value != null && !valid.has(currentId.value)) {
        currentId.value = null
      }
      if (currentId.value == null) {
        currentId.value = institutions.value[0]?.id ?? null
      }
    }
  } finally {
    // 失败也标记就绪，调用方据此放行子路由，避免页面永久空白
    loaded.value = true
  }
}

/** 切换当前机构。传入的 id 不在可选清单内时忽略，避免越界请求。 */
export function setCurrentInstitution(id: number | null): void {
  if (id == null) {
    currentId.value = null
    return
  }
  if (!institutions.value.some((i) => i.id === id)) {
    return
  }
  currentId.value = id
}

/** 退出登录 / 切换账号时清空，避免跨账号串机构。 */
export function resetInstitutionScope(): void {
  institutions.value = []
  canWrite.value = false
  scopeKind.value = ''
  boundInstitutionId.value = null
  currentId.value = null
  loaded.value = false
}
