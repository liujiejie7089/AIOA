package cn.aioa.resource.service.notify;

/**
 * 通知通道适配接口（统一消息中心）。
 *
 * <p>每个通道一个实现（INAPP/EMAIL/SMS/PUSH）。非站内通道一律走可配置 HTTP 网关
 * （{@link HttpGatewayChannel} 基类），不引入任何新依赖。
 * {@link #send} 抛异常即视为投递失败，由分发器登记 FAILED + last_error。</p>
 */
public interface NotificationChannel {

    /** 通道标识（channel_code 字段取值）。 */
    String code();

    /** 投递一次。2xx 视为成功；非 2xx 或异常请抛出，由分发器统一登记。 */
    void send(DeliveryContext ctx) throws Exception;
}
