package cn.aioa.resource.service.payment;

import java.util.Map;

/**
 * 支付通道适配接口（FR-G4：一期 MOCK 演示，二期接微信支付）。
 *
 * 技术方案要求：支付回调必须「验签 + 防重放」。通道实现负责验签，
 * 订单侧以状态机（PENDING→PAID 单向）+ 幂等处理防重放。
 */
public interface PaymentChannel {

    /** 通道标识（订单 pay_channel 字段取值）。 */
    String code();

    /**
     * 创建支付：返回给前端的支付凭据（微信支付时为 prepay 签名参数等）。
     *
     * @param orderNo    订单号
     * @param amountCents 金额（分）
     * @param description 商品描述
     */
    Map<String, Object> createPayment(String orderNo, int amountCents, String description);

    /**
     * 验签回调通知：合法返回 true。MOCK 通道恒真；微信通道做证书/签名校验。
     */
    boolean verifyNotify(String orderNo, String body, String signature);
}
