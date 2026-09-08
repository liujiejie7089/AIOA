package cn.aioa.resource.service.payment;

import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 微信支付通道（二期接入占位）：
 * 接入时实现 createPayment（JSAPI/Native 下单拿 prepay_id）与
 * verifyNotify（平台证书验签 + 通知 ID 去重防重放），订单侧零改动。
 */
@Component
public class WechatPaymentChannel implements PaymentChannel {

    @Override
    public String code() {
        return "WECHAT";
    }

    @Override
    public Map<String, Object> createPayment(String orderNo, int amountCents, String description) {
        throw new UnsupportedOperationException("微信支付通道二期接入，当前请使用 MOCK 演示通道");
    }

    @Override
    public boolean verifyNotify(String orderNo, String body, String signature) {
        throw new UnsupportedOperationException("微信支付通道二期接入，当前请使用 MOCK 演示通道");
    }
}
