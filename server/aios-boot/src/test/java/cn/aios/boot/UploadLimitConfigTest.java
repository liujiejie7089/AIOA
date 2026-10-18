package cn.aios.boot;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.PropertySource;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.io.ClassPathResource;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 上传体积上限的「单一数字」契约（docs/44 §3.3-5 的回归防线）。
 *
 * <p><b>为什么需要它</b>：同一个上限曾经同时硬编码在两处 ——
 * {@code spring.servlet.multipart.max-file-size: 50MB}（容器级硬闸）
 * 与 {@code FileController} 里的 {@code 50L * 1024 * 1024}（应用级友好 400）。
 * 两处各写一份数字时，只要有人按业务需要改大容器上限，应用层仍按旧值拒绝，
 * 表现为「文件没超容器上限却被 400 挡回」。</p>
 *
 * <p><b>★ 为什么不能只断言「解析后的值相等」</b>：写成字面量 {@code 50MB} 与
 * 引用 {@code ${aios.file.max-size-mb:50}MB} 解析出来的字符串**恰好相同**，
 * 于是「值是 50MB」这条断言对「有没有两份数字」**没有区分力**（实测：把 yml 改回
 * 字面量后该断言照样通过）。所以本用例以**源文本指纹**为主判据：
 * 两个项的取值必须是**引用同一个键**的占位符表达式；解析值只作辅助校验。</p>
 */
class UploadLimitConfigTest {

    /** 允许的形态：`${aios.file.max-size-mb}MB` 或 `${aios.file.max-size-mb:50}MB`。 */
    private static final Pattern REFERENCE = Pattern.compile("^\\$\\{aios\\.file\\.max-size-mb(:\\d+)?\\}MB$");

    private static String yamlText() throws Exception {
        try (var in = new ClassPathResource("application.yml").getInputStream()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    /** 取出某个键的**原始**取值文本（不做占位符解析），用于指纹断言。 */
    private static String rawValue(String yaml, String key) {
        Matcher m = Pattern.compile("(?m)^\\s*" + Pattern.quote(key) + ":\\s*(\\S+)\\s*$").matcher(yaml);
        assertTrue(m.find(), "application.yml 里找不到 " + key + "（键名被改过？）");
        return m.group(1);
    }

    @Test
    @DisplayName("★上传体积上限只允许一处数字：multipart 两项必须【引用】aios.file.max-size-mb")
    void multipartLimitsMustReferenceTheSingleKey() throws Exception {
        String yaml = yamlText();

        for (String key : new String[]{"max-file-size", "max-request-size"}) {
            String raw = rawValue(yaml, key);
            assertTrue(REFERENCE.matcher(raw).matches(),
                    "spring.servlet.multipart." + key + " 必须是引用 aios.file.max-size-mb 的占位符，"
                            + "否则它又变成第二份数字（只改一处即漂移）；实际为：" + raw);
        }
    }

    @Test
    @DisplayName("辅助：键存在且为正整数，multipart 解析值 = <键>MB（防止占位符指向一个不存在的键而静默用默认值）")
    void resolvedValuesAgreeWithTheKey() throws Exception {
        StandardEnvironment env = new StandardEnvironment();
        List<PropertySource<?>> sources = new YamlPropertySourceLoader()
                .load("application", new ClassPathResource("application.yml"));
        sources.forEach(env.getPropertySources()::addLast);

        Integer mb = env.getProperty("aios.file.max-size-mb", Integer.class);
        assertNotNull(mb, "aios.file.max-size-mb 未定义 —— FileController 会退回内置默认值，与 multipart 脱钩");
        assertTrue(mb > 0, "aios.file.max-size-mb 必须为正整数，实际 " + mb);

        assertEquals(mb + "MB", env.getProperty("spring.servlet.multipart.max-file-size"));
        assertEquals(mb + "MB", env.getProperty("spring.servlet.multipart.max-request-size"));
    }
}
