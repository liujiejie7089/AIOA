import axios from 'axios'

/** localStorage 持久化键（auth store 与本文件共用，避免循环依赖） */
export const TOKEN_KEY = 'aioa.token'
export const REFRESH_TOKEN_KEY = 'aioa.refreshToken'
export const USER_KEY = 'aioa.user'

/**
 * 接口基址。
 *
 * <p>生产：产物挂在 `https://<域名>/aioa/web/` 下，而**外网入口只反代 `/aioa/`**
 * （原样转发、不剥前缀）⇒ 写死根路径 `/api/v1` 会打到域名根下未被代理的路径，全部 404。
 * dev：Vite base 为 `/`（见 vite.config.ts，本地 10+ 套 UI 套件都按 `localhost:5173/xxx` 跑），
 * 走 vite 的 `/api` 代理即可。</p>
 *
 * <p>两者同源于 `import.meta.env.BASE_URL`（router 的 createWebHistory 也用它），
 * 不再各写一份 —— 生产 `/aioa/web/` ⇒ `/aioa/api/v1`，dev `/` ⇒ `/api/v1`。
 * 用户端 H5 的 `apiBaseFromPath()` 是同一口径（`/aioa/h5/` ⇒ `/aioa/api`）。</p>
 */
const API_PREFIX = import.meta.env.BASE_URL.replace(/web\/$/, '').replace(/\/$/, '')
export const API_BASE = `${API_PREFIX}/api/v1`

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

let unauthorizedHandler: () => void = () => {}

/** 由 router/main 注入，避免 api → router → store → api 的循环依赖 */
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      unauthorizedHandler()
    }
    return Promise.reject(error)
  }
)

/** 业务错误（HTTP 200 + code≠0）抛出的异常，携带后端业务码，便于调用方按码分支。 */
export class ApiError extends Error {
  readonly code: number
  constructor(code: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

/**
 * 统一取后端响应体：后端返回 ApiResponse<T> = { code, message, data }，这里剥到真正的业务数据。
 *
 * <p><b>为什么必须校验 code</b>：后端「业务失败」走的是 HTTP 200 + {@code code≠0}
 * （只有 401/403/404 才改 HTTP 状态码），且 Jackson 配了
 * {@code default-property-inclusion: non_null}，失败响应里根本没有 {@code data} 字段。
 * 旧实现只在 {@code body 同时含 code 与 data} 时才剥一层，于是：
 * 失败响应 → 返回整个信封 {@code {code,message}} 当作业务数据 → 调用方拿到
 * {@code undefined} 字段继续往下走（登录态存成 {@code "undefined"}、列表变空白），
 * 既不报错也没有任何提示。这正是「页面空白且无任何数据」这类缺陷的共同根因。</p>
 */
export function unwrap<T>(res: { data: unknown }): T {
  const body = res.data
  if (body && typeof body === 'object' && 'code' in body && 'message' in body) {
    const envelope = body as { code: number; message?: string; data?: T }
    // 仅当 code 是数字时才按统一信封处理：业务 DTO 里也可能有名为 code 的字符串字段
    // （如机构编码 ORG-FAGAI），那种响应不是信封，必须原样返回。
    if (typeof envelope.code === 'number') {
      if (envelope.code !== 0) {
        throw new ApiError(envelope.code, envelope.message || '请求失败')
      }
      return envelope.data as T
    }
  }
  return body as T
}
