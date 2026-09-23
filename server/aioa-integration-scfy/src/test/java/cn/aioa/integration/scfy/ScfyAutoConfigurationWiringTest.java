package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.agent.LexicalToolMatcher;
import cn.aioa.integration.scfy.agent.ScfyAgentCatalog;
import cn.aioa.integration.scfy.agent.ScfyAgentService;
import cn.aioa.integration.scfy.agent.ScfyToolDescriptor;
import cn.aioa.integration.scfy.agent.ToolMatcher;
import cn.aioa.integration.scfy.tools.ScfyAgentTools;
import cn.aioa.integration.scfy.tools.ScfyEcologyTools;
import cn.aioa.integration.scfy.tools.ScfyInheritorTools;
import cn.aioa.integration.scfy.tools.ScfyProjectTools;
import cn.aioa.integration.scfy.tools.ScfyShopTools;
import cn.aioa.integration.scfy.tools.ScfyTravelTools;
import cn.aioa.tool.sdk.AioaToolScanner;
import cn.aioa.tool.sdk.LocalToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 装配级验证：把开关打开、走真实的 Spring 装配路径（含两个启动自检），
 * 并验证「换匹配器不用改调用方」这句承诺是真的。
 *
 * <p>之所以要有这一层：单元测试各自 new 出来的对象无法暴露装配缺陷 ——
 * Bean 顺序、条件装配、自检时机（注册表要在扫描之后才能读）这些只有真的起一次容器才会暴露。</p>
 */
class ScfyAutoConfigurationWiringTest {

    /** 开关打开、把 5 个业务工具与 agent 工具都放进容器，跑完整装配。 */
    private AnnotationConfigApplicationContext context(ToolMatcher custom) {
        AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext();
        ctx.getEnvironment().getPropertySources().addFirst(new MapPropertySource("scfy-wiring",
                Map.of("aioa.integration.scfy.enabled", "true")));
        // 注意：这里必须写 lambda 而不是方法引用 —— registerBean 同时有
        // 「(String, Class, Supplier)」与「(String, Class, BeanDefinitionCustomizer...)」两个重载，
        // 方法引用会被判定为两者皆可而编译报错。
        ctx.registerBean("objectMapper", ObjectMapper.class, () -> new ObjectMapper());
        // LocalToolRegistry 在 SDK 里是 @Component，但本测试刻意不起组件扫描（只想要 scfy 这一小块），
        // 于是必须显式登记 —— 否则扫描器与服务层都取不到它。
        ctx.registerBean("localToolRegistry", LocalToolRegistry.class, () -> new LocalToolRegistry());
        ctx.registerBean("aioaToolScanner", AioaToolScanner.class, () -> new AioaToolScanner(
                ctx, ctx.getBean(LocalToolRegistry.class), noopProvider()));
        ctx.register(ScfyAutoConfiguration.class);
        // 工具 Bean：support 传 null（本测试不发起真实调用）
        ctx.registerBean("scfyInheritorTools", ScfyInheritorTools.class, () -> new ScfyInheritorTools(null));
        ctx.registerBean("scfyProjectTools", ScfyProjectTools.class, () -> new ScfyProjectTools(null));
        ctx.registerBean("scfyShopTools", ScfyShopTools.class, () -> new ScfyShopTools(null));
        ctx.registerBean("scfyEcologyTools", ScfyEcologyTools.class, () -> new ScfyEcologyTools(null));
        ctx.registerBean("scfyTravelTools", ScfyTravelTools.class, () -> new ScfyTravelTools(null));
        ctx.registerBean("scfyAgentTools", ScfyAgentTools.class,
                () -> new ScfyAgentTools(ctx.getBean(ScfyAgentService.class)));
        if (custom != null) {
            ctx.registerBean("customMatcher", ToolMatcher.class, () -> custom);
        }
        ctx.refresh();
        // 工具注册发生在「所有单例实例化之后」，必须手动触发一次，等价于真实启动时序
        ctx.getBean(AioaToolScanner.class).afterSingletonsInstantiated();
        return ctx;
    }

    @Test
    @DisplayName("开关打开即完成装配：两个启动自检通过，注册表 55 项且四要素齐备")
    void wiringSucceedsAndSelfChecksPass() {
        try (AnnotationConfigApplicationContext ctx = context(null)) {
            // 一致性自检（工具 ↔ 契约，含参数名）在 Bean 构造期已执行 —— 能起容器即通过

            ScfyAgentService service = ctx.getBean(ScfyAgentService.class);
            ScfyAgentCatalog catalog = service.catalog();
            assertEquals(55, catalog.size());
            assertEquals(54, catalog.registered().size());
            assertTrue(catalog.incompleteness().isEmpty(), "四要素应齐备：" + catalog.incompleteness());

            // 就绪自检（四要素 + 悬空工具 + 空注册表）真实执行一遍
            ScfyAutoConfiguration.ScfyAgentReadinessCheck check =
                    ctx.getBean(ScfyAutoConfiguration.ScfyAgentReadinessCheck.class);
            check.onApplicationEvent(null);

            // 两个 agent 入口工具也在注册表里（它们不映射 scfy 接口，故不在描述符集合中）
            assertTrue(ctx.getBean(LocalToolRegistry.class).get(ScfyAgentCatalog.ASK_TOOL_CODE) != null,
                    "scfy_ask 应已被扫描注册");
            assertTrue(ctx.getBean(LocalToolRegistry.class).get(ScfyAgentCatalog.CATALOG_TOOL_CODE) != null,
                    "scfy_catalog 应已被扫描注册");
        }
    }

    @Test
    @DisplayName("默认给出确定性匹配器")
    void defaultMatcherIsLexical() {
        try (AnnotationConfigApplicationContext ctx = context(null)) {
            assertInstanceOf(LexicalToolMatcher.class, ctx.getBean(ScfyAgentService.class).matcher());
            assertEquals("lexical-bigram-idf", ctx.getBean(ScfyAgentService.class).matcher().name());
        }
    }

    @Test
    @DisplayName("换匹配器只需声明一个 ToolMatcher Bean，服务层与注册表一行都不用改")
    void matcherIsPluggable() {
        ToolMatcher custom = new ToolMatcher() {
            @Override
            public String name() {
                return "test-vector-matcher";
            }

            @Override
            public List<Match> rank(String question, List<ScfyToolDescriptor> candidates, int topN) {
                return List.of();
            }

            @Override
            public double minScore() {
                return 0.9;
            }
        };
        try (AnnotationConfigApplicationContext ctx = context(custom)) {
            ScfyAgentService service = ctx.getBean(ScfyAgentService.class);
            assertEquals("test-vector-matcher", service.matcher().name(),
                    "自定义匹配器应被采纳（没有改服务层任何代码）");
            // 注册表与工具照旧可用，说明替换匹配器不影响其余能力
            assertEquals(55, service.catalog().size());
            Map<String, Object> r = service.ask("成都有哪些非遗工坊");
            assertEquals(Boolean.FALSE, r.get("matched"), "自定义匹配器返回空候选时应如实报告未匹配");
            assertFalse(String.valueOf(r.get("errors")).isBlank());
        }
    }

    private static org.springframework.beans.factory.ObjectProvider<cn.aioa.tool.sdk.ToolDefinitionSink> noopProvider() {
        return new org.springframework.beans.factory.ObjectProvider<>() {
            @Override
            public cn.aioa.tool.sdk.ToolDefinitionSink getObject() {
                return null;
            }

            @Override
            public cn.aioa.tool.sdk.ToolDefinitionSink getObject(Object... args) {
                return null;
            }

            @Override
            public cn.aioa.tool.sdk.ToolDefinitionSink getIfAvailable() {
                return null;
            }

            @Override
            public cn.aioa.tool.sdk.ToolDefinitionSink getIfUnique() {
                return null;
            }

            @Override
            public java.util.Iterator<cn.aioa.tool.sdk.ToolDefinitionSink> iterator() {
                return java.util.Collections.emptyIterator();
            }
        };
    }
}
