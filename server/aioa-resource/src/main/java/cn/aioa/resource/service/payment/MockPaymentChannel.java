package cn.aioa.resource.service.payment;

import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 模拟支付通道（一期演示）：createPayment 返回模拟收银台参数，
 * 回调验签恒通过——由受控的 /payments/notify/mock 接口触发，替代真实微信回调。
 */
@Component
public class MockPaymentChannel implements PaymentChannel {

    @Override
    public String code() {
        return "MOCK";
    }

    @Override
    public Map<String, Object> createPayment(String orderNo, int amountCents, String description) {
        return Map.of(
                "channel", "MOCK",
                "orderNo", orderNo,
                "payUrl", "/api/v1/payments/notify/mock/" + orderNo,
                "amountCents", amountCents,
                "description", description,
                "hint", "演示通道：调用 payUrl 即模拟支付成功");
    }

    @Override
    public boolean verifyNotify(String orderNo, String body, String signature) {
        // 演示通道不做真实验签；微信通道实现时在此做证书验签 + 时间戳防重放
        return true;
    }
}
