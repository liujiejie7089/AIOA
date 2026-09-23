package cn.aioa.boot.web;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 注册入口前缀剥离过滤器（详见 {@link AioaPathPrefixFilter} 的顺序说明）。
 */
@Configuration
@EnableConfigurationProperties(AioaWebProperties.class)
public class AioaWebPrefixConfig {

    @Bean
    public FilterRegistrationBean<AioaPathPrefixFilter> aioaPathPrefixFilter(AioaWebProperties properties) {
        FilterRegistrationBean<AioaPathPrefixFilter> registration =
                new FilterRegistrationBean<>(new AioaPathPrefixFilter(properties.getPrefix()));
        registration.addUrlPatterns("/*");
        // ★ 必须早于 Spring Security 过滤器链（SecurityProperties.DEFAULT_FILTER_ORDER = -100），
        //   否则安全链先看到 /aioa/api/... ⇒ 匹配不到放行名单、JWT 过滤器跳过 ⇒ 登录接口直接 401。
        registration.setOrder(Integer.MIN_VALUE);
        registration.setEnabled(properties.isEnabled());
        registration.setName("aioaPathPrefixFilter");
        return registration;
    }
}
