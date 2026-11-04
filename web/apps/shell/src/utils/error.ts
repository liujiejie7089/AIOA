import { ElMessage } from 'element-plus'

/**
 * 统一错误展示（管理端，docs/73）。
 *
 * <p>后端所有失败都回同一结构：</p>
 * <pre>{ code, errorCode, category, message, suggestion, traceId, details }</pre>
 *
 * <p>界面只做三件事：</p>
 * <ol>
 *   <li>主文案用 <b>message</b>（后端已保证是人话，不含类名/SQL/路径/堆栈）；</li>
 *   <li>有 <b>suggestion</b> 就追一句「建议：…」，让用户知道下一步做什么；</li>
 *   <li>内部错误（INTERNAL_ERROR）把 <b>traceId</b> 以「错误编号」形式露出，方便报障对账。</li>
 * </ol>
 *
 * <p><b>不要</b>把 `error.stack`、`error.message` 里可能夹带的原始响应直接拼到界面上 ——
 * 那正是 2026-11-04 用户看到 `生成失败：{"code":"MODEL_UPSTREAM_ERROR",...,"detail":...}` 的成因。</p>
 */

/** 与本文件同源的错误码兜底文案：后端没给 message 时也能说人话（按 errorCode 分支，不匹配中文）。 */
const FALLBACK: Record<string, string> = {
  VALIDATION_FAILED: '提交的内容有误，请按提示修改后重试',
  PARAM_INVALID: '请求参数不合法',
  PARAM_MISSING: '缺少必填参数',
  BODY_UNREADABLE: '请求内容不是合法的 JSON',
  UNAUTHENTICATED: '登录状态已失效，请重新登录',
  PERMISSION_DENIED: '当前账号没有这个操作的权限',
  RESOURCE_NOT_FOUND: '要找的内容不存在或已被删除',
  API_NOT_FOUND: '接口地址不存在',
  STATE_CONFLICT: '数据状态已变化，本次操作没有生效',
  RATE_LIMITED: '操作太频繁，已被限流',
  MODEL_UPSTREAM_ERROR: '模型服务本次没有返回结果',
  MODEL_NOT_FOUND: '配置的模型已下线或不存在',
  MODEL_AUTH_FAILED: '模型密钥无效或没有调用权限',
  MODEL_RATE_LIMITED: '模型调用过于频繁',
  MODEL_TIMEOUT: '模型响应超时',
  CONNECTOR_ERROR: '连接的外部应用调用失败',
  INTERNAL_ERROR: '服务内部出错了，本次操作没有完成',
  NOT_IMPLEMENTED: '该功能尚未开放'
}

/** 后端错误信封里我们关心的字段（与 `ApiError` 对应）。 */
export interface ErrorLike {
  message?: string
  errorCode?: string | null
  category?: string | null
  suggestion?: string | null
  traceId?: string | null
  code?: number | string | null
  details?: Array<{ field: string; message: string }> | null
}

/** 是否像「技术细节」：JSON 片段、类名、堆栈、SQL。命中则不直接展示。 */
function looksTechnical(text: string): boolean {
  return (
    /^\s*[{[]/.test(text) ||
    /\b(java|javax|org\.springframework|com\.mysql|cn\.aios)\b/.test(text) ||
    /\bat\s+[\w.$]+\(.*:\d+\)/.test(text) ||
    /\b(select|insert into|update\s+\w+\s+set|delete from)\b/i.test(text) ||
    /\b(SQLException|NullPointerException|Exception:)\b/.test(text)
  )
}

/**
 * 把任意异常/信封整理成「可直接展示」的文本。
 *
 * @param withTrace 内部错误是否附带错误编号（默认 true：这是用户报障的唯一凭据）
 */
export function describeError(e: unknown, opts: { withTrace?: boolean } = {}): string {
  const withTrace = opts.withTrace !== false
  const err = (e || {}) as ErrorLike & { rawMessage?: string | null }
  let msg = (err.rawMessage || err.message || '').trim()
  if (!msg || looksTechnical(msg)) {
    msg = (err.errorCode && FALLBACK[err.errorCode]) || '操作没有完成，请稍后重试'
  }
  let out = msg
  if (err.suggestion) out += `（建议：${err.suggestion}）`
  if (withTrace && err.category === 'INTERNAL' && err.traceId) out += `［错误编号 ${err.traceId}］`
  return out
}

/** 字段级错误 → 「字段：原因」列表（表单类页面用来标红/汇总）。 */
export function fieldErrors(e: unknown): string[] {
  const details = (e as ErrorLike)?.details
  if (!details || !details.length) return []
  return details.map((d) => `${d.field}：${d.message}`)
}

/** 错误提示（顶部轻提示）：统一入口，避免每个视图各拼一套。 */
export function toastError(e: unknown, prefix = ''): void {
  ElMessage.error(prefix + describeError(e))
}
