/**
 * 表单域 API（docs/52 P1 管理端表单设计器）。
 *
 * 对接后端 FormController（/api/v1/forms/**）与 FormTemplateService：
 *   - GET    /forms                      列表/筛选（form:manage）
 *   - GET    /forms/{code}               渲染用定义（登录即可；本页编辑时取字段用）
 *   - POST   /forms                      新建定义（form:manage，version=1）
 *   - PUT    /forms/{code}               更新定义（form:manage，自动 version+1）
 *
 * 设计器内部用「可读写的设计模型（FormDesign）」，保存时由 designToSave 转成后端
 * FormSave 形态（code/name/moduleCode/bizType/schemaJson/...），schemaJson 为
 * 标准 JSON Schema（Draft 2020-12），控件类型写在扩展键 x-type 上（与后端 FormFieldMeta 一致）。
 * 导入/导出用更友好的 { fields:[{options:[{value,label}]}] } 形态，与本文件互转。
 */
import { http, unwrap } from './index'

// ================================================================== 类型

/** 设计器里的单个字段（optionsText 为「值=标签」每行一条的可编辑文本）。 */
export interface FormFieldDraft {
  name: string
  label: string
  type: string
  required: boolean
  /** 「值=标签」每行一条；select/multiselect 才有意义，其它类型留空。 */
  optionsText: string
  placeholder: string
}

/** 设计器整体的可读写模型（页面编辑态的唯一真相）。 */
export interface FormDesign {
  code: string
  name: string
  moduleCode: string
  /** 提交后进审批的 bizType；空=不走审批。 */
  bizType: string
  submitPolicy: string
  fields: FormFieldDraft[]
}

/** 列表返回的表单模板（= 后端 FormTemplate 实体，含 bizType / version 等；不含字段明细）。 */
export interface FormTemplate {
  id?: number
  code: string
  name: string
  moduleCode?: string
  bizType?: string
  submitPolicy?: string
  version?: number
  status?: string
}

/** MyBatis-Plus IPage 分页结构（unwrap 后）。 */
export interface PageResult<T> {
  records: T[]
  total: number
  size: number
  current: number
  pages: number
}

/** 渲染用字段（GET /forms/{code} 返回，options 已解析为 {value,label} 数组）。 */
export interface FormRenderField {
  name: string
  label: string
  type: string
  required: boolean
  options?: Array<{ value: unknown; label: unknown }>
  placeholder?: string
  validation?: Record<string, unknown> | null
  default?: unknown
}

/** 渲染用整张表单（GET /forms/{code} 返回）。注意：此载荷不含 bizType，bizType 以列表记录为准。 */
export interface FormRender {
  templateId: number
  code: string
  name: string
  version: number
  moduleCode: string
  submitPolicy: string
  fields: FormRenderField[]
}

/** 后端 FormSave 的提交形态（schemaJson 由 designToSave 生成）。 */
interface FormSavePayload {
  code: string
  name: string
  moduleCode: string | null
  bizType: string | null
  schemaJson: string
  layoutJson: string | null
  submitPolicy: string
  receiptJson: string | null
}

// ================================================================== 接口

/** 管理端列表/筛选（form:manage）。 */
export function listForms(params: {
  moduleCode?: string
  status?: string
  page?: number
  size?: number
}): Promise<PageResult<FormTemplate>> {
  return http.get('/forms', { params }).then((r) => unwrap<PageResult<FormTemplate>>(r))
}

/** 取渲染用定义（ACTIVE 版本，含解析后的字段与选项）。 */
export function getForm(code: string): Promise<FormRender> {
  return http.get(`/forms/${code}`).then((r) => unwrap<FormRender>(r))
}

/** 新建表单定义（version=1）。 */
export function createForm(design: FormDesign): Promise<FormTemplate> {
  return http.post('/forms', designToSave(design)).then((r) => unwrap<FormTemplate>(r))
}

/** 更新表单定义（自动 version+1）。 */
export function updateForm(code: string, design: FormDesign): Promise<FormTemplate> {
  return http.put(`/forms/${code}`, designToSave(design)).then((r) => unwrap<FormTemplate>(r))
}

// ================================================================== 域转换（前端唯一判定点，勿在视图里另写一份）

/** 把「值=标签」每行一条的文本解析成 {value,label} 数组；空行跳过；无 `=` 则值=标签。 */
export function parseOptionEntries(text: string): Array<{ value: string; label: string }> {
  const out: Array<{ value: string; label: string }> = []
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const idx = line.indexOf('=')
    if (idx === -1) out.push({ value: line, label: line })
    else out.push({ value: line.slice(0, idx).trim(), label: line.slice(idx + 1).trim() })
  }
  return out
}

/** 把 {value,label} 数组还原成「值=标签」每行一条的文本（解析的逆操作）。 */
export function optionsToText(list: Array<{ value: unknown; label: unknown }>): string {
  if (!Array.isArray(list)) return ''
  return list
    .map((o) => (o && typeof o === 'object' ? `${o.value ?? ''}=${o.label ?? ''}` : String(o)))
    .join('\n')
}

/** 控件类型 → 标准 JSON Schema 的 type（与后端 resolveForRender / 提交校验口径一致）。 */
function schemaBaseType(type: string): { type: string; format?: string } {
  switch (type) {
    case 'number':
    case 'amount':
      return { type: 'number' }
    case 'boolean':
      return { type: 'boolean' }
    case 'date':
      return { type: 'string', format: 'date' }
    case 'datetime':
      return { type: 'string', format: 'date-time' }
    case 'multiselect':
      return { type: 'array' }
    default:
      // text / textarea / select / file 等统一用 string
      return { type: 'string' }
  }
}

/** 设计模型 → 后端 FormSave 形态（生成 schemaJson）。 */
export function designToSave(d: FormDesign): FormSavePayload {
  const properties: Record<string, Record<string, unknown>> = {}
  const required: string[] = []
  for (const f of d.fields) {
    if (!f.name) continue
    const prop: Record<string, unknown> = { 'x-type': f.type, title: f.label || f.name }
    if (f.placeholder) prop.description = f.placeholder
    const base = schemaBaseType(f.type)
    prop.type = base.type
    if (base.format) prop.format = base.format
    if (f.type === 'select' || f.type === 'multiselect') {
      const entries = parseOptionEntries(f.optionsText)
      prop.enum = entries.map((e) => e.value)
      prop.enumNames = entries.map((e) => e.label)
    }
    if (f.required) required.push(f.name)
    properties[f.name] = prop
  }
  const schema: Record<string, unknown> = { type: 'object', properties }
  if (required.length) schema.required = required
  return {
    code: d.code,
    name: d.name,
    moduleCode: d.moduleCode || null,
    bizType: d.bizType || null,
    schemaJson: JSON.stringify(schema),
    layoutJson: null,
    submitPolicy: d.submitPolicy || 'LEDGER',
    receiptJson: null
  }
}

/** 渲染字段 → 设计器字段草稿（options 数组转回「值=标签」文本）。 */
export function renderToFieldDraft(f: FormRenderField): FormFieldDraft {
  return {
    name: f.name,
    label: f.label,
    type: f.type,
    required: !!f.required,
    optionsText: optionsToText(f.options || []),
    placeholder: f.placeholder || ''
  }
}

/** 渲染整张表单 → 设计器字段列表（仅字段；头部信息以列表记录为准）。 */
export function renderToFields(r: FormRender): FormFieldDraft[] {
  return (r.fields || []).map(renderToFieldDraft)
}

/** 设计模型 → 导出 JSON 字符串（options 以 {value,label} 数组呈现，便于人读与回灌）。 */
export function designToExportJson(d: FormDesign): string {
  const obj = {
    code: d.code,
    name: d.name,
    moduleCode: d.moduleCode,
    bizType: d.bizType,
    submitPolicy: d.submitPolicy,
    fields: d.fields.map((f) => ({
      name: f.name,
      label: f.label,
      type: f.type,
      required: f.required,
      placeholder: f.placeholder,
      options: parseOptionEntries(f.optionsText)
    }))
  }
  return JSON.stringify(obj, null, 2)
}

/**
 * 导入 JSON 字符串 → 设计模型。
 *
 * <p>解析失败（非法 JSON / 缺字段 / 字段结构不对）统一抛出中文错误，由调用方捕获后提示，
 * 绝不把异常抛到渲染层导致白屏。</p>
 */
export function exportJsonToDesign(json: string): FormDesign {
  let obj: unknown
  try {
    obj = JSON.parse(json)
  } catch {
    throw new Error('JSON 解析失败：请检查是否为合法的 JSON 文本')
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new Error('导入失败：根节点必须是一个对象（含 code / name / fields 等）')
  }
  const root = obj as Record<string, unknown>
  if (!Array.isArray(root.fields)) {
    throw new Error('导入失败：缺少 fields 数组（应为 [{ name, label, type, ... }]）')
  }
  const fields: FormFieldDraft[] = (root.fields as unknown[]).map((item, i) => {
    if (!item || typeof item !== 'object') {
      throw new Error(`导入失败：第 ${i + 1} 个字段不是对象`)
    }
    const f = item as Record<string, unknown>
    if (typeof f.name !== 'string' || !f.name) {
      throw new Error(`导入失败：第 ${i + 1} 个字段缺少字符串 name`)
    }
    if (typeof f.type !== 'string' || !f.type) {
      throw new Error(`导入失败：字段「${f.name}」缺少字符串 type`)
    }
    let optionsText = ''
    if (Array.isArray(f.options)) {
      optionsText = optionsToText(f.options as Array<{ value: unknown; label: unknown }>)
    } else if (typeof f.optionsText === 'string') {
      optionsText = f.optionsText
    }
    return {
      name: f.name,
      label: typeof f.label === 'string' ? f.label : f.name,
      type: f.type,
      required: !!f.required,
      optionsText,
      placeholder: typeof f.placeholder === 'string' ? f.placeholder : ''
    }
  })
  return {
    code: typeof root.code === 'string' ? root.code : '',
    name: typeof root.name === 'string' ? root.name : '',
    moduleCode: typeof root.moduleCode === 'string' ? root.moduleCode : '',
    bizType: typeof root.bizType === 'string' ? root.bizType : '',
    submitPolicy: typeof root.submitPolicy === 'string' ? root.submitPolicy : 'LEDGER',
    fields
  }
}
