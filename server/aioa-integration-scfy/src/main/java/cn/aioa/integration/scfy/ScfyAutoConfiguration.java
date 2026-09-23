package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.tools.ScfyToolSupport;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import cn.aioa.tool.sdk.AioaTool;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.lang.reflect.Method;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.TreeSet;

/**
 * 装配入口 —— 整个 scfy 接入的「插拔开关」。
 *
 * <p>本类是模块的唯一边界：{@code aioa.integration.scfy.enabled=false}（默认）时
 * 不产生任何 Bean，{@link cn.aioa.tool.sdk.AioaToolScanner} 自然也扫不到任何工具，
 * 模型的能力清单里不会出现 scfy。<b>关掉即不存在</b>，不残留半成品状态。</p>
 */
@Configuration
@EnableConfigurationProperties(ScfyIntegrationProperties.class)
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyAutoConfiguration {

    private static final Logger log = LoggerFactory.getLogger(ScfyAutoConfiguration.class);

    /** 工具编码前缀：约定 {@code scfy_<endpointId>}，使「工具 ↔ 契约」可机器比对。 */
    public static final String TOOL_PREFIX = "scfy_";

    @Bean
    public ScfyClient scfyClient(ScfyIntegrationProperties props, ObjectMapper mapper) {
        ScfyClient client = new ScfyClient(props, mapper);
        log.info("scfy 接入已启用：baseUrl={} sslVerify={} login={} 契约可用接口={}（废弃={}）",
                props.getBaseUrl(), props.isVerifySsl(), props.isLoginEnabled(),
                ScfyCatalog.availableCount(), ScfyCatalog.deprecated().size());
        return client;
    }

    @Bean
    public ScfyParamValidator scfyParamValidator() {
        return new ScfyParamValidator();
    }

    @Bean
    public ScfyToolSupport scfyToolSupport(ScfyClient client, ScfyParamValidator validator) {
        return new ScfyToolSupport(client, validator);
    }

    /**
     * 启动自检：把「工具声明」与「契约」对账。
     *
     * <p>为什么必须有这一步：{@code @AioaTool} 是编译期注解，无法引用运行时的
     * {@link ScfyCatalog}，于是「接口清单」和「工具参数」天然存在<b>两份文本</b>。
     * 两份文本就会漂移 —— 契约里改了参数名，忘了改注解，表现是「模型看到的 Schema
     * 与校验器认知不一致」，很难在测试里被发现。<b>把一致性交给机器比对，
     * 是让「两处维护」不至于变成两处真相的唯一办法。</b></p>
     *
     * <p>失败策略分两级：
     * <ul>
     *   <li>工具引用了契约里不存在/已废弃的接口 ⇒ <b>抛异常阻止启动</b>（代码缺陷）；</li>
     *   <li>契约里有接口还没写工具 ⇒ 只告警（分阶段接入的正常状态，不该阻断启动）。</li>
     * </ul>
     */
    @Bean
    public ScfyCatalogConsistencyChecker scfyCatalogConsistencyChecker(ApplicationContext ctx) {
        return new ScfyCatalogConsistencyChecker(ctx);
    }

    /** 契约与工具声明的一致性对账器。 */
    public static class ScfyCatalogConsistencyChecker {

        private static final Logger log = LoggerFactory.getLogger(ScfyCatalogConsistencyChecker.class);

        public ScfyCatalogConsistencyChecker(ApplicationContext ctx) {
            Set<String> declared = declaredEndpointIds(ctx);
            Set<String> bad = new TreeSet<>();
            for (String id : declared) {
                ScfyEndpoint ep = ScfyCatalog.byId(id);
                if (ep == null) {
                    bad.add("工具 scfy_" + id + " 对应的接口不在 ScfyCatalog 中");
                } else if (!ep.available()) {
                    bad.add("工具 scfy_" + id + " 对应的是已废弃接口：" + ep.note());
                }
            }
            if (!bad.isEmpty()) {
                throw new IllegalStateException(
                        "scfy 工具与契约不一致，拒绝启动（避免模型看到会 500 的工具）：\n  - "
                                + String.join("\n  - ", bad));
            }

            Set<String> missing = new LinkedHashSet<>();
            for (ScfyEndpoint ep : ScfyCatalog.available()) {
                if (!declared.contains(ep.id())) {
                    missing.add(ep.id() + "（" + ep.group() + "）");
                }
            }
            if (missing.isEmpty()) {
                log.info("scfy 契约覆盖完整：{} 个可用接口全部有对应工具", declared.size());
            } else {
                log.warn("scfy 还有 {} 个可用接口未提供工具（分阶段接入中）：{}",
                        missing.size(), String.join(", ", missing));
            }
        }

        /** 反射枚举容器中所有带 @AioaTool 且以 scfy_ 开头的编码。 */
        private static Set<String> declaredEndpointIds(ApplicationContext ctx) {
            Set<String> ids = new LinkedHashSet<>();
            for (String beanName : ctx.getBeanDefinitionNames()) {
                Class<?> type;
                try {
                    type = ctx.getType(beanName);
                } catch (Exception e) {
                    continue;
                }
                if (type == null || !type.getName().startsWith("cn.aioa.integration.scfy")) {
                    continue;
                }
                for (Method m : type.getDeclaredMethods()) {
                    AioaTool ann = m.getAnnotation(AioaTool.class);
                    if (ann != null && ann.code().startsWith(TOOL_PREFIX)) {
                        ids.add(ann.code().substring(TOOL_PREFIX.length()));
                    }
                }
            }
            return ids;
        }
    }
}
