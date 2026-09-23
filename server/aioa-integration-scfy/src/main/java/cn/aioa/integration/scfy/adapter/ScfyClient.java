package cn.aioa.integration.scfy.adapter;

import cn.aioa.integration.scfy.ScfyIntegrationProperties;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.Cipher;
import javax.crypto.spec.SecretKeySpec;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;

import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * scfy 协议适配器 —— 全平台<b>唯一</b>与 scfy 通信的地方。
 *
 * <p><b>为什么必须有这一层，而不能直接用基座的 ToolDispatcher 出网</b>：
 * 基座的出网鉴权只支持 {@code BASIC} / {@code Bearer}（见 ToolDispatcher）。
 * 而 scfy 需要三件基座不支持的事：
 * <ol>
 *   <li>自定义请求头 {@code token: <jwt>}（不是标准的 Authorization: Bearer）；</li>
 *   <li>登录密码需 AES/ECB/PKCS5Padding 加密后再提交；</li>
 *   <li>Token 会在<b>每个响应的响应头里</b>返回新值，调用方必须每次读取并替换 —— 即续期。</li>
 * </ol>
 * 这三件事收在本类内部，上层工具只看到「调一个接口、拿一个结果」。
 * 换 scfy 版本或换环境时，改动不会溢出到这个文件之外。</p>
 *
 * <p><b>安全边界</b>：本类只发 GET。<b>不提供任何写方法</b> —— 当前阶段业务约束是
 * 「只能查询数据，禁止增删改」，把这个约束落成类型系统里「不存在写方法」，
 * 比落成「记得别调」可靠。</p>
 */
public class ScfyClient {

    private static final Logger log = LoggerFactory.getLogger(ScfyClient.class);

    /** 登录密码加密 key（文档附录 B：AES_KEY_UPDATE_USER_INFO）。 */
    private static final String AES_KEY = "8bd32eeed3d0e0ea";
    /** 登录端点（文档 3.1 方式 1）。 */
    private static final String LOGIN_PATH = "/sso/shiro/ajaxLogin";

    private final ScfyIntegrationProperties props;
    private final ObjectMapper mapper;
    private final HttpClient http;

    /** 当前 Token；登录模式下由 login() 写入、由每次响应的 token 头续期。 */
    private volatile String token;

    public ScfyClient(ScfyIntegrationProperties props, ObjectMapper mapper) {
        this.props = props;
        this.mapper = mapper;
        this.http = buildHttpClient(props);
    }

    private static HttpClient buildHttpClient(ScfyIntegrationProperties props) {
        HttpClient.Builder b = HttpClient.newBuilder()
                // 与 common/http/AgentHttpClient 口径一致：固定 HTTP/1.1。
                // scfy 接口无需 HTTP/2，而固定版本能避开明文目标升级 H2C 时的
                // 「upstream connect failed」类问题（本机 7777 就出现过该现象）。
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofMillis(props.getConnectTimeoutMs()))
                .followRedirects(HttpClient.Redirect.NORMAL);
        if (!props.isVerifySsl()) {
            b.sslContext(trustAllContext());
        }
        return b.build();
    }

    /** 仅在 verifySsl=false 时使用：信任所有证书（对应 curl -k）。 */
    private static SSLContext trustAllContext() {
        try {
            TrustManager[] trustAll = new TrustManager[]{new X509TrustManager() {
                @Override
                public void checkClientTrusted(X509Certificate[] chain, String authType) {
                }

                @Override
                public void checkServerTrusted(X509Certificate[] chain, String authType) {
                }

                @Override
                public X509Certificate[] getAcceptedIssuers() {
                    return new X509Certificate[0];
                }
            }};
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, trustAll, new SecureRandom());
            return ctx;
        } catch (Exception e) {
            throw new IllegalStateException("构造信任所有证书的 SSLContext 失败", e);
        }
    }

    // ==================== 只读调用 ====================

    /**
     * 调用一个契约中声明为可用的接口。
     * <p>契约里的参数名即为实际请求参数名 —— 这是 {@code ScfyCatalog} 存在的意义：
     * 文档写 {@code shopId} 的接口，契约里写的是实测确认的 {@code id}。</p>
     */
    public ScfyResponse get(ScfyEndpoint endpoint, Map<String, Object> params) {
        if (!endpoint.available()) {
            // 不静默跳过：废弃接口被调用属于编排层缺陷，必须暴露。
            throw new IllegalArgumentException("接口 " + endpoint.id() + " 已废弃，不应被调用：" + endpoint.note());
        }
        return get(endpoint.fullPath(), params);
    }

    /** 按裸路径调用（登录取 token 等内部用途）。 */
    public ScfyResponse get(String fullPath, Map<String, Object> params) {
        String url = buildUrl(fullPath, params);
        ScfyResponse last = null;
        int attempts = Math.max(1, props.getMaxAttempts());
        for (int i = 1; i <= attempts; i++) {
            last = doGet(url);
            if (shouldRetry(last) && i < attempts) {
                sleep(props.getRetryBackoffMs() << (i - 1));
                continue;
            }
            break;
        }
        return last;
    }

    private boolean shouldRetry(ScfyResponse r) {
        // 只重试「可能是瞬时」的失败：网络层异常（httpStatus=-1）与 5xx。
        // 参数类错误（is not present）与业务错误不重试 —— 重试只是把同一个错误再犯一遍。
        if (r == null) {
            return true;
        }
        if (r.httpStatus() == -1 || r.httpStatus() >= 500) {
            return !r.illegalParam();
        }
        return false;
    }

    private ScfyResponse doGet(String url) {
        long t0 = System.currentTimeMillis();
        try {
            HttpRequest.Builder rb = HttpRequest.newBuilder(URI.create(url))
                    .GET()
                    .timeout(Duration.ofMillis(props.getReadTimeoutMs()))
                    .header("Accept", "application/json")
                    .header("User-Agent", "aioa-scfy-adapter/1.0");
            if (token != null && !token.isBlank()) {
                rb.header("token", token);
            }
            HttpResponse<InputStream> resp = http.send(rb.build(), HttpResponse.BodyHandlers.ofInputStream());

            byte[] body = readLimited(resp.body(), props.getMaxBytes());
            boolean truncated = body.length >= props.getMaxBytes();
            long ms = System.currentTimeMillis() - t0;

            renewToken(resp.headers().firstValue("token").orElse(null));
            return parse(resp.statusCode(), body, ms, truncated);
        } catch (Exception e) {
            long ms = System.currentTimeMillis() - t0;
            log.warn("scfy 调用失败 url={} 耗时={}ms err={}", url, ms, e.toString());
            return new ScfyResponse(-1, null, "网络异常：" + e.getClass().getSimpleName()
                    + (e.getMessage() == null ? "" : " " + e.getMessage()), null, ms, false);
        }
    }

    /** 限长读取，防止单个接口返回超大 body 撑爆后续处理。 */
    private static byte[] readLimited(InputStream in, int max) throws Exception {
        try (InputStream is = in; ByteArrayOutputStream bos = new ByteArrayOutputStream(8192)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) != -1) {
                int room = max - bos.size();
                if (room <= 0) {
                    break;
                }
                bos.write(buf, 0, Math.min(n, room));
            }
            return bos.toByteArray();
        }
    }

    private ScfyResponse parse(int httpStatus, byte[] body, long ms, boolean truncated) {
        JsonNode root;
        try {
            root = mapper.readTree(body);
        } catch (Exception e) {
            String snippet = new String(body, StandardCharsets.UTF_8);
            if (snippet.length() > 200) {
                snippet = snippet.substring(0, 200) + "…";
            }
            return new ScfyResponse(httpStatus, null, "响应非 JSON：" + snippet, null, ms, truncated);
        }
        if (root == null || root.isMissingNode()) {
            return new ScfyResponse(httpStatus, null, "响应为空", null, ms, truncated);
        }
        Integer code = root.hasNonNull("code") ? root.get("code").asInt() : null;
        // 成功用 msg、失败用 message —— 两个键都读，否则出错时信息为 null。
        String message = firstText(root, "msg", "message");
        JsonNode data = root.has("data") ? root.get("data") : null;
        return new ScfyResponse(httpStatus, code, message, data, ms, truncated);
    }

    private static String firstText(JsonNode root, String... keys) {
        for (String k : keys) {
            if (root.hasNonNull(k)) {
                String v = root.get(k).asText();
                if (v != null && !v.isBlank()) {
                    return v;
                }
            }
        }
        return null;
    }

    // ==================== 凭据（需要登录的接口，当前阶段默认关闭）====================

    /**
     * 登录取 Token。
     * <p>当前阶段所有工具都走 /show/* 免登录接口，本方法仅为后续「后台测试服务」预留。
     * 业务约束是只读，因此本类不会新增任何写调用。</p>
     */
    public synchronized boolean login() {
        if (!props.isLoginEnabled()) {
            return false;
        }
        if (props.getUsername() == null || props.getPassword() == null) {
            throw new IllegalStateException(
                    "aioa.integration.scfy.login-enabled=true 但未提供 username/password；"
                            + "不允许静默降级为匿名 —— 那会让需登录接口以 401 伪装成「无数据」");
        }
        String enc = aesEncrypt(props.getPassword());
        String url = props.getBaseUrl() + LOGIN_PATH;
        long t0 = System.currentTimeMillis();
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofMillis(props.getReadTimeoutMs()))
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(
                            "username=" + enc(props.getUsername()) + "&password=" + enc(enc),
                            StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            JsonNode root = mapper.readTree(resp.body());
            Integer code = root.hasNonNull("code") ? root.get("code").asInt() : null;
            if (code != null && code == 0 && root.has("data") && root.get("data").hasNonNull("token")) {
                this.token = root.get("data").get("token").asText();
                log.info("scfy 登录成功 user={} 耗时={}ms", props.getUsername(), System.currentTimeMillis() - t0);
                return true;
            }
            log.warn("scfy 登录失败 code={} msg={}", code, firstText(root, "message", "msg"));
            return false;
        } catch (Exception e) {
            log.warn("scfy 登录异常：{}", e.toString());
            return false;
        }
    }

    /** 响应头带回的新 Token 即续期值；为空则保持原值不动。 */
    private void renewToken(String newToken) {
        if (newToken != null && !newToken.isBlank() && !newToken.equals(this.token)) {
            this.token = newToken;
        }
    }

    public boolean hasToken() {
        return token != null && !token.isBlank();
    }

    /** AES/ECB/PKCS5Padding + Base64（文档 3.1 与附录 B）。 */
    static String aesEncrypt(String plain) {
        try {
            Cipher c = Cipher.getInstance("AES/ECB/PKCS5Padding");
            c.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(AES_KEY.getBytes(StandardCharsets.UTF_8), "AES"));
            return Base64.getEncoder().encodeToString(c.doFinal(plain.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("AES 加密失败", e);
        }
    }

    // ==================== 工具方法 ====================

    private String buildUrl(String fullPath, Map<String, Object> params) {
        StringBuilder sb = new StringBuilder(props.getBaseUrl()).append(fullPath);
        if (params != null && !params.isEmpty()) {
            boolean first = true;
            for (Map.Entry<String, Object> e : params.entrySet()) {
                Object v = e.getValue();
                if (v == null) {
                    continue;      // 缺省参数不拼进 URL：传空串会让后端按空值过滤而非「不筛选」
                }
                String sv = String.valueOf(v);
                if (sv.isBlank()) {
                    continue;
                }
                sb.append(first ? '?' : '&').append(enc(e.getKey())).append('=').append(enc(sv));
                first = false;
            }
        }
        return sb.toString();
    }

    private static String enc(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
    }

    /** 供健康检查/自检使用：只探 baseUrl 是否可达，不解析业务。 */
    public int ping() {
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(props.getBaseUrl() + "/show/ecologicalArea/getAreasNum"))
                    .timeout(Duration.ofMillis(props.getReadTimeoutMs()))
                    .GET()
                    .build();
            return http.send(req, HttpResponse.BodyHandlers.discarding()).statusCode();
        } catch (Exception e) {
            return -1;
        }
    }
}
