package cn.aioa.resource.service.notify;

import org.springframework.stereotype.Component;

/**
 * 移动推送通道：继承 HTTP 网关基类，通道码 {@code PUSH}。
 *
 * <p>必填配置键（服务端校验）：url（http(s):// 开头）、token；可选 titleTemplate（≤64）。
 * 收件地址（设备令牌）当前数据模型尚未建模，由分发器记 SKIPPED（已知限制，如实记录）。</p>
 */
@Component
public class PushChannel extends HttpGatewayChannel {

    @Override
    public String code() {
        return "PUSH";
    }
}
