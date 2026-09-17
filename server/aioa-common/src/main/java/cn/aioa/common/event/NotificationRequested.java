package cn.aioa.common.event;

/**
 * 通知触达请求事件（统一消息中心）。
 *
 * <p>用途：让「写站内信」与「多通道分发」解耦——业务域（aioa-resource 的
 * NotificationService、aioa-org 的 ApprovalFlowService）只负责把站内信落库，
 * 再发布本事件；aioa-resource 监听事件后异步分发到邮件 / 短信 / 推送等通道，
 * 两域都只依赖 aioa-common，不产生模块间横向依赖（沿用 TenantProvisionedEvent 先例）。</p>
 *
 * <p>监听方必须**幂等**且**不抛异常**：写通知是主流程，分发只是增强。</p>
 *
 * @param tenantId       租户 id
 * @param userId         接收人（站内信落库时的 user_id）
 * @param type           通知类型（如 APPROVAL / SYSTEM / WORKER）
 * @param title          标题
 * @param content        正文
 * @param refId          关联业务 id（如审批单 id），可空
 * @param actorId        操作人 id，可空（机构侧历史通知无此信息）
 * @param notificationId 落库后的站内通知自增 id；机构侧若拿不到自增 id 则为 null
 */
public record NotificationRequested(Long tenantId, Long userId, String type, String title,
                                    String content, Long refId, Long actorId, Long notificationId) {
}
