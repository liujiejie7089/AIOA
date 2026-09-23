package cn.aioa.boot.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 前缀剥离过滤器的行为单测。
 *
 * <p>这里测的是「下游看到了什么路径」——它就是安全链与控制器能否命中的唯一依据：
 * <ul>
 *   <li>剥过了 ⇒ 既有 {@code /api/**} 控制器与放行名单原样可用；</li>
 *   <li>没剥 ⇒ 控制器 404、且 JWT 过滤器跳过 ⇒ 连登录接口都 401；</li>
 *   <li>剥错了既有根路径（{@code /api/**} 也被改）⇒ 44 个既有套件全部失效。</li>
 * </ul>
 */
class AioaPathPrefixFilterTest {

    /** 记录下游实际收到的请求，便于断言。 */
    private static final class Capture implements FilterChain {
        final AtomicReference<HttpServletRequest> seen = new AtomicReference<>();
        final AtomicInteger calls = new AtomicInteger();

        @Override
        public void doFilter(jakarta.servlet.ServletRequest request, jakarta.servlet.ServletResponse response) {
            seen.set((HttpServletRequest) request);
            calls.incrementAndGet();
        }
    }

    private Capture run(String uri, String prefix) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", uri);
        MockHttpServletResponse response = new MockHttpServletResponse();
        Capture capture = new Capture();
        new AioaPathPrefixFilter(prefix).doFilter(request, response, capture);
        return capture;
    }

    @Test
    @DisplayName("带前缀的接口请求：下游看到剥过的路径，原始 URI 存在请求属性里")
    void stripsApiPrefixBeforeChain() throws Exception {
        Capture captured = run("/aioa/api/v1/auth/login", "/aioa");

        assertEquals(1, captured.calls.get(), "过滤器必须且只能放行一次");
        HttpServletRequest downstream = captured.seen.get();
        assertEquals("/api/v1/auth/login", downstream.getRequestURI());
        assertEquals("/api/v1/auth/login", downstream.getServletPath());
        assertEquals("/aioa/api/v1/auth/login",
                downstream.getAttribute(AioaPathPrefixSupport.ATTR_ORIGINAL_URI));
    }

    @Test
    @DisplayName("裸 /aioa/api 也剥成 /api")
    void stripsBareApiPath() throws Exception {
        Capture captured = run("/aioa/api", "/aioa");
        assertEquals("/api", captured.seen.get().getRequestURI());
    }

    @Test
    @DisplayName("既有 /api/** 必须原样放行（44 个套件与现场脚本的前提），且不留原始 URI 属性")
    void leavesExistingApiPathUntouched() throws Exception {
        Capture captured = run("/api/v1/auth/login", "/aioa");

        HttpServletRequest downstream = captured.seen.get();
        assertEquals("/api/v1/auth/login", downstream.getRequestURI());
        assertNull(downstream.getAttribute(AioaPathPrefixSupport.ATTR_ORIGINAL_URI),
                "未被剥离的请求不该写原值属性，否则错误文案会与真实请求混淆");
    }

    @Test
    @DisplayName("非 /api 路径（静态入口、actuator）一律不碰")
    void leavesNonApiPathsUntouched() throws Exception {
        String[] paths = {"/aioa/h5/index.html", "/aioa/web", "/aioa/web/assets/a.js",
                "/actuator/health", "/v3/api-docs", "/aioa", "/aioax/api/v1/x"};
        for (String p : paths) {
            Capture captured = run(p, "/aioa");
            assertEquals(p, captured.seen.get().getRequestURI(), p);
            assertNull(captured.seen.get().getAttribute(AioaPathPrefixSupport.ATTR_ORIGINAL_URI), p);
        }
    }

    @Test
    @DisplayName("前缀配成空串（不启用）时不剥任何东西")
    void emptyPrefixDisablesStripping() throws Exception {
        Capture captured = run("/aioa/api/v1/x", "");
        assertEquals("/aioa/api/v1/x", captured.seen.get().getRequestURI());
    }
}
