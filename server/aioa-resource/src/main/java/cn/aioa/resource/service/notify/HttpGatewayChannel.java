package cn.aioa.resource.service.notify;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.ProxySelector;
import java.net.SocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 非站内通道基类：用 JDK {@link HttpClient} 向 {@code config.url} POST JSON，
 * 携带 {@code Authorization: Bearer <config.token>}，超时 5 秒。
 *
 * <p>设计要点（照搬 GiteeClient 的工程经验）：</p>
 * <ul>
 *   <li><b>显式禁用代理</b>：部署环境可能带 HTTP 代理环境变量，钉死直连避免拿到代理错误页。</li>
 *   <li><b>令牌只走 Authorization 头</b>，绝不进 URL query（防日志/Referer 泄露）。</li>
 *   <li><b>请求体固定</b>：{@code channel, to, title, content, refId} + 可选
 *       {@code signName/from/type/titleTemplate}；2xx 视为成功，否则抛异常由分发器登记 FAILED。</li>
 * </ul>
 *
 * <p>仅 EMAIL/SMS/PUSH 继承本类，各自通过 {@link #code()} 声明通道码；所需配置键的
 * 服务端校验在 {@code NotificationChannelConfigService} 完成（不能只靠前端）。</p>
 */
@Slf4j
public abstract class HttpGatewayChannel implements NotificationChannel {

    /** 请求超时（秒）。 */
    protected static final int TIMEOUT_SECONDS = 5;

    private static final ProxySelector NO_PROXY = new ProxySelector() {
        @Override
        public List<Proxy> select(URI uri) {
            return List.of(Proxy.NO_PROXY);
        }

        @Override
        public void connectFailed(URI uri, SocketAddress sa, IOException ioe) {
            // 不使用代理，无需处理
        }
    };

    protected final ObjectMapper objectMapper = new ObjectMapper();

    private final HttpClient http = HttpClient.newBuilder()
            .proxy(NO_PROXY)
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    @Override
    public void send(DeliveryContext ctx) throws Exception {
        Map<String, Object> cfg = ctx.getConfig() == null ? Map.of() : ctx.getConfig();

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("channel", code());
        body.put("to", ctx.getTo());
        body.put("title", ctx.getTitle());
        body.put("content", ctx.getContent());
        body.put("refId", ctx.getRefId());
        // 可选键：仅当配置中存在才下发（无损携带网关侧可能需要的字段）
        putIfPresent(body, cfg, "signName");
        putIfPresent(body, cfg, "from");
        putIfPresent(body, cfg, "type");
        putIfPresent(body, cfg, "titleTemplate");

        String url = str(cfg.get("url"));
        String token = str(cfg.get("token"));
        if (!StringUtils.hasText(url)) {
            throw new IllegalStateException("通道 " + code() + " 未配置网关地址 url");
        }

        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(TIMEOUT_SECONDS))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + (token == null ? "" : token))
                .POST(HttpRequest.BodyPublishers.ofString(
                        objectMapper.writeValueAsString(body), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        int status = resp.statusCode();
        if (status < 200 || status >= 300) {
            String preview = resp.body() == null ? "" : resp.body();
            if (preview.length() > 200) {
                preview = preview.substring(0, 200);
            }
            throw new IllegalStateException("通道 " + code() + " 网关返回 HTTP " + status + "：" + preview);
        }
    }

    private static void putIfPresent(Map<String, Object> body, Map<String, Object> cfg, String key) {
        if (cfg != null && cfg.containsKey(key)) {
            body.put(key, cfg.get(key));
        }
    }

    private static String str(Object v) {
        return v == null ? null : String.valueOf(v);
    }
}
