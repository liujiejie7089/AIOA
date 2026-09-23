package cn.aioa.boot.web;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 入口前缀纯规则的单测。
 *
 * <p>为什么这些规则要单独测：它们是「接口能不能登录」的唯一判据。
 * {@code stripApiPrefix} 少剥一个字符 → 控制器全部 404；多剥/误剥 → 既有 {@code /api/**} 调用方被改写。
 * 前者会立刻被发现，后者是静默的（现象是「某些老脚本偶发 404」，很难联想到前缀），所以边界必须钉死。</p>
 */
class AioaPathPrefixSupportTest {

    @Test
    @DisplayName("前缀归一化：补前导斜杠、去尾斜杠；空与 '/' 视为不启用")
    void normalizePrefix() {
        assertEquals("", AioaPathPrefixSupport.normalizePrefix(null));
        assertEquals("", AioaPathPrefixSupport.normalizePrefix(""));
        assertEquals("", AioaPathPrefixSupport.normalizePrefix("   "));
        assertEquals("", AioaPathPrefixSupport.normalizePrefix("/"));
        assertEquals("/aioa", AioaPathPrefixSupport.normalizePrefix("/aioa"));
        assertEquals("/aioa", AioaPathPrefixSupport.normalizePrefix("aioa"));
        assertEquals("/aioa", AioaPathPrefixSupport.normalizePrefix("  /aioa/  "));
        assertEquals("/aioa", AioaPathPrefixSupport.normalizePrefix("/aioa///"));
    }

    @Test
    @DisplayName("剥离：/aioa/api/** → /api/**，其余一律不剥")
    void stripApiPrefix() {
        Map<String, String> shouldStrip = new LinkedHashMap<>();
        shouldStrip.put("/aioa/api/v1/auth/login", "/api/v1/auth/login");
        shouldStrip.put("/aioa/api/v1/experts", "/api/v1/experts");
        shouldStrip.put("/aioa/api", "/api");
        shouldStrip.put("/aioa/api/", "/api/");

        shouldStrip.forEach((uri, expected) ->
                assertEquals(expected, AioaPathPrefixSupport.stripApiPrefix(uri, "/aioa"), uri));

        // 不应剥离：既有根路径形态、非 /api 段、以及「前缀只是开头碰巧一样」
        String[] untouched = {
                "/api/v1/auth/login",
                "/api",
                "/aioa/h5/index.html",
                "/aioa/web/assets/a.js",
                "/aioax/api/v1/x",
                "/aioa/apitest",
                "/aioa",
                "/actuator/health",
                null,
                ""
        };
        for (String uri : untouched) {
            assertNull(AioaPathPrefixSupport.stripApiPrefix(uri, "/aioa"), String.valueOf(uri));
        }
    }

    @Test
    @DisplayName("剥离：前缀写法宽松（无前导斜杠 / 带尾斜杠）结果一致；前缀为空则不剥")
    void stripApiPrefixPrefixVariants() {
        assertEquals("/api/v1/x", AioaPathPrefixSupport.stripApiPrefix("/aioa/api/v1/x", "aioa"));
        assertEquals("/api/v1/x", AioaPathPrefixSupport.stripApiPrefix("/aioa/api/v1/x", "/aioa/"));
        assertEquals("/api/v1/x", AioaPathPrefixSupport.stripApiPrefix("/aioa/api/v1/x", "  /aioa  "));
        assertNull(AioaPathPrefixSupport.stripApiPrefix("/aioa/api/v1/x", ""));
        assertNull(AioaPathPrefixSupport.stripApiPrefix("/aioa/api/v1/x", "/"));
    }

    @Test
    @DisplayName("扩展名：取末段最后一个点之后，小写；无扩展名/末段是目录名则为空")
    void extensionOf() {
        assertEquals("js", AioaPathPrefixSupport.extensionOf("assets/index-Bx.js"));
        assertEquals("js", AioaPathPrefixSupport.extensionOf("assets/index-Bx.JS"));
        assertEquals("css", AioaPathPrefixSupport.extensionOf("a.css"));
        assertEquals("", AioaPathPrefixSupport.extensionOf("org-structure"));
        assertEquals("", AioaPathPrefixSupport.extensionOf(""));
        assertEquals("", AioaPathPrefixSupport.extensionOf(null));
        // 末段是目录名（点出现在前一段）⇒ 不算扩展名，否则子应用名里的点会被误判成文件
        assertEquals("", AioaPathPrefixSupport.extensionOf("subapps/demo.v2/detail"));
        // 以点结尾视为无扩展名（不是「扩展名为空字符串」的文件）
        assertEquals("", AioaPathPrefixSupport.extensionOf("weird."));
    }

    @Test
    @DisplayName("静态白名单：只放行「带白名单扩展名」的文件；开发件与无扩展名裸文件一律拦")
    void allowedStaticExtensions() {
        String[] allowed = {"index.html", "assets/a.js", "assets/a.css", "a.svg", "a.woff2",
                "a.png", "a.json", "a.txt", "favicon.ico"};
        for (String p : allowed) {
            assertTrue(AioaPathPrefixSupport.isAllowedStaticExtension(p), p);
        }
        // 静态目录是 permitAll 的：这些一旦落到目录里被托管，等于对外公开。
        // 注意最后一组是**无扩展名的裸文件** —— 只按扩展名白名单会漏掉它们（首版就漏了）。
        String[] denied = {"serve.py", "deploy.sh", "App.java", "a.exe", "a.dll", "conf.env",
                "id_rsa", "Makefile", "VERSION", ".env"};
        for (String p : denied) {
            assertFalse(AioaPathPrefixSupport.isAllowedStaticExtension(p), p);
        }
        // 目录/前端路由（无扩展名）不是「文件」，由 SPA 回退分支处理，不参与本判定
        assertFalse(AioaPathPrefixSupport.isAllowedStaticExtension("subapps/demo-ticket"));
        assertFalse(AioaPathPrefixSupport.isAllowedStaticExtension(""));
    }

    @Test
    @DisplayName("SPA 回退判据：末段无扩展名才允许回退，拼错的 .js 必须 404")
    void shouldFallbackToIndex() {
        String[] fallback = {"", "/", "org-structure", "subapps/demo-ticket", "subapps/demo-ticket/",
                "a/b/c"};
        for (String p : fallback) {
            assertTrue(AioaPathPrefixSupport.shouldFallbackToIndex(p), p);
        }
        String[] noFallback = {"assets/a.js", "nope.js", "a.css", "a.png", "subapps/x/app.js"};
        for (String p : noFallback) {
            assertFalse(AioaPathPrefixSupport.shouldFallbackToIndex(p), p);
        }
    }
}
