package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.tools.ScfyEcologyTools;
import cn.aioa.integration.scfy.tools.ScfyInheritorTools;
import cn.aioa.integration.scfy.tools.ScfyProjectTools;
import cn.aioa.integration.scfy.tools.ScfyShopTools;
import cn.aioa.integration.scfy.tools.ScfyTravelTools;
import cn.aioa.tool.sdk.AioaToolScanner;
import cn.aioa.tool.sdk.LocalToolRegistry;
import cn.aioa.tool.sdk.ToolDefinitionSink;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;

import java.util.Collections;
import java.util.Iterator;
import java.util.Map;

/**
 * agent 层测试的公共装配 —— <b>刻意复用生产路径</b>。
 *
 * <p>注册表由 SDK 的 {@link AioaToolScanner} 真实扫描注解而来，而不是测试里手搓一份
 * {@code ToolSpec}：手搓的那份一旦与扫描器口径不同（少个字段、参数名写错），
 * 测试就会在一个平行世界里全绿，而生产是坏的。</p>
 */
final class AgentTestSupport {

    private AgentTestSupport() {
    }

    public static final ObjectMapper MAPPER = new ObjectMapper();

    /** 5 个业务工具类的实例（support 传 null：本层测试只读描述信息，不发生真实调用）。 */
    public static Object[] scfyToolBeans() {
        return new Object[]{
                new ScfyInheritorTools(null),
                new ScfyProjectTools(null),
                new ScfyShopTools(null),
                new ScfyEcologyTools(null),
                new ScfyTravelTools(null)
        };
    }

    /** 用真实扫描路径装配注册表。 */
    public static LocalToolRegistry registryWithScfyTools() {
        return registryWith(scfyToolBeans());
    }

    /** 用真实扫描路径装配注册表，可附加自定义 Bean（用于注入桩实现）。 */
    @SuppressWarnings("unchecked")
    public static LocalToolRegistry registryWith(Object... beans) {
        AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext();
        ctx.getEnvironment().getPropertySources().addFirst(
                new MapPropertySource("scfy-test", Map.of("aioa.integration.scfy.enabled", "true")));
        int i = 0;
        for (Object bean : beans) {
            // 必须走 registerBean（BeanDefinition）而不是 registerSingleton：
            // AioaToolScanner 按 getBeanDefinitionNames() 枚举 Bean，手动单例不在该列表里
            ctx.registerBean("bean" + (i++), (Class<Object>) bean.getClass(), () -> bean);
        }
        ctx.refresh();

        LocalToolRegistry registry = new LocalToolRegistry();
        new AioaToolScanner(ctx, registry, noSink()).afterSingletonsInstantiated();
        ctx.close();
        return registry;
    }

    /** 用真实注册表 + classpath 里的实测返回结构装配 agent 注册表。 */
    public static ScfyAgentCatalog catalog() {
        return ScfyAgentCatalog.load(registryWithScfyTools(), MAPPER);
    }

    private static ObjectProvider<ToolDefinitionSink> noSink() {
        return new ObjectProvider<>() {
            @Override
            public ToolDefinitionSink getObject() {
                return null;
            }

            @Override
            public ToolDefinitionSink getObject(Object... args) {
                return null;
            }

            @Override
            public ToolDefinitionSink getIfAvailable() {
                return null;
            }

            @Override
            public ToolDefinitionSink getIfUnique() {
                return null;
            }

            @Override
            public Iterator<ToolDefinitionSink> iterator() {
                return Collections.emptyIterator();
            }
        };
    }
}
