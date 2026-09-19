package cn.aioa.bridge.service;

import cn.aioa.bridge.entity.ToolDefinition;
import cn.aioa.bridge.entity.ToolSystem;
import cn.aioa.common.exception.BizException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工具调用执行器：按定义发起真实 HTTP 调用。
 *
 * <p>这是 M1 占位里那句「tool invoke 将在 M2 实现」的落点 —— 之前只有实体和 Mapper，
 * 没有任何一处代码把 {@code endpoint} / {@code http_method} / {@code param_mapping}
 * 用起来，工具调用实际从未出过网。</p>
 *
 * <p><b>参数映射口径</b>（{@code tool_definition.param_mapping}）：</p>
 * <pre>
 * {
 *   "headers": { "&lt;目标头&gt;":   "&lt;入参名&gt;" },
 *   "query":   { "&lt;目标参数&gt;": "&lt;入参名&gt;" },
 *   "body":    { "&lt;目标字段&gt;": "&lt;入参名&gt;" }
 * }
 * </pre>
 * <p>未配置 {@code param_mapping} 时的缺省行为：GET/HEAD 把入参全部拼进 query，
 * 其它方法把入参整体作为 JSON 请求体 —— 覆盖绝大多数「透传型」工具。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolDispatcher {

    private static final long DEFAULT_TIMEOUT_MS = 5_000L;
    private static final long DEFAULT_MAX_BYTES = 1_048_576L;

    private final ObjectMapper objectMapper;

    /**
     * 请求后端的产物。
     *
     * @param httpStatus HTTP 状态码；网络层失败时为 null
     * @param body       响应体（已按 max_bytes 截断）
     * @param durationMs 耗时
     * @param error      错误摘要；null = 网络层成功（HTTP 4xx/5xx 不算网络层失败，要看 httpStatus）
     */
    public record Outcome(Integer httpStatus, String body, long durationMs, String error) {

        public boolean ok() {
            return error == null && httpStatus != null && httpStatus < 400;
        }
    }

    public Outcome call(ToolDefinition def, ToolSystem system, Map<String, Object> args) {
        Map<String, Object> in = args == null ? Map.of() : args;
        String method = def.getHttpMethod() == null || def.getHttpMethod().isBlank()
                ? "GET" : def.getHttpMethod().trim().toUpperCase();
        String url = buildUrl(def, system);
        long timeout = def.getTimeoutMs() != null ? def.getTimeoutMs()
                : (system != null && system.getTimeoutMs() != null ? system.getTimeoutMs() : DEFAULT_TIMEOUT_MS);
        long maxBytes = def.getMaxBytes() != null && def.getMaxBytes() > 0 ? def.getMaxBytes() : DEFAULT_MAX_BYTES;

        Map<String, Object> mapping = def.getParamMapping();
        Map<String, String> headerMap = subMapping(mapping, "headers");
        Map<String, String> queryMap = subMapping(mapping, "query");
        Map<String, String> bodyMap = subMapping(mapping, "body");

        StringBuilder query = new StringBuilder();
        if (!queryMap.isEmpty()) {
            appendQuery(query, project(in, queryMap));
        } else if (mapping == null && ("GET".equals(method) || "HEAD".equals(method))) {
            appendQuery(query, in);
        }
        if (query.length() > 0) {
            url = url + (url.contains("?") ? "&" : "?") + query;
        }

        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofMillis(timeout))
                .header("Accept", "application/json");
        // 业务系统的静态鉴权（auth_type/auth_ref），工具级配置优先
        String authType = def.getAuthType() != null ? def.getAuthType()
                : (system == null ? null : system.getAuthType());
        String authRef = def.getAuthRef() != null ? def.getAuthRef()
                : (system == null ? null : system.getAuthRef());
        if (authRef != null && !authRef.isBlank()) {
            if (authType != null && authType.toUpperCase().contains("BASIC")) {
                builder.header("Authorization", "Basic " + authRef);
            } else {
                builder.header("Authorization", "Bearer " + authRef);
            }
        }
        for (Map.Entry<String, String> e : headerMap.entrySet()) {
            Object v = in.get(e.getValue());
            if (v != null) {
                builder.header(e.getKey(), String.valueOf(v));
            }
        }

        String body = null;
        if (!"GET".equals(method) && !"HEAD".equals(method)) {
            Map<String, Object> payload = bodyMap.isEmpty() ? in : project(in, bodyMap);
            try {
                body = objectMapper.writeValueAsString(payload);
            } catch (Exception e) {
                throw BizException.badRequest("工具入参无法序列化为 JSON：" + e.getMessage());
            }
            builder.header("Content-Type", "application/json");
        }
        builder.method(method, body == null
                ? HttpRequest.BodyPublishers.noBody()
                : HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));

        long start = System.currentTimeMillis();
        try {
            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofMillis(Math.min(timeout, DEFAULT_TIMEOUT_MS)))
                    .followRedirects(HttpClient.Redirect.NEVER)
                    .build();
            HttpResponse<byte[]> resp = client.send(builder.build(),
                    HttpResponse.BodyHandlers.ofByteArray());
            long cost = System.currentTimeMillis() - start;
            byte[] raw = resp.body() == null ? new byte[0] : resp.body();
            boolean truncated = raw.length > maxBytes;
            if (truncated) {
                byte[] cut = new byte[(int) maxBytes];
                System.arraycopy(raw, 0, cut, 0, (int) maxBytes);
                raw = cut;
            }
            String text = new String(raw, StandardCharsets.UTF_8);
            if (truncated) {
                text = text + "...[truncated at " + maxBytes + " bytes]";
            }
            return new Outcome(resp.statusCode(), text, cost, null);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new Outcome(null, null, System.currentTimeMillis() - start, "调用被中断");
        } catch (Exception e) {
            log.warn("工具调用失败：tool={}, url={}, err={}", def.getToolCode(), url, e.toString());
            return new Outcome(null, null, System.currentTimeMillis() - start,
                    "调用失败：" + e.getClass().getSimpleName() + (e.getMessage() == null ? "" : " - " + e.getMessage()));
        }
    }

    private static String buildUrl(ToolDefinition def, ToolSystem system) {
        String endpoint = def.getEndpoint();
        if (endpoint == null || endpoint.isBlank()) {
            throw BizException.badRequest("工具 " + def.getToolCode() + " 未配置 endpoint");
        }
        if (endpoint.startsWith("http://") || endpoint.startsWith("https://")) {
            return endpoint;
        }
        if (system == null || system.getBaseUrl() == null || system.getBaseUrl().isBlank()) {
            throw BizException.badRequest("工具 " + def.getToolCode() + " 绑定的业务系统（"
                    + def.getSystemCode() + "）未注册或未配置 base_url，且 endpoint 不是绝对地址");
        }
        String base = system.getBaseUrl().replaceAll("/+$", "");
        return base + (endpoint.startsWith("/") ? endpoint : "/" + endpoint);
    }

    /** 从 param_mapping 里取子映射（值必须是字符串；非字符串值视为非法，直接忽略该键）。 */
    private static Map<String, String> subMapping(Map<String, Object> mapping, String key) {
        Map<String, String> out = new LinkedHashMap<>();
        if (mapping == null) {
            return out;
        }
        Object node = mapping.get(key);
        if (!(node instanceof Map<?, ?> m)) {
            return out;
        }
        for (Map.Entry<?, ?> e : m.entrySet()) {
            if (e.getKey() != null && e.getValue() instanceof String s && !s.isBlank()) {
                out.put(String.valueOf(e.getKey()), s);
            }
        }
        return out;
    }

    /** 按映射把入参投影成目标结构：目标字段名 → 入参取值。 */
    private static Map<String, Object> project(Map<String, Object> in, Map<String, String> mapping) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<String, String> e : mapping.entrySet()) {
            Object v = in.get(e.getValue());
            if (v != null) {
                out.put(e.getKey(), v);
            }
        }
        return out;
    }

    private static void appendQuery(StringBuilder sb, Map<String, Object> params) {
        for (Map.Entry<String, Object> e : params.entrySet()) {
            if (e.getValue() == null) {
                continue;
            }
            if (sb.length() > 0) {
                sb.append('&');
            }
            sb.append(URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8))
                    .append('=')
                    .append(URLEncoder.encode(String.valueOf(e.getValue()), StandardCharsets.UTF_8));
        }
    }

    /**
     * 极简 JSON 路径取值：支持 {@code a.b.c} 与 {@code a[0].b}。
     *
     * <p>刻意不引第三方 JMESPath 实现：本平台 99% 的工具只需要「取某个字段」，
     * 引入一个完整表达式引擎会成倍放大依赖面。解析失败或路径不存在时**原样返回响应体**，
     * 保证「配置写错」不会变成「拿不到数据」。</p>
     */
    public String extract(String body, String path) {
        if (path == null || path.isBlank() || body == null || body.isBlank()) {
            return body;
        }
        try {
            JsonNode node = objectMapper.readTree(body);
            for (String seg : path.split("\\.")) {
                if (seg.isBlank()) {
                    continue;
                }
                String name = seg;
                while (name.contains("[")) {
                    int lb = name.indexOf('[');
                    int rb = name.indexOf(']', lb);
                    if (rb < 0) {
                        return body;
                    }
                    if (!node.isArray()) {
                        return body;
                    }
                    node = node.path(Integer.parseInt(name.substring(lb + 1, rb).trim()));
                    name = name.substring(rb + 1);
                }
                if (!name.isBlank()) {
                    node = node.path(name);
                }
                if (node.isMissingNode()) {
                    return body;
                }
            }
            if (node.isValueNode()) {
                return node.asText();
            }
            return objectMapper.writeValueAsString(node);
        } catch (Exception e) {
            log.debug("response_jmespath 解析失败，回落完整响应体：path={}, err={}", path, e.toString());
            return body;
        }
    }

    /** 响应体摘要（sha256 前 32 位），用于对账与幂等比对。 */
    public static String digest(String body) {
        if (body == null) {
            return null;
        }
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] h = md.digest(body.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 16; i++) {
                sb.append(String.format("%02x", h[i]));
            }
            return sb.toString();
        } catch (Exception e) {
            return null;
        }
    }

    /** 调用的可读摘要（写日志用，避免落敏感值：只记键名）。 */
    public static List<String> argKeys(Map<String, Object> args) {
        List<String> keys = new ArrayList<>();
        if (args != null) {
            keys.addAll(args.keySet());
        }
        return keys;
    }
}
