import { http, unwrap } from './index'
import type { AppEntry } from '@/types'

export function list(): Promise<AppEntry[]> {
  return http.get('/apps').then(unwrap)
}
