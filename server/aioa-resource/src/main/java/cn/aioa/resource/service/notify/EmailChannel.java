package cn.aioa.resource.service.notify;

import org.springframework.stereotype.Component;

/**
 * 邮件通道：继承 HTTP 网关基类，通道码 {@code EMAIL}。
 *
 * <p>必填配置键（服务端校验）：url（http(s):// 开头）、token、from。
 * 收件地址取 {@code sys_user.email}，取不到由分发器记 SKIPPED。</p>
 */
@Component
public class EmailChannel extends HttpGatewayChannel {

    @Override
    public String code() {
        return "EMAIL";
    }
}
