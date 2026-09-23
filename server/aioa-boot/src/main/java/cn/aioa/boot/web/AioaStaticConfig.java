package cn.aioa.boot.web;

import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.web.servlet.resource.PathResourceResolver;

import java.io.IOException;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 单端口部署的静态托管：把用户端与管理端交给 aioa-server 自己发，去掉对外部 nginx 的依赖。
 *
 * <pre>
 *   /aioa/h5/**    → H5 单文件目录（h5Dir），SPA 回退到 h5Dir/index.html
 *   /aioa/web/**   → 管理端 dist（webDir），SPA 回退到「最近的 index.html」
 * </pre>
 *
 * <h2>两个必须自己处理的陷阱</h2>
 * <ol>
 *   <li><b>默认解析器会返回「目录」本身</b>：对 {@code /aioa/web/}（路径为空）调用
 *       {@code PathResourceResolver.getResource("")}，返回的是 webDir 这个目录对象，
 *       {@code ResourceHttpRequestHandler} 拿它去写响应会出错。所以这里**不挂默认解析器**：
 *       用 {@code resourceChain(false)} 让解析链里只有本类注册的 {@link SpaResourceResolver}，
 *       由它统一决定「直取文件 / 回退首页 / 明确 404」。</li>
 *   <li><b>子应用各有自己的首页</b>：{@code /aioa/web/subapps/demo-ticket/detail} 必须回退到
 *       {@code subapps/demo-ticket/index.html}，而不是管理端根部的 index.html
 *       （旧 nginx 是用两个 {@code location} 显式写死这条规则的）。
 *       这里改为「沿目录逐级向上找最近的 index.html」，规则通用、不写死应用名。</li>
 * </ol>
 */
@Slf4j
@Configuration
public class AioaStaticConfig implements WebMvcConfigurer {

    private final AioaWebProperties properties;

    /** 同一个静态根只告警一次，避免刷日志。 */
    private final Set<String> warnedRoots = ConcurrentHashMap.newKeySet();

    public AioaStaticConfig(AioaWebProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    void logConfiguredRoots() {
        if (!properties.isEnabled()) {
            log.info("单端口静态托管未启用（aioa.web.enabled=false）：/aioa/h5/** 与 /aioa/web/** 均不可用");
            return;
        }
        checkRoot("用户端 H5", properties.getH5Dir(), properties.getH5Index(), "h5-dir");
        checkRoot("管理端", properties.getWebDir(), properties.getWebIndex(), "web-dir");
    }

    private void checkRoot(String who, String dir, String indexName, String propName) {
        java.io.File root = new java.io.File(dir);
        java.io.File index = new java.io.File(root, indexName);
        if (root.isDirectory() && index.isFile()) {
            log.info("单端口静态托管已启用：{} 根目录 = {}（存在）", who, root.getAbsolutePath());
        } else {
            log.warn("单端口静态托管：{} 根目录不可用（缺目录或缺 {}）= {} —— 该入口将全部返回 404；"
                            + "本地联调用 --aioa.web.{} 覆盖",
                    who, indexName, root.getAbsolutePath(), propName);
        }
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String prefix = AioaPathPrefixSupport.normalizePrefix(properties.getPrefix());
        if (!properties.isEnabled() || prefix.isEmpty()) {
            return;
        }
        // 裸路径（无尾斜杠）与 /** 都注册：PathPattern 的 /** 是否覆盖裸路径随版本而异，
        // 显式两条消除歧义 —— 用户从地址栏手敲 /aioa/web 的场景很常见。
        register(registry, prefix + "/h5", properties.getH5Dir(), properties.getH5Index());
        register(registry, prefix + "/web", properties.getWebDir(), properties.getWebIndex());
    }

    private void register(ResourceHandlerRegistry registry, String basePattern, String rootDir, String indexName) {
        // 三条模式都要注册，缺一不可（真机实测，非推测）：
        //   "/aioa/web"    → 根路径无尾斜杠
        //   "/aioa/web/"   → 根路径带尾斜杠 ← **`/**` 不匹配这一条**（实测：只剩 `/**` 时 /aioa/web/ 直接 404），
        //                    而带尾斜杠恰恰是用户从地址栏敲 /aioa/web 后浏览器跳转到的形态
        //   "/aioa/web/**" → 其下所有子路径
        registry.addResourceHandler(basePattern, basePattern + "/", basePattern + "/**")
                .addResourceLocations(toFileLocation(rootDir))
                .resourceChain(false)
                .addResolver(new SpaResourceResolver(rootDir, indexName, basePattern));
    }

    /** 目录 → Spring 资源地址。统一补尾斜杠，否则 createRelative 会拼错层级。 */
    static String toFileLocation(String dir) {
        String d = dir == null ? "" : dir.trim();
        if (d.isEmpty()) {
            d = ".";
        }
        if (!d.endsWith("/") && !d.endsWith("\\")) {
            d = d + "/";
        }
        return "file:" + d;
    }

    /**
     * 「直取文件 → 白名单校验 → 沿目录向上找 index.html」的解析器。
     *
     * <p>继承 {@link PathResourceResolver} 是为了复用它的 {@code isResourceUnderLocation} 越界检查
     * （防 {@code ../} 路径穿越）；所有直取都走 {@code super}，本类只加「回退」与「白名单」两条规则。
     */
    final class SpaResourceResolver extends PathResourceResolver {

        private final String rootDir;
        private final String indexName;
        /** 处理器的基路径（去掉斜杠），例：{@code aioa/web}。用于把两种到达形态归一化。 */
        private final String basePath;

        SpaResourceResolver(String rootDir, String indexName, String basePattern) {
            this.rootDir = rootDir;
            this.indexName = indexName;
            this.basePath = trimSlashes(basePattern);
        }

        @Override
        protected Resource getResource(String resourcePath, Resource location) throws IOException {
            String path = normalize(resourcePath);

            Resource direct = super.getResource(path, location);
            if (isRealFile(direct)) {
                if (!AioaPathPrefixSupport.isAllowedStaticExtension(path)) {
                    // 白名单外：明确拒绝 + 留痕。返回 null 会走 404，但日志能说明「是策略拒绝，不是文件不存在」，
                    // 避免将来新增一种合法静态类型时只看到一个没有线索的 404。
                    // 覆盖两类：扩展名不在白名单（如 .py），以及**无扩展名的裸文件**（如 id_rsa / makefile）。
                    log.warn("静态托管拒绝非白名单文件：{}（可托管类型见 AioaPathPrefixSupport.ALLOWED_STATIC_EXTENSIONS）", path);
                    return null;
                }
                log.debug("静态命中：'{}' → 直取文件", path);
                return direct;
            }

            if (rootMissing()) {
                return null;
            }

            // 末段含扩展名 ⇒ 是真实资源请求，找不到就必须 404，不能拿 index.html 顶替
            if (!AioaPathPrefixSupport.shouldFallbackToIndex(path)) {
                log.debug("静态未命中：'{}' → 末段是文件，不回退（404）", path);
                return null;
            }

            // 沿目录逐级向上找最近的 index.html：
            //   ""                       → index.html
            //   "org-structure"          → index.html
            //   "subapps/demo-ticket"    → subapps/demo-ticket/index.html
            String dir = path;
            while (true) {
                String candidate = dir.isEmpty() ? indexName : dir + "/" + indexName;
                Resource hit = super.getResource(candidate, location);
                if (isRealFile(hit) && AioaPathPrefixSupport.isAllowedStaticExtension(candidate)) {
                    log.debug("静态命中：'{}' → 回退 {}", path, candidate);
                    return hit;
                }
                if (dir.isEmpty()) {
                    log.debug("静态未命中：'{}' → 无可用 index.html（404）", path);
                    return null;
                }
                int slash = dir.lastIndexOf('/');
                dir = slash < 0 ? "" : dir.substring(0, slash);
            }
        }

        private boolean rootMissing() {
            if (warnedRoots.contains(rootDir)) {
                return true;
            }
            java.io.File f = new java.io.File(rootDir);
            if (f.isDirectory()) {
                return false;
            }
            if (warnedRoots.add(rootDir)) {
                log.warn("静态根目录不存在，该入口返回 404：{}（检查 aioa.web.h5-dir / aioa.web.web-dir 与容器卷挂载）",
                        f.getAbsolutePath());
            }
            return true;
        }

        /**
         * 去掉前导与尾部斜杠，并把**处理器前缀**剥掉，得到相对于静态根的路径（"" 表示根）。
         *
         * <p>★ 为什么必须显式剥前缀（真机 DEBUG 日志实测，不是推测）：同一个 URL 家族会以两种形态到达——
         * <pre>
         *   /aioa/web              （字面模式命中）→ resourcePath = "aioa/web"      （带前缀）
         *   /aioa/web/org-structure（通配模式命中）→ resourcePath = "org-structure" （已无前缀）
         * </pre>
         * 不归一化就会出现「同一类请求走两条不同分支」：带前缀的那种要靠「沿目录向上找 index.html」
         * 兜到静态根才偶然正确 —— 能跑，但正确性来自巧合而不是规则。
         */
        private String normalize(String resourcePath) {
            String p = trimSlashes(resourcePath == null ? "" : resourcePath.trim());
            if (!basePath.isEmpty()) {
                if (p.equals(basePath)) {
                    return "";
                }
                if (p.startsWith(basePath + "/")) {
                    return p.substring(basePath.length() + 1);
                }
            }
            return p;
        }

        private static String trimSlashes(String value) {
            String v = value;
            while (v.startsWith("/")) {
                v = v.substring(1);
            }
            while (v.endsWith("/")) {
                v = v.substring(0, v.length() - 1);
            }
            return v;
        }

        /**
         * 是不是一个可以真正写进响应的文件。
         * 关键是排除**目录**：{@code PathResourceResolver} 对空路径会返回静态根目录本身，
         * 直接交给响应写出会报错。
         */
        private boolean isRealFile(Resource resource) {
            if (resource == null) {
                return false;
            }
            try {
                return resource.isFile() && !resource.getFile().isDirectory();
            } catch (IOException | RuntimeException e) {
                return false;
            }
        }
    }
}
