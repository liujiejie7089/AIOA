package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.agent.LexicalToolMatcher;
import cn.aioa.integration.scfy.agent.ScfyAgentCatalog;
import cn.aioa.integration.scfy.agent.ScfyAgentService;
import cn.aioa.integration.scfy.agent.ScfyParamExtractor;
import cn.aioa.integration.scfy.agent.ScfyToolDescriptor;
import cn.aioa.integration.scfy.agent.ToolMatcher;
import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.integration.scfy.tools.ScfyToolSupport;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import cn.aioa.tool.sdk.LocalToolRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * 装配入口 —— 整个 scfy 接入的「插拔开关」。
 *
 * <p>本类是模块的唯一边界：{@code aioa.integration.scfy.enabled=false}（默认）时
 * 不产生任何 Bean，{@link cn.aioa.tool.sdk.AioaToolScanner} 自然也扫不到任何工具，
 * 模型的能力清单里不会出现 scfy。<b>关掉即不存在</b>，不残留半成品状态。</p>
 *
 * <p><b>关于匹配器的可替换性</b>：默认给确定性词法匹配器（离线可测、结果可复现）。
 * 要换成向量检索或大模型选工具，只需在自己的配置里声明一个 {@link ToolMatcher} Bean ——
 * 这里用 {@link ObjectProvider#getIfAvailable(java.util.function.Supplier)} 取用，
 * 有且只有一个自定义实现时就用它，一个都没有就退回默认，出现多个会直接报错而不是随便挑一个。</p>
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

    @Bean
    public ScfyParamExtractor scfyParamExtractor() {
        return new ScfyParamExtractor();
    }

    /**
     * agent 问答服务 —— 匹配 → 抽参 → 调用 → 结构化返回。
     *
     * <p>注册表（{@link ScfyAgentCatalog}）在这里<b>按需装配</b>而不是立即装配：
     * 工具是注解，要等 SDK 扫描器在所有单例实例化完成后才写进
     * {@link LocalToolRegistry}；Bean 创建阶段就读会读到空表。</p>
     */
    @Bean
    public ScfyAgentService scfyAgentService(LocalToolRegistry registry,
                                             ObjectMapper mapper,
                                             ObjectProvider<ToolMatcher> matchers,
                                             ScfyParamExtractor extractor,
                                             ScfyParamValidator validator) {
        ToolMatcher matcher = matchers.getIfAvailable(LexicalToolMatcher::new);
        log.info("scfy agent 匹配器：{}（minScore={}）", matcher.name(), matcher.minScore());
        return new ScfyAgentService(registry, mapper, matcher, extractor, validator);
    }

    /**
     * 启动自检（第一段）：把「工具声明」与「契约」对账 —— 在 Bean 创建阶段即可完成。
     *
     * <p>为什么必须有这一步：{@code @AioaTool} 是编译期注解，无法引用运行时的
     * {@link ScfyCatalog}，于是「接口清单」和「工具参数」天然存在<b>两份文本</b>。
     * 两份文本就会漂移 —— 契约里改了参数名，忘了改注解，表现是「模型看到的 Schema
     * 与校验器认知不一致」，很难在测试里被发现。<b>把一致性交给机器比对，
     * 是让「两处维护」不至于变成两处真相的唯一办法。</b></p>
     *
     * <p>失败策略分两级：
     * <ul>
     *   <li>工具引用了契约里不存在/已废弃的接口、或参数名与契约不一致 ⇒ <b>抛异常阻止启动</b>（代码缺陷）；</li>
     *   <li>契约里有接口还没写工具 ⇒ 只告警（分阶段接入的正常状态，不该阻断启动）。</li>
     * </ul>
     */
    @Bean
    public ScfyCatalogConsistencyChecker scfyCatalogConsistencyChecker(ApplicationContext ctx) {
        return new ScfyCatalogConsistencyChecker(ctx);
    }

    /**
     * 启动自检（第二段）：注册项四要素齐备性。
     *
     * <p>挂在 {@link ApplicationReadyEvent} 上是刻意的：只有到了这一刻，
     * SDK 扫描器才把全部工具写进注册表，注册表才可能被真正装配起来。
     * 早一步检查等于检查一张空表，会得出「全都不齐备」的假结论。</p>
     */
    @Bean
    public ScfyAgentReadinessCheck scfyAgentReadinessCheck(ScfyAgentService service) {
        return new ScfyAgentReadinessCheck(service);
    }

    /** 契约与工具声明的一致性对账器。 */
    public static class ScfyCatalogConsistencyChecker {

        private static final Logger log = LoggerFactory.getLogger(ScfyCatalogConsistencyChecker.class);

        public ScfyCatalogConsistencyChecker(ApplicationContext ctx) {
            Map<String, Set<String>> declared = declaredTools(ctx);
            Set<String> bad = new TreeSet<>();
            Set<String> covered = new LinkedHashSet<>();
            for (Map.Entry<String, Set<String>> e : declared.entrySet()) {
                String id = e.getKey();
                ScfyEndpoint ep = ScfyCatalog.byId(id);
                if (ep == null) {
                    bad.add("工具 scfy_" + id + " 对应的接口不在 ScfyCatalog 中");
                    continue;
                }
                if (!ep.available()) {
                    bad.add("工具 scfy_" + id + " 对应的是已废弃接口：" + ep.note());
                    continue;
                }
                covered.add(id);
                // 注解参数名 ↔ 契约参数名：不一致会让「模型看到的参数」与
                // 「校验器认的参数」变成两份事实，典型后果是模型永远填不对参数
                Set<String> contractParams = new LinkedHashSet<>();
                for (ScfyParam p : ep.params()) {
                    contractParams.add(p.name());
                }
                if (!contractParams.equals(e.getValue())) {
                    bad.add("工具 scfy_" + id + " 的参数与契约不一致：注解=" + e.getValue()
                            + "，契约=" + contractParams);
                }
            }
            if (!bad.isEmpty()) {
                throw new IllegalStateException(
                        "scfy 工具与契约不一致，拒绝启动（避免模型看到会 500 或填不对参数的工具）：\n  - "
                                + String.join("\n  - ", bad));
            }

            Set<String> missing = new LinkedHashSet<>();
            for (ScfyEndpoint ep : ScfyCatalog.available()) {
                if (!covered.contains(ep.id())) {
                    missing.add(ep.id() + "（" + ep.group() + "）");
                }
            }
            if (missing.isEmpty()) {
                log.info("scfy 契约覆盖完整：{} 个可用接口全部有对应工具，且参数名与契约一致", covered.size());
            } else {
                log.warn("scfy 还有 {} 个可用接口未提供工具（分阶段接入中）：{}",
                        missing.size(), String.join(", ", missing));
            }
        }

        /** 反射枚举容器中所有 scfy 工具：接口 id → 注解声明的参数名集合。 */
        private static Map<String, Set<String>> declaredTools(ApplicationContext ctx) {
            Map<String, Set<String>> out = new LinkedHashMap<>();
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
                    if (ann == null || !ann.code().startsWith(TOOL_PREFIX)) {
                        continue;
                    }
                    // agent 层自身的工具不映射 scfy 接口，不在契约内，跳过
                    if (ScfyAgentCatalog.AGENT_LAYER_TOOL_CODES.contains(ann.code())) {
                        continue;
                    }
                    Set<String> params = new LinkedHashSet<>();
                    for (Parameter p : m.getParameters()) {
                        AioaToolParam pa = p.getAnnotation(AioaToolParam.class);
                        if (pa != null) {
                            params.add(pa.name());
                        }
                    }
                    out.put(ann.code().substring(TOOL_PREFIX.length()), params);
                }
            }
            return out;
        }
    }

    /**
     * 就绪自检：每个已注册接口的<b>名称 / 用途 / 参数 / 返回结构</b>必须齐备。
     *
     * <p>为什么要硬失败而不是告警：这四项正是「注册」的含义。缺任何一项，
     * 模型都会出现一类可预期的失败（不知道何时调用 / 不知道填什么参数 / 不知道取哪个字段），
     * 而这类失败在运行时表现为「答案不对」，很难追回到「注册时少写了一个字段」。
     * 宁可启动就失败，也不要把一个残缺的注册表放出去。</p>
     */
    public static class ScfyAgentReadinessCheck implements ApplicationListener<ApplicationReadyEvent> {

        private static final Logger log = LoggerFactory.getLogger(ScfyAgentReadinessCheck.class);

        private final ScfyAgentService service;

        public ScfyAgentReadinessCheck(ScfyAgentService service) {
            this.service = service;
        }

        @Override
        public void onApplicationEvent(ApplicationReadyEvent event) {
            ScfyAgentCatalog catalog = service.catalog();

            if (!catalog.dangling().isEmpty()) {
                throw new IllegalStateException("scfy agent 注册表存在悬空工具，拒绝启动：\n  - "
                        + String.join("\n  - ", catalog.dangling()));
            }

            Map<String, List<String>> incomplete = catalog.incompleteness();
            if (!incomplete.isEmpty()) {
                List<String> lines = new ArrayList<>();
                for (Map.Entry<String, List<String>> e : incomplete.entrySet()) {
                    lines.add(e.getKey() + " 缺少：" + String.join("、", e.getValue()));
                }
                throw new IllegalStateException("scfy agent 注册项四要素不齐备，拒绝启动"
                        + "（名称 / 用途 / 参数 / 返回结构必须齐全）：\n  - " + String.join("\n  - ", lines));
            }

            if (catalog.registered().isEmpty()) {
                throw new IllegalStateException(
                        "scfy agent 注册表里没有任何「已实测返回数据」的接口 —— 注册没有生效，拒绝启动");
            }

            log.info("scfy agent 就绪：注册 {} 个接口，其中可直接语义匹配调用 {} 个；"
                            + "排除 {} 个实测无数据接口（{}）；返回结构采集自 {}",
                    catalog.size(), catalog.registered().size(), catalog.excluded().size(),
                    names(catalog.excluded()), catalog.shapeMeta().get("generatedFrom"));
        }

        private static String names(List<ScfyToolDescriptor> ds) {
            List<String> n = new ArrayList<>();
            for (ScfyToolDescriptor d : ds) {
                n.add(d.endpointId() + "(" + d.observed() + ")");
            }
            return String.join(", ", n);
        }
    }
}
