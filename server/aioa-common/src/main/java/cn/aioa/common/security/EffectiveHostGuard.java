package cn.aioa.common.security;

import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/**
 * 注入式的 host 守卫门面：把「配置 + profile」解析成最终开关，再委托纯逻辑
 * {@link UrlHostGuard} 判定。消费者（ToolDispatcher / GiteePlatformConfigService）
 * 只调本类，避免在两处重复写「读配置 + 判断 profile」的胶水。
 */
@Component
public class EffectiveHostGuard {

    private final SecurityProperties securityProperties;
    private final Environment environment;

    public EffectiveHostGuard(SecurityProperties securityProperties, Environment environment) {
        this.securityProperties = securityProperties;
        this.environment = environment;
    }

    /** 按当前配置与 profile 校验 URL（非法/被禁时抛 BizException）。 */
    public void assertAllowed(String url) {
        boolean prod = SecretStrengthValidator.isProdProfile(environment.getActiveProfiles());
        boolean allowPrivate = UrlHostGuard.resolveAllowPrivate(
                securityProperties.getAllowPrivateHosts(), prod);
        UrlHostGuard.assertAllowed(url, allowPrivate);
    }
}
