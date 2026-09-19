package cn.aioa.tool.sdk;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;

/**
 * 服务内工具注册表 + 反射调用器。
 *
 * <p>工具在这里被真正执行：{@code local://} 工具不出网，直接调 Java 方法。
 * 与 HTTP 工具共享同一套治理（权限 / 幂等 / 审批 / 日志），差别只在「最后一跳」。</p>
 *
 * <p><b>参数绑定规则</b>（三条，无隐式行为）：</p>
 * <ol>
 *   <li>{@link ToolCallContext} 参数 → 注入调用者身份；</li>
 *   <li>未标注 {@link AioaToolParam} 的 {@code Map} 参数 → 收到整个入参表（透传）；</li>
 *   <li>其余参数必须标注 {@link AioaToolParam}，按名字取值并按声明类型转换。</li>
 * </ol>
 *
 * <p>规则三的「必须」是刻意的：一个没有名字的参数在 function-calling 里无法被模型填写，
 * 与其在运行期静默传 null，不如在启动扫描时就暴露出来。</p>
 */
@Component
public class LocalToolRegistry {

    private final Map<String, ToolSpec> byCode = new ConcurrentHashMap<>();

    public void put(ToolSpec spec) {
        if (spec != null && spec.toolCode() != null) {
            byCode.put(spec.toolCode(), spec);
        }
    }

    public ToolSpec get(String toolCode) {
        return toolCode == null ? null : byCode.get(toolCode);
    }

    public Collection<ToolSpec> all() {
        return List.copyOf(byCode.values());
    }

    public int size() {
        return byCode.size();
    }

    /**
     * 执行一个服务内工具。
     *
     * @return 工具的返回值；{@code Map} 原样返回，其它类型包成 {@code {ok:true,data:...}}
     * @throws IllegalArgumentException 参数缺失 / 类型不可转换（属于调用方错误，会被网关记为业务失败）
     * @throws RuntimeException         工具方法自身抛出的异常（原样上抛，由网关记日志）
     */
    public Object invoke(String toolCode, Map<String, Object> args, ToolCallContext context) {
        ToolSpec spec = byCode.get(toolCode);
        if (spec == null) {
            throw new IllegalArgumentException("未注册的服务内工具：" + toolCode);
        }
        Map<String, Object> in = args == null ? Map.of() : args;
        Method method = spec.method();
        Parameter[] params = method.getParameters();
        Object[] argv = new Object[params.length];
        for (int i = 0; i < params.length; i++) {
            argv[i] = bind(params[i], in, context, spec);
        }
        try {
            method.setAccessible(true);
            Object result = method.invoke(spec.bean(), argv);
            if (result instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = (Map<String, Object>) result;
                return m;
            }
            Map<String, Object> wrapped = new LinkedHashMap<>();
            wrapped.put("ok", true);
            wrapped.put("data", result);
            return wrapped;
        } catch (InvocationTargetException e) {
            Throwable cause = e.getTargetException();
            if (cause instanceof RuntimeException re) {
                throw re;
            }
            throw new IllegalStateException("工具执行失败：" + spec.toolCode() + " - " + cause.getMessage(), cause);
        } catch (IllegalAccessException e) {
            throw new IllegalStateException("工具方法不可访问：" + spec.toolCode(), e);
        }
    }

    private static Object bind(Parameter p, Map<String, Object> args, ToolCallContext ctx, ToolSpec spec) {
        Class<?> type = p.getType();
        if (ToolCallContext.class.isAssignableFrom(type)) {
            return ctx;
        }
        AioaToolParam ann = p.getAnnotation(AioaToolParam.class);
        if (ann == null) {
            if (Map.class.isAssignableFrom(type)) {
                return args;
            }
            throw new IllegalArgumentException("工具 " + spec.toolCode() + " 的参数「" + p.getName()
                    + "」既不是 Map 也没有 @AioaToolParam 标注，模型无从填写该参数");
        }
        Object raw = args.get(ann.name());
        if (raw == null) {
            if (ann.required()) {
                throw new IllegalArgumentException("缺少必填参数：" + ann.name());
            }
            if (type.isPrimitive()) {
                throw new IllegalArgumentException("缺少参数：" + ann.name() + "（原始类型不能为 null）");
            }
            return null;
        }
        return coerce(raw, type, ann.name());
    }

    /** 宽松但显式的类型转换：失败即报错，不静默取默认值。 */
    private static Object coerce(Object raw, Class<?> type, String name) {
        if (type.isInstance(raw) || type == Object.class) {
            return raw;
        }
        String s = String.valueOf(raw);
        try {
            if (type == String.class) {
                return s;
            }
            if (type == Integer.class || type == int.class) {
                return (int) Double.parseDouble(s.trim());
            }
            if (type == Long.class || type == long.class) {
                return (long) Double.parseDouble(s.trim());
            }
            if (type == Double.class || type == double.class) {
                return Double.parseDouble(s.trim());
            }
            if (type == Boolean.class || type == boolean.class) {
                return Boolean.parseBoolean(s.trim());
            }
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("参数「" + name + "」无法转换为 " + type.getSimpleName() + "：" + s);
        }
        throw new IllegalArgumentException("参数「" + name + "」不支持的类型：" + type.getName());
    }
}
