package cn.aios.boot.web;

import cn.aios.common.trace.TraceIdFilter;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;

/**
 * 注册入口前缀剥离过滤器（详见 {@link AiosPathPrefixFilter} 的顺序说明）。
 */
@Configuration
@EnableConfigurationProperties(AiosWebProperties.class)
public class AiosWebPrefixConfig {

    @Bean
    public FilterRegistrationBean<AiosPathPrefixFilter> aiosPathPrefixFilter(AiosWebProperties properties) {
        FilterRegistrationBean<AiosPathPrefixFilter> registration =
                new FilterRegistrationBean<>(new AiosPathPrefixFilter(properties.getPrefix()));
        registration.addUrlPatterns("/*");
        // ★ 必须早于 Spring Security 过滤器链（SecurityProperties.DEFAULT_FILTER_ORDER = -100），
        //   否则安全链先看到 /aios/api/... ⇒ 匹配不到放行名单、JWT 过滤器跳过 ⇒ 登录接口直接 401。
        registration.setOrder(Integer.MIN_VALUE);
        registration.setEnabled(properties.isEnabled());
        registration.setName("aiosPathPrefixFilter");
        return registration;
    }

    /**
     * 注册 TraceId 过滤器：把 traceId 写入 MDC（X-Trace-Id），保证每个请求都有独立的
     * 日志关联键，避免跨请求串台。
     *
     * <p>必须排在 {@link AiosPathPrefixFilter}（{@code Integer.MIN_VALUE}）之前，
     * 即 {@code HIGHEST_PRECEDENCE}，保证所有请求（含被前缀剥离过滤器处理的请求）
     * 在最外层就进入 MDC。顺序早于前缀过滤器不影响其剥离逻辑，二者职责正交。</p>
     */
    @Bean
    public FilterRegistrationBean<TraceIdFilter> traceIdFilter() {
        FilterRegistrationBean<TraceIdFilter> registration =
                new FilterRegistrationBean<>(new TraceIdFilter());
        registration.addUrlPatterns("/*");
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        registration.setName("traceIdFilter");
        return registration;
    }
}
