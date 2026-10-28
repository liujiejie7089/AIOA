package cn.aios.common.wecom;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * 企业微信官方接口客户端（{@code qyapi.weixin.qq.com}）。
 *
 * <p><b>唯一实现</b>：连接器 OAuth（{@code cn.aios.resource.connector.wecom}）与
 * 企微 OAuth 登录（{@code cn.aios.admin.wecom}）共用本类，不再各造一套 HTTP。
 * 纯 JDK 实现，无第三方依赖；body 里<b>绝不</b>记录 access_token / corpSecret。</p>
 *
 * <p>只封装三个只读接口：gettoken（应用 access_token）、auth/getuserinfo（code → userid
 * + user_ticket）、auth/getuserdetail（user_ticket → userid/name/biz_mail）。</p>
 */
public class WeComAuthClient {

    private static final String BASE = "https://qyapi.weixin.qq.com/cgi-bin";
    private static final Duration TIMEOUT = Duration.ofSeconds(8);
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(TIMEOUT)
            .build();
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** 应用 access_token（官方有效期 7200s，调用方自行缓存）。 */
    public Token getToken(String corpId, String corpSecret) {
        JsonNode n = get(BASE + "/gettoken?corpid=" + enc(corpId) + "&corpsecret=" + enc(corpSecret));
        requireOk(n, "gettoken");
        return new Token(n.path("access_token").asText(), n.path("expires_in").asInt(7200));
    }

    /**
     * OAuth code → 身份。snsapi_privateinfo 授权时额外返回 user_ticket（1800s 有效，
     * 只可用于一次 getuserdetail）；snsapi_base / PC 扫码无 user_ticket。
     */
    public UserInfo getUserInfo(String accessToken, String code) {
        JsonNode n = get(BASE + "/auth/getuserinfo?access_token=" + enc(accessToken) + "&code=" + enc(code));
        requireOk(n, "auth/getuserinfo");
        return new UserInfo(n.path("userid").asText(null), n.path("user_ticket").asText(null));
    }

    /** user_ticket → 详细身份（POST）。 */
    public UserDetail getUserDetail(String accessToken, String userTicket) {
        JsonNode n = post(BASE + "/auth/getuserdetail?access_token=" + enc(accessToken),
                "{\"user_ticket\":\"" + userTicket.replace("\"", "") + "\"}");
        requireOk(n, "auth/getuserdetail");
        return new UserDetail(n.path("userid").asText(null), n.path("name").asText(null),
                n.path("biz_mail").asText(null));
    }

    /** access_token + 有效期（accessToken 不应外泄）。 */
    public record Token(String accessToken, int expiresIn) {
    }

    public record UserInfo(String userid, String userTicket) {
    }

    public record UserDetail(String userid, String name, String bizMail) {
    }

    private static void requireOk(JsonNode n, String api) {
        if (n == null) {
            throw new IllegalStateException("企业微信 " + api + " 无响应");
        }
        int errcode = n.path("errcode").asInt(0);
        if (errcode != 0) {
            throw new IllegalStateException("企业微信 " + api + " 失败 errcode=" + errcode
                    + " errmsg=" + n.path("errmsg").asText(""));
        }
    }

    private static JsonNode get(String url) {
        try {
            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(url)).timeout(TIMEOUT).GET().build();
            return parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body());
        } catch (Exception e) {
            throw new IllegalStateException("企业微信 GET 异常: " + e.getClass().getSimpleName(), e);
        }
    }

    private static JsonNode post(String url, String jsonBody) {
        try {
            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(url)).timeout(TIMEOUT)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody, StandardCharsets.UTF_8))
                    .build();
            return parse(HTTP.send(req, HttpResponse.BodyHandlers.ofString()).body());
        } catch (Exception e) {
            throw new IllegalStateException("企业微信 POST 异常: " + e.getClass().getSimpleName(), e);
        }
    }

    private static JsonNode parse(String body) {
        try {
            return body == null || body.isBlank() ? null : MAPPER.readTree(body);
        } catch (Exception e) {
            return null;
        }
    }

    private static String enc(String s) {
        return URLEncoder.encode(s == null ? "" : s, StandardCharsets.UTF_8);
    }
}
