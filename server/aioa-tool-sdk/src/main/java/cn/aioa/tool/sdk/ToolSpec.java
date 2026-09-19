package cn.aioa.tool.sdk;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

/**
 * 一个已解析的工具声明（注解 → 可执行契约）。
 *
 * <p>{@link #inputSchema()} 由 {@link AioaToolParam} 推导而来，不是手写的 JSON ——
 * 这是「注解即契约」的关键：模型看到的参数表与 Java 方法签名永远一致，
 * 不会出现「文档说有三个参数、代码只读两个」。</p>
 */
public record ToolSpec(String toolCode,
                       String version,
                       String name,
                       String description,
                       String domain,
                       String riskLevel,
                       boolean requiresApproval,
                       boolean idempotencyRequired,
                       String owner,
                       Map<String, Object> inputSchema,
                       Object bean,
                       Method method,
                       List<String> paramNames) {

    /** 服务内工具的伪协议前缀：工具网关据此判定「本地调用」而非出网。 */
    public static final String LOCAL_SCHEME = "local://";

    /** SDK 工具统一挂在这个虚拟系统下（无 base_url，因为不出网）。 */
    public static final String SYSTEM_CODE = "aioa_sdk";

    public String systemCode() {
        return SYSTEM_CODE;
    }

    public String endpoint() {
        return LOCAL_SCHEME + toolCode;
    }

    /** 是否本地（服务内）工具。 */
    public static boolean isLocal(String endpoint) {
        return endpoint != null && endpoint.startsWith(LOCAL_SCHEME);
    }

    public String displayName() {
        return name == null || name.isBlank() ? toolCode : name;
    }
}
