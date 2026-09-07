package cn.aioa.common.trace;

import org.slf4j.MDC;

import java.util.UUID;

/**
 * traceId 工具：基于 SLF4J MDC，贯穿日志与统一响应体。
 */
public final class TraceId {

    public static final String MDC_KEY = "traceId";
    public static final String HEADER = "X-Trace-Id";

    private TraceId() {
    }

    public static String get() {
        String value = MDC.get(MDC_KEY);
        if (value == null || value.isBlank()) {
            value = newTraceId();
            MDC.put(MDC_KEY, value);
        }
        return value;
    }

    public static String newTraceId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    }

    public static void set(String value) {
        MDC.put(MDC_KEY, value == null ? "" : value);
    }

    public static void clear() {
        MDC.remove(MDC_KEY);
    }
}
