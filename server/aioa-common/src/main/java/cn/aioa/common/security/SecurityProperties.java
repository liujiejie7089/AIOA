package cn.aioa.common.security;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 安全相关配置（{@code aioa.security.*}）。
 *
 * <p>{@code allow-private-hosts}：是否放行回环 / RFC1918 / link-local / 0.0.0.0。
 * 默认值随 profile 走（见 {@link UrlHostGuard#resolveAllowPrivate}）：</p>
 * <ul>
 *   <li>显式配置（含环境变量 {@code AIOA_SECURITY_ALLOW_PRIVATE_HOSTS}）→ 用配置值；</li>
 *   <li>未配置：prod → false；其它（dev/local/test/default）→ true。</li>
 * </ul>
 * 字段用 {@link Boolean}（对象）以区分「用户显式设为 false」与「未配置」。
 */
@Component
@ConfigurationProperties(prefix = "aioa.security")
public class SecurityProperties {

    private Boolean allowPrivateHosts;

    public Boolean getAllowPrivateHosts() {
        return allowPrivateHosts;
    }

    public void setAllowPrivateHosts(Boolean allowPrivateHosts) {
        this.allowPrivateHosts = allowPrivateHosts;
    }
}
