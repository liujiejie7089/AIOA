import { http, unwrap } from './index'

/**
 * 平台「调整某个租户的资源上限」API 封装（V66 / docs/38 批次 A 的 ③）。
 *
 * <p><b>为什么单独一个文件</b>：本接口原先和「子租户」的封装挤在 `api/subTenant.ts` 里。
 * 2026-09-28 子租户能力按决定移除，本接口与子租户<b>没有任何依赖关系</b>
 * （它改的是顶层租户自己的资源池，走 `QuotaService.upsertPool` 那个唯一写入口），
 * 若跟着一起删掉，平台就失去「事后调整某租户资源上限」的入口（铁律 #4）。
 * 故按能力拆分归属，而不是按「当初谁跟谁写在一起」。</p>
 *
 * <p>路径挂在 `/admin/tenants/{id}/quota`，后端实现是 aioa-org 的
 * `PlatformTenantQuotaController`（复用它才能不复制「总量不得低于已分配量」的既有判定）。</p>
 */

/** 资源调整前后对照（后端 `PUT /admin/tenants/{id}/quota` 返回）。 */
export interface QuotaBeforeAfter {
  before: {
    period?: string
    tokenTotal?: number
    expertSeats?: number
    skillSeats?: number
    [key: string]: unknown
  }
  after: {
    period?: string
    tokenTotal?: number
    expertSeats?: number
    skillSeats?: number
    [key: string]: unknown
  }
}

/** 调整租户的资源上限（周期 / 词元 / 专家席位 / 技能席位），返回调整前后对照。 */
export function updateTenantQuota(
  tenantId: number,
  body: { period?: string; tokenTotal?: number; expertSeats?: number; skillSeats?: number },
): Promise<QuotaBeforeAfter> {
  return http.put(`/admin/tenants/${tenantId}/quota`, body).then((r) => unwrap<QuotaBeforeAfter>(r))
}
