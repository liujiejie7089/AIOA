package cn.aios.resource.connector.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.config.ConnectorProperties;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.entity.ConnectorOauthState;
import cn.aios.resource.connector.mapper.ConnectorConnectionMapper;
import cn.aios.resource.connector.mapper.ConnectorOauthStateMapper;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 企业微信 OAuth2 授权（docs/58 §3.3）。两步：start（生成一次性 state + 返回授权页 URL）
 * 与 callback（校验 state → 换 token → 取 userid → 写连接）。
 *
 * <p><b>开放重定向防护</b>：start 校验 {@code returnPath}（以 {@code /} 开头、不含 {@code //}、
 * 不含反斜杠），并把 {@code Origin} 主机名与请求 {@code Host} 主机名比对，不一致直接 400。</p>
 *
 * <p><b>CSRF 防护</b>：state 一次性（used_at 写后即废）、10 分钟过期；callback 校验失败时
 * <b>绝不</b>写任何 connection，仅 302 回失败页。</p>
 *
 * <p><b>日志纪律</b>：access_token 等敏感信息<b>绝不</b>进入日志。</p>
 */
@Slf4j
@Service
public class WeComOAuthService {

    private static final String WECHAT_WORK = "wechat_work";
    private static final String AUTH_BASE = "https://open.work.weixin.qq.com/wwopen/sso/qrConnect";
    /** 移动端网页授权（企微客户端内）：scope 固定 snsapi_privateinfo（docs/58 §3.3）。 */
    private static final String WEB_AUTH_BASE = "https://open.weixin.qq.com/connect/oauth2/authorize";
    private static final String GETTOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken";
    private static final String GETUSERINFO_URL = "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo";
    /** snsapi_privateinfo 授权后 user_ticket 换详细身份（POST），含 biz_mail。 */
    private static final String GETUSERDETAIL_URL = "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserdetail";
    private static final Duration STATE_TTL = Duration.ofMinutes(10);
    private static final Duration HTTP_TIMEOUT = Duration.ofSeconds(8);

    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(HTTP_TIMEOUT)
            .build();

    private final ConnectorOauthStateMapper stateMapper;
    private final ConnectorConnectionMapper connectionMapper;
    private final ConnectorCatalogService catalogService;
    private final SecretCodec secretCodec;
    private final ConnectorProperties props;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public WeComOAuthService(ConnectorOauthStateMapper stateMapper,
                             ConnectorConnectionMapper connectionMapper,
                             ConnectorCatalogService catalogService,
                             SecretCodec secretCodec,
                             ConnectorProperties props) {
        this.stateMapper = stateMapper;
        this.connectionMapper = connectionMapper;
        this.catalogService = catalogService;
        this.secretCodec = secretCodec;
        this.props = props;
    }

    /** 发起授权：校验 returnPath / origin，生成 state，返回授权页 URL。
     *
     * <p><b>UA 分流</b>：企微/微信客户端内（User-Agent 含 MicroMessenger 或 wxwork）走移动端
     * 网页授权 {@code oauth2/authorize}，scope 固定 {@code snsapi_privateinfo}（授权后可拿
     * user_ticket → getuserdetail → biz_mail）；普通浏览器保留 PC 扫码（qrConnect，仅 userid）。</p>
     */
    public ConnectorCatalogService.ConnectorStart start(AuthUser user, String code, String returnPath,
                                                       String origin, String host, String userAgent) {
        ConnectorCatalogService.ConfigReadyResult ready = catalogService.configReady(code, user.getTenantId());
        if (!ready.ready()) {
            throw BizException.badRequest(ready.hint() == null ? "连接器未就绪" : ready.hint());
        }

        if (returnPath == null || !returnPath.startsWith("/") || returnPath.contains("//")
                || returnPath.contains("\\")) {
            throw BizException.badRequest("returnPath 非法（须为同站相对路径）");
        }
        if (origin == null || origin.isBlank()) {
            throw BizException.badRequest("缺少 Origin，拒绝授权跳转");
        }
        String originHost = hostOf(origin);
        String reqHost = hostOfHeader(host);
        if (originHost == null || reqHost == null || !originHost.equalsIgnoreCase(reqHost)) {
            throw BizException.badRequest("Origin 与 Host 主机名不一致，拒绝开放重定向");
        }

        String state = UUID.randomUUID().toString().replace("-", "");
        ConnectorOauthState st = new ConnectorOauthState();
        st.setState(state);
        st.setTenantId(user.getTenantId());
        st.setUserId(user.getUserId());
        st.setConnectorCode(code);
        st.setReturnPath(returnPath);
        st.setOrigin(origin);
        st.setCreatedAt(LocalDateTime.now());
        stateMapper.insert(st);

        ConnectorCatalogService.WeComCredentials creds = catalogService.resolveWeCom(user.getTenantId());
        if (creds == null) {
            throw BizException.badRequest("缺少企业微信应用配置：corpId / agentId / corpSecret");
        }

        String callbackBase = (props.getPublicBase() == null || props.getPublicBase().isBlank())
                ? origin : props.getPublicBase();
        String callbackUrl = callbackBase.replaceAll("/+$", "") + "/api/v1/connectors/" + code + "/callback";

        String authUrl;
        if (isWecomClient(userAgent)) {
            // 移动端网页授权：scope 固定 snsapi_privateinfo（不用 snsapi_base —— 拿不到 user_ticket/biz_mail）
            authUrl = WEB_AUTH_BASE
                    + "?appid=" + urlEncode(creds.corpId())
                    + "&redirect_uri=" + urlEncode(callbackUrl)
                    + "&response_type=code"
                    + "&scope=snsapi_privateinfo"
                    + "&state=" + urlEncode(state)
                    + "&agentid=" + urlEncode(creds.agentId())
                    + "#wechat_redirect";
        } else {
            // PC 扫码（原分支，保持不变）
            authUrl = AUTH_BASE
                    + "?appid=" + urlEncode(creds.corpId())
                    + "&agentid=" + urlEncode(creds.agentId())
                    + "&redirect_uri=" + urlEncode(callbackUrl)
                    + "&state=" + urlEncode(state);
        }

        return new ConnectorCatalogService.ConnectorStart("OAUTH2", authUrl, java.util.List.of());
    }

    /** OAuth 回调：校验 state → 换 token → 取 userid → 写连接；返回 302 Location。 */
    public String callback(String code, String state) {
        ConnectorOauthState st = stateMapper.selectById(state);
        if (st == null) {
            // 伪造 state：无可信 origin，安全起见只回首页（不写 connection）
            return "/?connector=" + urlEncode(WECHAT_WORK) + "&result=fail&message=" + urlEncode("state 无效");
        }
        if (st.getUsedAt() != null) {
            return buildLocation(st, "fail", "state 已使用");
        }
        if (st.getCreatedAt() == null
                || Duration.between(st.getCreatedAt(), LocalDateTime.now()).compareTo(STATE_TTL) > 0) {
            return buildLocation(st, "fail", "state 已过期");
        }
        // 一次性：立即作废
        st.setUsedAt(LocalDateTime.now());
        stateMapper.updateById(st);

        ConnectorCatalogService.WeComCredentials creds = catalogService.resolveWeCom(st.getTenantId());
        if (creds == null) {
            return buildLocation(st, "fail", "企业微信应用配置缺失");
        }
        String accessToken;
        try {
            accessToken = getToken(st.getTenantId()).accessToken();
        } catch (Exception e) {
            return buildLocation(st, "fail", "获取 access_token 失败：" + e.getMessage());
        }
        String infoResp = httpGet(GETUSERINFO_URL + "?access_token=" + urlEncode(accessToken)
                + "&code=" + urlEncode(code));
        JsonNode info = parse(infoResp);
        String userid = info == null ? null : info.path("userid").asText(null);
        if (userid == null || userid.isBlank()) {
            return buildLocation(st, "fail", "未获取到企业微信 userid：" + (info == null ? "无响应" : info.path("errmsg").asText("")));
        }

        // snsapi_privateinfo 授权 ⇒ getuserinfo 额外返回 user_ticket（1800s 有效，只在本请求内用一次换详细身份）
        String userTicket = info.path("user_ticket").asText(null);
        Map<String, Object> credential = new java.util.LinkedHashMap<>();
        credential.put("userid", userid);
        if (userTicket != null && !userTicket.isBlank()) {
            JsonNode detail = httpPostJson(GETUSERDETAIL_URL + "?access_token=" + urlEncode(accessToken),
                    jsonOf("user_ticket", userTicket));
            if (detail != null && detail.path("errcode").asInt(0) == 0) {
                String bizMail = detail.path("biz_mail").asText(null);
                if (bizMail != null && !bizMail.isBlank()) {
                    credential.put("biz_mail", bizMail);
                }
                String name = detail.path("name").asText(null);
                if (name != null && !name.isBlank()) {
                    credential.put("name", name);
                }
            } else {
                // getuserdetail 失败不阻断连接：.userid 已到手，biz_mail 缺失时 get_my_profile 如实缺省
                log.info("getuserdetail 未成功（不阻断连接）: {}",
                        detail == null ? "无响应" : detail.path("errmsg").asText(""));
            }
        }

        upsertConnection(st.getTenantId(), st.getUserId(), st.getConnectorCode(), credential);
        return buildLocation(st, "ok", null);
    }

    private void upsertConnection(Long tenantId, Long userId, String code, Map<String, Object> credential) {
        ConnectorConnection c = connectionMapper.selectOne(new LambdaQueryWrapper<ConnectorConnection>()
                .eq(ConnectorConnection::getTenantId, tenantId)
                .eq(ConnectorConnection::getUserId, userId)
                .eq(ConnectorConnection::getConnectorCode, code));
        boolean insert = c == null;
        if (insert) {
            c = new ConnectorConnection();
            c.setTenantId(tenantId);
            c.setUserId(userId);
            c.setConnectorCode(code);
        }
        LocalDateTime now = LocalDateTime.now();
        c.setStatus(ConnectorConnection.STATUS_CONNECTED);
        String userid = String.valueOf(credential.getOrDefault("userid", ""));
        Object bizMail = credential.get("biz_mail");
        c.setAccountLabel(bizMail != null && !String.valueOf(bizMail).isBlank()
                ? String.valueOf(bizMail) : userid);
        c.setCredentialJson(secretCodec.encrypt(toJson(credential)));
        c.setConnectedAt(now);
        c.setLastCheckedAt(now);
        c.setLastError(null);
        c.setDisconnectedAt(null);
        if (insert) {
            connectionMapper.insert(c);
        } else {
            connectionMapper.updateById(c);
        }
    }

    private String buildLocation(ConnectorOauthState st, String result, String message) {
        String origin = st.getOrigin() == null ? "" : st.getOrigin();
        String returnPath = st.getReturnPath() == null ? "/" : st.getReturnPath();
        StringBuilder sb = new StringBuilder(origin).append(returnPath);
        sb.append(sb.indexOf("?") >= 0 ? "&" : "?");
        sb.append("connector=").append(urlEncode(st.getConnectorCode())).append("&result=").append(result);
        if (message != null) {
            sb.append("&message=").append(urlEncode(message));
        }
        return sb.toString();
    }

    private String httpGet(String url) {
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(HTTP_TIMEOUT)
                    .GET()
                    .build();
            HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
            return resp.body();
        } catch (Exception e) {
            log.debug("企业微信 HTTP 请求异常: {}", e.getClass().getSimpleName());
            return null;
        }
    }

    /** POST JSON（getuserdetail 用），body 为 JSON 字符串。 */
    private JsonNode httpPostJson(String url, String jsonBody) {
        try {
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(HTTP_TIMEOUT)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
            return parse(resp.body());
        } catch (Exception e) {
            log.debug("企业微信 POST 异常: {}", e.getClass().getSimpleName());
            return null;
        }
    }

    /** 企微/微信客户端内 UA 判定（网页授权分支，只在服务端判定，前端不参与）。 */
    private static boolean isWecomClient(String userAgent) {
        if (userAgent == null) {
            return false;
        }
        String ua = userAgent.toLowerCase();
        return ua.contains("micromessenger") || ua.contains("wxwork");
    }

    private String toJson(Map<String, Object> map) {
        try {
            return objectMapper.writeValueAsString(map);
        } catch (Exception e) {
            throw new IllegalStateException("构造凭据 JSON 失败", e);
        }
    }

    private JsonNode parse(String body) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readTree(body);
        } catch (Exception e) {
            return null;
        }
    }

    private String jsonOf(String k, String v) {
        try {
            com.fasterxml.jackson.databind.node.ObjectNode n = objectMapper.createObjectNode();
            n.put(k, v);
            return objectMapper.writeValueAsString(n);
        } catch (Exception e) {
            throw new IllegalStateException("构造凭据 JSON 失败", e);
        }
    }

    private static String urlEncode(String s) {
        return URLEncoder.encode(s == null ? "" : s, StandardCharsets.UTF_8);
    }

    private static String hostOf(String url) {
        try {
            URI u = new URI(url);
            return u.getHost();
        } catch (Exception e) {
            return null;
        }
    }

    private static String hostOfHeader(String host) {
        if (host == null) {
            return null;
        }
        int idx = host.indexOf(':');
        return idx >= 0 ? host.substring(0, idx) : host;
    }

    /**
     * 取应用 access_token（复用租户级 / 平台级凭据解析与官方 gettoken 调用，不另造第二套）。
     * errcode!=0 抛 {@link BizException} 带 errmsg；令牌明文<b>绝不</b>对外返回（仅内部透传给官方接口）。
     *
     * @throws BizException 缺配置或 errcode!=0
     */
    public WeComToken getToken(Long tenantId) {
        // access_token 官方有效期 7200s；内存缓存至剩 5 分钟，避免每次工具调用都打 gettoken
        // （官方对 gettoken 有频率限制，频繁刷新会返回 45009）。缓存只在进程内，不落盘。
        synchronized (TOKEN_CACHE_LOCK) {
            CachedToken cached = TOKEN_CACHE.get(tenantId);
            if (cached != null && LocalDateTime.now().isBefore(cached.expiresAt())) {
                return cached.token();
            }
        }
        ConnectorCatalogService.WeComCredentials creds = catalogService.resolveWeCom(tenantId);
        if (creds == null) {
            throw BizException.badRequest("企业微信未配置：请管理员在连接器里填写 corpId / agentId / corpSecret");
        }
        String resp = httpGet(GETTOKEN_URL + "?corpid=" + urlEncode(creds.corpId())
                + "&corpsecret=" + urlEncode(creds.corpSecret()));
        JsonNode tk = parse(resp);
        if (tk == null || tk.path("errcode").asInt(0) != 0) {
            String msg = tk == null ? "无响应" : tk.path("errmsg").asText("");
            throw BizException.badRequest("企业微信获取 access_token 失败：" + msg);
        }
        WeComToken token = new WeComToken(tk.path("access_token").asText(), creds.agentId(),
                tk.path("expires_in").asInt(7200));
        synchronized (TOKEN_CACHE_LOCK) {
            TOKEN_CACHE.put(tenantId, new CachedToken(token,
                    LocalDateTime.now().plusSeconds(Math.max(60, token.expiresIn() - 300L))));
        }
        return token;
    }

    private static final Object TOKEN_CACHE_LOCK = new Object();
    private static final java.util.concurrent.ConcurrentHashMap<Long, CachedToken> TOKEN_CACHE =
            new java.util.concurrent.ConcurrentHashMap<>();

    private record CachedToken(WeComToken token, LocalDateTime expiresAt) {
    }

    /** 企业微信 access_token 三元组（accessToken 不应对外暴露）。 */
    public record WeComToken(String accessToken, String agentId, int expiresIn) {
    }
}
