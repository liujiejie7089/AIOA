/**
 * 多租户专家配置 API（方案 P7）。
 * 对应后端 ExpertConfigController：/api/v1/expert-config/**。
 */
import { http, unwrap } from './index'

/**
 * 专家领域分类（与后端迁移 V27 对 `ai_expert.category` 的注释同源：
 * LEGAL/LABOR/CONTRACT/IP/COMPLIANCE/TAX/DATA，另加 GENERAL 兜底）。
 *
 * 单独放这里作为**前端唯一入口** —— 模板表单与列表回显都用它，
 * 不在视图里另起一份字面量（否则新增分类时会出现「后端认、下拉里选不到」）。
 */
export const EXPERT_CATEGORIES = [
  { value: 'LEGAL', label: '法律' },
  { value: 'LABOR', label: '劳动用工' },
  { value: 'CONTRACT', label: '合同' },
  { value: 'IP', label: '知识产权' },
  { value: 'COMPLIANCE', label: '合规风控' },
  { value: 'TAX', label: '财税' },
  { value: 'DATA', label: '数据分析' },
  { value: 'GENERAL', label: '通用' }
] as const

/** 领域分类码 → 中文名；未收录时原样显示分类码，不静默吞掉。 */
export const EXPERT_CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  EXPERT_CATEGORIES.map((c) => [c.value, c.label])
) as Record<string, string>

// ================================================================== 类型
export interface ExpertSetting {
  enabled?: boolean
  visibleScope?: string
  defaultEnabled?: boolean
  kbScope?: string
  model?: string
  temperature?: number
  topK?: number
  threshold?: number
  retrievalMode?: string
  tools?: Record<string, boolean>
  sort?: number
  systemPrompt?: string
  knowledgeScope?: string
}

export interface ExpertView extends ExpertSetting {
  id?: number
  expertKey?: string
  name?: string
  icon?: string
  summary?: string
  intro?: string
  category?: string
  templateVersion?: string
  isTenantCopy?: boolean
  sources?: Record<string, string>
}

// ================================================================== API
/** 当前用户可见的专家列表（含生效配置）。 */
export function listExperts(): Promise<ExpertView[]> {
  return http.get('/expert-config/experts').then((r) => unwrap<ExpertView[]>(r))
}

/** 单个专家详情（含覆盖链路）。 */
export function getExpert(key: string): Promise<ExpertView> {
  return http.get(`/expert-config/experts/${key}`).then((r) => unwrap<ExpertView>(r))
}

/** 只取解析结果（验证配置生效）。 */
export function resolveExpert(key: string): Promise<ExpertSetting> {
  return http.get(`/expert-config/experts/${key}/resolve`).then((r) => unwrap<ExpertSetting>(r))
}

/** 全局模板清单。 */
export function listTemplates(): Promise<ExpertView[]> {
  return http.get('/expert-config/templates').then((r) => unwrap<ExpertView[]>(r))
}

/** 从全局模板导入为租户副本。 */
export function importTemplate(key: string): Promise<{ id: number; expertKey: string; created: boolean }> {
  return http
    .post(`/expert-config/templates/${key}/import`)
    .then((r) => unwrap<{ id: number; expertKey: string; created: boolean }>(r))
}

/** 新建/更新全局专家模板的入参（config 为运行参数，落 GLOBAL 层配置片段）。 */
export interface ExpertTemplatePayload {
  /** 模板标识：小写字母开头、2–32 位 a-z0-9_（如 legal / data_analyst）；幂等键 */
  key: string
  name: string
  icon?: string
  summary?: string
  intro?: string
  tags?: string[]
  recs?: string[]
  category?: string
  agentCode?: string
  templateVersion?: string
  visibleScope?: string
  kbScope?: string
  defaultEnabled?: boolean
  sort?: number
  config?: Record<string, unknown>
}

/**
 * 新建/更新全局专家模板（写入 tenant_id=0）。
 *
 * 仅平台管理员可调用（后端 `PermissionCatalog.isPlatformAdmin` 把关，非平台管理员 403）。
 * 幂等键 = `key`：同 key 重复提交是「更新模板」，不会产生第二份；
 * 已导入的租户副本不会自动同步，需租户再点一次「从模板导入」。
 */
export function createTemplate(
  payload: ExpertTemplatePayload
): Promise<{ id: number; expertKey: string; created: boolean; templateVersion?: string; hint?: string }> {
  return http
    .post('/expert-config/templates', payload)
    .then((r) =>
      unwrap<{ id: number; expertKey: string; created: boolean; templateVersion?: string; hint?: string }>(r)
    )
}

/** 写入/替换某层配置片段。 */
export function saveExpertConfig(
  key: string,
  scopeType: string,
  config: Record<string, unknown>,
  scopeId = 0
): Promise<unknown> {
  return http
    .post(`/expert-config/experts/${key}/config`, { scopeType, scopeId, config })
    .then((r) => unwrap<unknown>(r))
}

/** 局部更新某层配置片段。 */
export function patchExpertConfig(
  key: string,
  scopeType: string,
  config: Record<string, unknown>,
  scopeId = 0
): Promise<unknown> {
  return http
    .put(`/expert-config/experts/${key}/config`, { scopeType, scopeId, config })
    .then((r) => unwrap<unknown>(r))
}

/** 删除某层配置片段。 */
export function deleteExpertConfig(key: string, scopeType: string, scopeId = 0): Promise<boolean> {
  return http
    .delete(`/expert-config/experts/${key}/config`, { params: { scopeType, scopeId } })
    .then((r) => unwrap<boolean>(r))
}
