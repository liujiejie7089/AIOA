import axios from 'axios'

/** localStorage 持久化键（auth store 与本文件共用，避免循环依赖） */
export const TOKEN_KEY = 'aioa.token'
export const REFRESH_TOKEN_KEY = 'aioa.refreshToken'
export const USER_KEY = 'aioa.user'

export const http = axios.create({
  baseURL: '/api/v1',
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

/** 统一取后端响应体（兼容 { data } 与裸对象） */
export function unwrap<T>(res: { data: T }): T {
  return res.data
}
