package cn.aioa.common.web;

import jakarta.servlet.http.HttpServletRequest;

/**
 * 请求级属性契约（跨模块共用，避免 aioa-boot 与 aioa-common 互相依赖）。
 *
 * <p>目前只有一项：<b>客户端原始 URI</b>。</p>
 *
 * <p>背景（单端口部署，见 {@code docs/33-单端口部署改造实施计划.md}）：
 * 对外入口是 {@code /aioa/api/**}，进入安全链之前会被剥成 {@code /api/**} 以便复用既有控制器；
 * 剥离发生在 {@code HttpServletRequestWrapper} 上，于是 {@code getRequestURI()} 看到的是**剥过的**路径。
 * 用户可见的报错文案与排查日志要的是**他真正请求的地址**，所以由剥离方把原值存进本属性。</p>
 */
public final class AioaRequestAttributes {

    /** 客户端原始 URI（未被前缀剥离改写）。 */
    public static final String ORIGINAL_URI = "aioa.original.uri";

    private AioaRequestAttributes() {
    }

    /**
     * 取「用户真正请求的 URI」：优先取剥离前的原值，没有则退回 {@code getRequestURI()}。
     * 用于错误文案与日志，不要用于路由匹配。
     */
    public static String originalUri(HttpServletRequest request) {
        if (request == null) {
            return "";
        }
        Object original = request.getAttribute(ORIGINAL_URI);
        if (original instanceof String s && !s.isEmpty()) {
            return s;
        }
        return request.getRequestURI();
    }
}
