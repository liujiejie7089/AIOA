/**
 * 多租户专家配置 API（方案 P7）。
 * 对应后端 ExpertConfigController：/api/v1/expert-config/**。
 */
import { http, unwrap } from './index'

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
