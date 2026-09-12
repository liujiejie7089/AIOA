package cn.aioa.common.event;

/**
 * 租户/机构完成入驻（新机构落库）时发布的领域事件。
 *
 * <p>用途：让「数字员工预置」等租户级初始化动作与「机构入驻」解耦——
 * 企业域（aioa-org）只管入驻，能力域（aioa-resource）监听事件后按需预置，
 * 两者都只依赖 aioa-common，不产生模块间横向依赖。</p>
 *
 * <p>监听方必须**幂等**且**不抛异常**：入驻是主流程，预置只是增强。</p>
 *
 * @param tenantId        租户 id
 * @param institutionId   机构 id
 * @param institutionName 机构名称（用于日志/审计可读性）
 */
public record TenantProvisionedEvent(Long tenantId, Long institutionId, String institutionName) {
}
