package cn.aioa.tool.sdk;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import lombok.extern.slf4j.Slf4j;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.context.ApplicationContext;
import org.springframework.stereotype.Component;

/**
 * 注解扫描器：把容器里所有 {@link AioaTool} 方法变成工具声明。
 *
 * <p>时机选在 {@link SmartInitializingSingleton}（全部单例实例化完成、容器刷新末尾）：
 * 此时 Bean 已就绪可直接反射调用，又早于首个请求，
 * 因此「启动日志里就能看到注册了哪些工具」，而不是等第一次被调用才发现注册失败。</p>
 *
 * <p><b>为什么按 BeanDefinition 名字枚举而不是 getBeansWithAnnotation</b>：
 * 注解标在<b>方法</b>上，容器没有「按方法注解查 Bean」的能力，
 * 只能逐 Bean 看方法；跳过 Spring 自身的基础设施 Bean 以免无意义地扫几百个类。</p>
 */
@Slf4j
@Component
public class AioaToolScanner implements SmartInitializingSingleton {

    private static final String[] SKIP_PREFIXES = {
            "org.springframework.", "org.mybatis.", "com.baomidou.", "org.springdoc.", "io.swagger."
    };

    private final ApplicationContext applicationContext;
    private final LocalToolRegistry registry;
    private final ObjectProvider<ToolDefinitionSink> sinkProvider;

    public AioaToolScanner(ApplicationContext applicationContext,
                           LocalToolRegistry registry,
                           ObjectProvider<ToolDefinitionSink> sinkProvider) {
        this.applicationContext = applicationContext;
        this.registry = registry;
        this.sinkProvider = sinkProvider;
    }

    @Override
    public void afterSingletonsInstantiated() {
        List<ToolSpec> specs = new ArrayList<>();
        for (String name : applicationContext.getBeanDefinitionNames()) {
            if (name == null || name.startsWith("scopedTarget.") || isSkipped(name)) {
                continue;
            }
            Object bean;
            try {
                bean = applicationContext.getBean(name);
            } catch (Exception e) {
                // 非单例 / 条件未满足 / 工厂产物 —— 与工具注册无关，跳过即可
                continue;
            }
            if (bean == null) {
                continue;
            }
            specs.addAll(scanBean(bean));
        }

        if (specs.isEmpty()) {
            log.info("未发现 @AioaTool 声明（服务内工具注册表为空）");
            return;
        }
        ToolDefinitionSink sink = sinkProvider.getIfAvailable();
        if (sink == null) {
            // 只放进本地注册表：注解先写、平台后接是正常落地顺序，不该让启动失败。
            for (ToolSpec spec : specs) {
                registry.put(spec);
            }
            log.info("发现 {} 个 @AioaTool 声明，但没有 ToolDefinitionSink 实现，仅注册到进程内表：{}",
                    specs.size(), codes(specs));
            return;
        }
        for (ToolSpec spec : specs) {
            registry.put(spec);
            try {
                sink.register(spec);
            } catch (RuntimeException e) {
                // 单个工具登记失败不应拖垮启动：本地调用仍然可用，落库可稍后重试。
                log.error("工具声明登记失败：code={}", spec.toolCode(), e);
            }
        }
        log.info("已注册 {} 个服务内工具：{}", specs.size(), codes(specs));
    }

    private List<ToolSpec> scanBean(Object bean) {
        List<ToolSpec> out = new ArrayList<>();
        Class<?> target = AopUtils.getTargetClass(bean);
        for (Method m : target.getMethods()) {
            AioaTool ann = m.getAnnotation(AioaTool.class);
            if (ann == null || m.getDeclaringClass() == Object.class) {
                continue;
            }
            if (ann.code() == null || ann.code().isBlank()) {
                log.warn("@AioaTool 缺少 code，已跳过：{}#{}", target.getSimpleName(), m.getName());
                continue;
            }
            Method invocable = AopUtils.selectInvocableMethod(m, bean.getClass());
            out.add(new ToolSpec(
                    ann.code(),
                    ann.version(),
                    ann.name() == null || ann.name().isBlank() ? m.getName() : ann.name(),
                    ann.description(),
                    ann.domain(),
                    ann.riskLevel(),
                    ann.requiresApproval(),
                    ann.idempotencyRequired(),
                    ann.owner(),
                    buildSchema(m),
                    bean,
                    invocable,
                    paramNames(m)));
        }
        return out;
    }

    /** 由 @AioaToolParam 推导 JSON Schema —— 保证模型看到的参数表与方法签名同源。 */
    static Map<String, Object> buildSchema(Method m) {
        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();
        for (Parameter p : m.getParameters()) {
            if (ToolCallContext.class.isAssignableFrom(p.getType())) {
                continue;
            }
            AioaToolParam ann = p.getAnnotation(AioaToolParam.class);
            if (ann == null) {
                continue;
            }
            Map<String, Object> prop = new LinkedHashMap<>();
            prop.put("type", ann.type());
            if (!ann.description().isBlank()) {
                prop.put("description", ann.description());
            }
            properties.put(ann.name(), prop);
            if (ann.required()) {
                required.add(ann.name());
            }
        }
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", properties);
        schema.put("required", required);
        return schema;
    }

    private static List<String> paramNames(Method m) {
        List<String> names = new ArrayList<>();
        for (Parameter p : m.getParameters()) {
            AioaToolParam ann = p.getAnnotation(AioaToolParam.class);
            if (ann != null) {
                names.add(ann.name());
            }
        }
        return names;
    }

    private static boolean isSkipped(String beanName) {
        for (String p : SKIP_PREFIXES) {
            if (beanName.startsWith(p)) {
                return true;
            }
        }
        return false;
    }

    private static List<String> codes(List<ToolSpec> specs) {
        List<String> c = new ArrayList<>();
        for (ToolSpec s : specs) {
            c.add(s.toolCode());
        }
        return c;
    }
}
