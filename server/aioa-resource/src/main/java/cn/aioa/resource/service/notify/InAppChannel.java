package cn.aioa.resource.service.notify;

import org.springframework.stereotype.Component;

/**
 * 站内信通道：站内信已由写入方落库，本通道只登记投递成功（不重复写 notification 表）。
 *
 * <p>不做任何外部调用，{@link #send} 恒视为成功——其成功语义由「落库」本身保证，
 * 分发器据此写一条 SENT 的 notification_delivery 行以便统一可观测。</p>
 */
@Component
public class InAppChannel implements NotificationChannel {

    @Override
    public String code() {
        return "INAPP";
    }

    @Override
    public void send(DeliveryContext ctx) {
        // 站内信已在写入方落库，此处仅登记投递成功。
    }
}
