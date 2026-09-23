package cn.aioa.boot.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 单端口部署的入口前缀剥离：把 {@code /aioa/api/**} 还原成 {@code /api/**}，
 * 再交给后面的过滤器与 DispatcherServlet。
 *
 * <h2>★ 注册顺序（本类最容易出错的地方）</h2>
 * 必须在 Spring Security 过滤器链（{@code SecurityProperties.DEFAULT_FILTER_ORDER = -100}）**之前**执行。
 * 否则安全链先看到 {@code /aioa/api/v1/auth/login}：
 * <ol>
 *   <li>匹配不到 {@code PUBLIC_ENDPOINTS} 里的 {@code /api/v1/auth/**}；</li>
 *   <li>也过不了 {@code JwtAuthenticationFilter.shouldNotFilter()} 的 {@code startsWith("/api/")} 判定，
 *       于是 JWT 过滤器直接跳过、安全上下文为空；</li>
 *   <li>最终落到 {@code .anyRequest().authenticated()} ⇒ <b>连登录接口都返回 401</b>。</li>
 * </ol>
 * 把剥离放在最前面，既有的安全链与所有控制器**一行都不用改**。
 * 注册见 {@link AioaWebPrefixConfig}（{@code setOrder(Integer.MIN_VALUE)}）。
 *
 * <h2>只改「用于匹配的路径」</h2>
 * 覆写 {@code getRequestURI()} / {@code getServletPath()} 让后续匹配看到剥过的路径；
 * **不覆写** {@code getRequestURL()} —— 保持客户端真实地址，
 * 这样由请求推导出来的回调地址、重定向地址仍是对外可见的 {@code /aioa/api/...} 形态。
 */
public class AioaPathPrefixFilter extends OncePerRequestFilter {

    private final String rawPrefix;

    public AioaPathPrefixFilter(String rawPrefix) {
        this.rawPrefix = rawPrefix;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String originalUri = request.getRequestURI();
        String stripped = AioaPathPrefixSupport.stripApiPrefix(originalUri, rawPrefix);
        if (stripped == null) {
            // 不在「前缀 + /api」下：原样放行（/api/** 与 /actuator/** 等既有形态不受影响）
            chain.doFilter(request, response);
            return;
        }
        // 留存原始 URI，供用户可见的报错文案与排查日志使用
        request.setAttribute(AioaPathPrefixSupport.ATTR_ORIGINAL_URI, originalUri);
        chain.doFilter(new PrefixStrippedRequest(request, stripped), response);
    }

    /** 仅改写用于匹配的路径，不触碰参数、请求头与会话状态。 */
    static final class PrefixStrippedRequest extends HttpServletRequestWrapper {

        private final String uri;

        PrefixStrippedRequest(HttpServletRequest source, String uri) {
            super(source);
            this.uri = uri;
        }

        @Override
        public String getRequestURI() {
            return uri;
        }

        @Override
        public String getServletPath() {
            return uri;
        }

        @Override
        public String getPathInfo() {
            return null;
        }
    }
}
