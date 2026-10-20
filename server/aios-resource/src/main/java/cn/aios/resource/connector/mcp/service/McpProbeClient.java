package cn.aios.resource.connector.mcp.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.resource.connector.mcp.config.McpProperties;
import cn.aios.resource.connector.mcp.entity.McpServer;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MCP 网关存活探测客户端（docs/59 §10.3 hub 端点 {@code POST /internal/mcp/probe}）。
 *
 * <p>请求体按 source/transport 组装：BUILTIN → {@code {transport:"builtin",code}}；
 * STDIO → {@code {transport:"stdio",command,args,env}}；STREAMABLE_HTTP →
 * {@code {transport:"streamable_http",url,headers}}。env/headers 在传输前由 {@link SecretCodec}
 * 解密（网关只在内存持有，不落盘）。</p>
 *
 * <p><b>纪律</b>：hub 不可用或网络异常一律返回 {@link ProbeResult#ok=false}，<b>绝不</b>把异常
 * 穿透成 HTTP 500（前端据此展示「连接器本轮不可用」）。</p>
 */
@Slf4j
@Component
public class McpProbeClient {

    private final McpProperties props;
    private final SecretCodec secretCodec;
    private final ObjectMapper objectMapper = new ObjectMapper();
    /**
     * 只走 HTTP/1.1。
     *
     * <p><b>为什么必须显式指定</b>：JDK HttpClient 默认 HTTP/2，对 {@code http://} 会先发
     * h2c 升级请求；uvicorn(httptools) 不支持 HTTP/2，实测表现为
     * {@code WARNING: Unsupported upgrade request} + {@code Invalid HTTP request received}，
     * 于是**请求体被丢掉**，hub 收到的 body 为空并回「未知 transport：None」——
     * 排查时极易误判成「Java 没传 transport」。2026-10-20 实测踩过。</p>
     */
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(8))
            .build();

    public McpProbeClient(McpProperties props, SecretCodec secretCodec) {
        this.props = props;
        this.secretCodec = secretCodec;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ProbeResult {
        private boolean ok;
        private List<Tool> tools = new ArrayList<>();
        private String error;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Tool {
        private String name;
        private String description;
        /**
         * JSON Schema **对象**（不是字符串）。hub 返回的就是对象；声明成 String 会让整个
         * 反序列化抛 MismatchedInputException，整次探测被吞成「网关不可用」。
         */
        private Object inputSchema;
        private boolean readOnly;
    }

    public ProbeResult probe(McpServer server) {
        if (!props.isHubEnabled()) {
            ProbeResult r = new ProbeResult();
            r.setOk(false);
            r.setError("MCP 网关不可用：hub-enabled=false");
            return r;
        }
        try {
            String body = buildRequestBody(server);
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(props.getHubUrl() + "/internal/mcp/probe"))
                    .timeout(Duration.ofMillis(props.getProbeTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            ProbeResult r = objectMapper.readValue(resp.body(), ProbeResult.class);
            if (r.getTools() == null) {
                r.setTools(new ArrayList<>());
            }
            return r;
        } catch (Exception e) {
            // 仅记录异常类型，绝不打印请求体 / 参数
            log.debug("MCP 网关探测异常: {}", e.getClass().getSimpleName());
            ProbeResult r = new ProbeResult();
            r.setOk(false);
            r.setError("MCP 网关不可用：" + e.getClass().getSimpleName());
            return r;
        }
    }

    private String buildRequestBody(McpServer server) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        if (McpServer.SOURCE_BUILTIN.equals(server.getSource())) {
            body.put("transport", "builtin");
            body.put("code", server.getCode());
        } else if (McpServer.TRANSPORT_STDIO.equals(server.getTransport())) {
            body.put("transport", "stdio");
            body.put("command", server.getCommand());
            body.put("args", parseArray(server.getArgsJson()));
            body.put("env", decryptMap(server.getEnvEnc()));
        } else {
            body.put("transport", "streamable_http");
            body.put("url", server.getUrl());
            body.put("headers", decryptMap(server.getHeadersEnc()));
        }
        return objectMapper.writeValueAsString(body);
    }

    private Map<String, String> decryptMap(String enc) {
        if (enc == null || enc.isBlank()) {
            return null;
        }
        try {
            String json = secretCodec.decrypt(enc);
            return objectMapper.readValue(json, Map.class);
        } catch (Exception e) {
            log.debug("MCP 网关凭据解密失败: {}", e.getClass().getSimpleName());
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> parseArray(String s) {
        if (s == null || s.isBlank()) {
            return new ArrayList<>();
        }
        try {
            return objectMapper.readValue(s, List.class);
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }
}
