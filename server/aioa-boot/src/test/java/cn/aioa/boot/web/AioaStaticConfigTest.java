package cn.aioa.boot.web;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.DefaultResourceLoader;
import org.springframework.core.io.Resource;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 静态资源解析规则的单测（单端口部署；见 docs/33）。
 *
 * <p>这里覆盖三类**静默缺陷**：
 * <ol>
 *   <li><b>目录被当成文件</b>：{@code /aioa/web/} 的空路径会解析出静态根目录本身，
 *       交给响应写出会报错，而不是「首页」；</li>
 *   <li><b>子应用回退到别人的首页</b>：{@code /aioa/web/subapps/demo-ticket/detail} 若回退到管理端根部 index.html，
 *       浏览器会加载错的应用、白屏且无 404 —— 旧 nginx 是用两个显式 location 才避开这条的；</li>
 *   <li><b>拼错的资源被 HTML 顶替</b>：{@code app.js} 写错名字却拿到 index.html，浏览器报的是 JS 语法错误
 *       而不是 404，排查成本极高。</li>
 * </ol>
 */
class AioaStaticConfigTest {

    @TempDir
    Path temp;

    private Path root;
    private AioaStaticConfig.SpaResourceResolver resolver;
    private String rootId;

    @BeforeEach
    void setUp() throws IOException {
        root = Files.createDirectories(temp.resolve("webroot"));
        rootId = root.toAbsolutePath().toString();

        // 管理端产物形态：根部 index.html + assets/ + 两个子应用各自有 index.html
        write("index.html", "<html>shell</html>");
        write("assets/app.js", "console.log(1)");
        write("assets/app.css", "body{}");
        write("subapps/demo-ticket/index.html", "<html>ticket</html>");
        write("subapps/demo-ticket/assets/t.js", "console.log('t')");
        write("subapps/demo-dispatch/index.html", "<html>dispatch</html>");
        // 会被白名单拦掉的开发件
        write("serve.py", "print('nope')");
        // 越界目标：放在静态根之外，若穿越没被拦住就会被发出去
        Files.writeString(temp.resolve("outside.txt"), "SECRET", StandardCharsets.UTF_8);

        AioaWebProperties properties = new AioaWebProperties();
        properties.setWebDir(rootId);
        resolver = new AioaStaticConfig(properties).new SpaResourceResolver(rootId, "index.html", "/aioa/web");
    }

    private void write(String relative, String content) throws IOException {
        Path p = root.resolve(relative);
        Files.createDirectories(p.getParent());
        Files.writeString(p, content, StandardCharsets.UTF_8);
    }

    private Resource resolve(String path) throws IOException {
        return resolver.getResource(path, location(root));
    }

    /**
     * 生产环境里 location 由 {@code "file:..."} 字符串经 DefaultResourceLoader 解析，得到的是 {@code UrlResource}。
     * 这里必须**同型构造**，否则测的不是同一件事：
     * {@code PathResourceResolver.isResourceUnderLocation} 先比 class（不同直接 false），
     * 再对非 {@code UrlResource} / {@code ClassPathResource} 走「比较文件名」分支
     * ⇒ 传 {@code FileSystemResource} 会让**所有**路径都解析出 null。
     * 首版就踩了这个坑，现象是 4 个用例集体失败、且失败信息完全不指向真实原因。
     */
    private Resource location(Path dir) {
        return new DefaultResourceLoader()
                .getResource(AioaStaticConfig.toFileLocation(dir.toAbsolutePath().toString()));
    }

    private String contentOf(String path) throws IOException {
        Resource r = resolve(path);
        assertNotNull(r, "期望命中资源：" + path);
        return read(r);
    }

    /**
     * 读资源内容并**显式关闭**输入流。
     * 不关的后果在 Windows 上不是「内存泄漏」这种慢问题，而是 {@code @TempDir} 清理直接抛
     * {@code IOException: Failed to delete temp directory}：断言全过、用例却报 ERROR，
     * 很容易被误读成被测代码有问题。
     */
    private String read(Resource resource) throws IOException {
        try (java.io.InputStream in = resource.getInputStream()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    @Test
    @DisplayName("空路径与根斜杠 → 首页（而不是静态根目录本身）")
    void emptyPathServesIndex() throws IOException {
        for (String p : new String[]{null, "", "/"}) {
            Resource r = resolve(p);
            assertNotNull(r, String.valueOf(p));
            // 关键：必须是文件。若是目录，ResourceHttpRequestHandler 会写出错
            assertEquals(false, r.getFile().isDirectory(), "空路径不能解析出目录：" + p);
            assertEquals("<html>shell</html>", read(r));
        }
    }

    @Test
    @DisplayName("★ 两种到达形态必须归一到同一结果（带前缀的字面模式 / 不带前缀的通配模式）")
    void bothArrivalShapesNormalize() throws IOException {
        // 形态 A：字面模式 /aioa/web 命中 ⇒ resourcePath 带处理器前缀（真机 DEBUG 日志实测）
        // 形态 B：通配模式 /aioa/web/** 命中 ⇒ resourcePath 已无前缀
        assertEquals("<html>shell</html>", contentOf("aioa/web"));
        assertEquals("<html>shell</html>", contentOf("aioa/web/"));
        assertEquals("<html>shell</html>", contentOf(""));
        assertEquals("<html>shell</html>", contentOf("aioa/web/org-structure"));
        assertEquals("<html>shell</html>", contentOf("org-structure"));
        assertEquals("console.log(1)", contentOf("aioa/web/assets/app.js"));
        assertEquals("console.log(1)", contentOf("assets/app.js"));
        // 不以前缀开头时不能被误剥（前缀只按整段匹配）
        assertEquals("<html>ticket</html>", contentOf("subapps/demo-ticket/detail"));
    }

    @Test
    @DisplayName("真实资源直取（js / css）")
    void servesRealFiles() throws IOException {
        assertEquals("console.log(1)", contentOf("assets/app.js"));
        assertEquals("body{}", contentOf("assets/app.css"));
    }

    @Test
    @DisplayName("管理端前端路由（无扩展名）→ 回退根部首页")
    void fallsBackToShellIndex() throws IOException {
        assertEquals("<html>shell</html>", contentOf("org-structure"));
        assertEquals("<html>shell</html>", contentOf("a/b/c"));
    }

    @Test
    @DisplayName("★ 子应用路由 → 回退到「自己的」首页，不是管理端根部首页")
    void fallsBackToOwnSubappIndex() throws IOException {
        assertEquals("<html>ticket</html>", contentOf("subapps/demo-ticket/detail"));
        assertEquals("<html>ticket</html>", contentOf("subapps/demo-ticket/"));
        // 裸路径（无尾斜杠）也必须是它自己的首页
        assertEquals("<html>ticket</html>", contentOf("subapps/demo-ticket"));
        assertEquals("<html>dispatch</html>", contentOf("subapps/demo-dispatch/home"));
        // 子应用自己的静态资源仍直取
        assertEquals("console.log('t')", contentOf("subapps/demo-ticket/assets/t.js"));
    }

    @Test
    @DisplayName("★ 末段含扩展名 → 找不到必须 404，不能拿 index.html 顶替")
    void missingAssetIsNotMaskedByIndex() throws IOException {
        assertNull(resolve("assets/nope.js"));
        assertNull(resolve("app.js"));
        assertNull(resolve("subapps/demo-ticket/assets/missing.css"));
    }

    @Test
    @DisplayName("白名单：静态根下的开发件（.py）与无扩展名裸文件都不被托管")
    void devFilesAreNotPubliclyServed() throws IOException {
        assertNull(resolve("serve.py"));
        // 只按扩展名白名单会漏掉这一类：无扩展名的裸文件（首版就漏了）
        write("id_rsa", "PRIVATE KEY");
        write("Makefile", "all:");
        assertNull(resolve("id_rsa"));
        assertNull(resolve("Makefile"));
    }

    @Test
    @DisplayName("路径穿越必须被拦住（静态根之外的文件不可达）")
    void traversalIsBlocked() throws IOException {
        assertNull(resolve("../outside.txt"));
        assertNull(resolve("assets/../../outside.txt"));
        assertNull(resolve("..%2Foutside.txt"));
    }

    @Test
    @DisplayName("静态根不存在时返回 null（不是异常、不是 500），且不重复告警")
    void missingRootDegradesToNull() throws IOException {
        Path missing = temp.resolve("not-there").toAbsolutePath();
        AioaWebProperties properties = new AioaWebProperties();
        properties.setWebDir(missing.toString());
        AioaStaticConfig.SpaResourceResolver r =
                new AioaStaticConfig(properties).new SpaResourceResolver(missing.toString(), "index.html", "/aioa/web");
        Resource loc = location(missing);

        assertNull(r.getResource("", loc));
        assertNull(r.getResource("org-structure", loc));
        assertNull(r.getResource("assets/a.js", loc));
    }

    @Test
    @DisplayName("资源地址拼接：统一补尾斜杠，空目录退化为当前目录")
    void fileLocationNormalization() {
        assertEquals("file:/app/web/", AioaStaticConfig.toFileLocation("/app/web"));
        assertEquals("file:/app/web/", AioaStaticConfig.toFileLocation("/app/web/"));
        assertEquals("file:./", AioaStaticConfig.toFileLocation("."));
        assertEquals("file:./", AioaStaticConfig.toFileLocation(""));
        assertEquals("file:./", AioaStaticConfig.toFileLocation(null));
    }
}
