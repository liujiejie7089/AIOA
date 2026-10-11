import { http, unwrap } from './index'

/**
 * 机构参数配置（需求二 / docs/44 §2.4）。
 *
 * <p>本文件是「后端 {@code aioa-admin} 模块 `/admin/org-configs` 契约」在前端的唯一映射入口，
 * 字段名与后端返回体**逐字对应**，不在视图里另起一套字面量。</p>
 *
 * <p>三层同源：菜单（MainLayout.showOrgConfigMenu）→ 路由 meta.allowRoles（ORG_CONFIG_ROLES）
 * → 后端 {@code PermissionCatalog.ORG_CONFIG_MANAGE}（权限码 {@code org:config:manage}，角色集 {@code ORG_ADMINS}）。</p>
 *
 * <p>数据范围由后端按调用者档位收窄：平台/租户管理员可切换机构，机构管理员被钉死本机构
 * （返回 {@code scopeLocked=true}）。省略 {@code institutionId} 且本应可切换机构时，
 * GET 返回 {@code institutionId=null & items=[]}，由前端先让用户选机构；
 * PUT/DELETE 省略 {@code institutionId} 则后端 400「请先选择机构」。</p>
 */

/** 可切换机构选项。 */
export interface OrgOption {
  id: number
  name: string
}

/** 单条机构参数。tenantValue 是继承源，orgValue 是本机构覆盖值（null=未覆盖），effectiveValue 是生效值。 */
export interface OrgConfigItem {
  configKey: string
  configName: string
  groupCode: string
  valueType: string
  /** 租户级（继承源）。 */
  tenantValue: string
  /** 本机构覆盖值；null = 未覆盖（继承租户值）。 */
  orgValue: string | null
  /** 生效值（覆盖优先，否则继承租户值）。 */
  effectiveValue: string
  /** 本机构是否已覆盖租户值。 */
  overridden: boolean
}

/** GET /admin/org-configs 返回体。 */
export interface OrgConfigPage {
  institutions: OrgOption[]
  /** true = 机构被钉死（机构管理员，只能看本机构）。 */
  scopeLocked: boolean
  canManage: boolean
  institutionId: number | null
  items: OrgConfigItem[]
  /** groupCode → 中文分组名（后端唯一一处定义，与「系统参数」页同源）。可选，容错旧后端。 */
  groups?: Record<string, string>
}

/** PUT /admin/org-configs 请求体。 */
export interface OrgConfigUpdateBody {
  institutionId?: number
  configKey: string
  configValue: string
}

/** 读取机构参数（按机构）。省略 institutionId 且可切换机构 → 返回 institutionId=null、items=[]。 */
export function getOrgConfigs(institutionId?: number | null) {
  return http
    .get('/admin/org-configs', { params: institutionId == null ? {} : { institutionId } })
    .then((r) => unwrap<OrgConfigPage>(r))
}

/** 覆盖某机构参数。 */
export function putOrgConfig(body: OrgConfigUpdateBody) {
  return http.put('/admin/org-configs', body).then((r) => unwrap<OrgConfigItem>(r))
}

/** 恢复继承（删除本机构覆盖）。 */
export function deleteOrgConfig(institutionId: number, configKey: string) {
  return http
    .delete('/admin/org-configs', { params: { institutionId, configKey } })
    .then((r) => unwrap<void>(r))
}
