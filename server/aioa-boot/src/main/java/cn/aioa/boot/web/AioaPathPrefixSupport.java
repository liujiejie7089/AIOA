package cn.aioa.boot.web;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/**
 * 单端口入口前缀的**纯规则**（不依赖 Spring / Servlet / IO），便于单测与脚本核对。
 *
 * <h2>为什么需要它</h2>
 * 生产入口是与别的系统共用的域名（{@code mall.egoaicloud.com}），AIOA 拿不到根路径
 * ⇒ 三个入口统一挂在前缀下：用户端 {@code /aioa/h5/}、管理端 {@code /aioa/web/}、接口 {@code /aioa/api/}。
 *
 * <h2>为什么接口是「双前缀并存」而不是把旧路径搬过去</h2>
 * 仓库里 58 个端到端套件中有 44 个直接打 {@code :8080/api/**}，现场也有按这个形态写死的脚本。
 * 若改用 {@code server.servlet.context-path} 把接口整体搬到 {@code /aioa/api}，
 * 这 44 个套件会在同一秒钟全部失败。因此：
 * <ul>
 *   <li>{@code /aioa/api/**} 在进入安全链**之前**被剥成 {@code /api/**}（见 {@link AioaPathPrefixFilter}）；</li>
 *   <li>{@code /api/**} 原样保留 —— 既有调用方零改动，新入口同时可用。</li>
 * </ul>
 */
public final class AioaPathPrefixSupport {

    /**
     * 存放「客户端原始 URI」的请求属性名。
     * 剥离只改**内部用于匹配的路径**，对外可见的地址不能变
     * ⇒ 用户可见的报错文案取这个属性，而不是被剥过的 {@code getRequestURI()}。
     *
     * <p>常量本体定义在 {@code aioa-common}（{@link cn.aioa.common.web.AioaRequestAttributes}），
     * 因为读它的是 common 里的 {@code GlobalExceptionHandler}；此处只是转发，避免两处各写一份字符串。</p>
     */
    public static final String ATTR_ORIGINAL_URI = cn.aioa.common.web.AioaRequestAttributes.ORIGINAL_URI;

    /**
     * 允许静态托管的文件扩展名（小写，不含点）。
     *
     * <p>为什么要有白名单：静态目录是 permitAll 的，而部署时 H5 目录里可能还躺着
     * {@code serve.py} 之类的开发件 —— 没有白名单就等于把它们一起对外公开了。
     * 白名单是确定性的，且未命中时会打 WARN 日志（避免「某个合法类型被静默 404」查不出来）。
     */
    public static final Set<String> ALLOWED_STATIC_EXTENSIONS = Collections.unmodifiableSet(
            new HashSet<>(Arrays.asList(
                    "html", "htm", "js", "mjs", "css", "json", "map", "txt",
                    "ico", "png", "jpg", "jpeg", "gif", "svg", "webp", "avif",
                    "woff", "woff2", "ttf", "otf", "eot",
                    "mp4", "webm", "pdf"
            )));

    private AioaPathPrefixSupport() {
    }

    /**
     * 归一化前缀：补前导 {@code /}、去掉尾部 {@code /}。
     * 空值 / 纯空白 / {@code "/"} → 空串，表示**不启用**（调用方据此跳过剥离）。
     */
    public static String normalizePrefix(String raw) {
        if (raw == null) {
            return "";
        }
        String p = raw.trim();
        if (p.isEmpty() || "/".equals(p)) {
            return "";
        }
        if (!p.startsWith("/")) {
            p = "/" + p;
        }
        while (p.length() > 1 && p.endsWith("/")) {
            p = p.substring(0, p.length() - 1);
        }
        return p;
    }

    /**
     * 若 {@code uri} 落在「前缀 + /api」之下，返回剥掉前缀后的 uri；否则返回 {@code null}。
     *
     * <pre>
     * prefix=/aioa
     *   /aioa/api/v1/auth/login → /api/v1/auth/login   （剥）
     *   /aioa/api               → /api                 （剥）
     *   /api/v1/auth/login      → null                 （原样保留）
     *   /aioa/h5/index.html     → null                 （不在 /api 下）
     *   /aioax/api/v1/x         → null                 （必须整段匹配，防前缀误吞）
     *   /aioa/apitest           → null                 （同上）
     * </pre>
     */
    public static String stripApiPrefix(String uri, String rawPrefix) {
        String prefix = normalizePrefix(rawPrefix);
        if (prefix.isEmpty() || uri == null || uri.isEmpty()) {
            return null;
        }
        String apiPath = prefix + "/api";
        if (uri.equals(apiPath)) {
            return "/api";
        }
        if (uri.startsWith(apiPath + "/")) {
            return uri.substring(prefix.length());
        }
        return null;
    }

    /**
     * 取扩展名（小写，不含点）；无扩展名返回空串。
     * 以**最后一个路径段的最后一个点**为准：{@code subapps/demo.v2/detail} → 空串（末段是 detail）。
     */
    public static String extensionOf(String path) {
        if (path == null) {
            return "";
        }
        int slash = path.lastIndexOf('/');
        String last = slash >= 0 ? path.substring(slash + 1) : path;
        int dot = last.lastIndexOf('.');
        if (dot < 0 || dot == last.length() - 1) {
            return "";
        }
        return last.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    /**
     * 该路径是否是一个「允许被静态托管的文件路径」。
     *
     * <p>判据只有一个：**扩展名在白名单里**。因此无扩展名的路径一律返回 {@code false}。
     * 这不是笔误 —— 调用它之前已经排除了目录（{@code isRealFile} 只对真实文件成立），
     * 所以剩下的无扩展名路径就是 {@code id_rsa} / {@code serve} / {@code Makefile} 这类**裸文件**，
     * 静态目录是 permitAll 的，放出去等于对外公开。宁可 404 + 一条 WARN，也不默认放行。</p>
     */
    public static boolean isAllowedStaticExtension(String path) {
        String ext = extensionOf(path);
        if (ext.isEmpty()) {
            return false;
        }
        return ALLOWED_STATIC_EXTENSIONS.contains(ext);
    }

    /**
     * 是否应走 SPA 回退（即「末段不是文件」）。
     * 末段含 {@code .} ⇒ 视为对真实资源的请求，找不到就必须 404，不能拿 index.html 顶替
     * （否则一个拼错的 {@code .js} 会返回 HTML，浏览器报的是语法错误而不是 404，极难查）。
     */
    public static boolean shouldFallbackToIndex(String path) {
        if (path == null || path.isEmpty()) {
            return true;
        }
        String trimmed = path;
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        if (trimmed.isEmpty()) {
            return true;
        }
        return extensionOf(trimmed).isEmpty();
    }
}
