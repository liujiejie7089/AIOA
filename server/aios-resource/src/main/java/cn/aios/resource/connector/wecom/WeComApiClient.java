package cn.aios.resource.connector.wecom;

import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.service.WeComOAuthService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

/**
 * 企业微信应用 API 客户端（docs/59 §10.3 wechat_work 内置工具）。
 *
 * <p>凭据由 {@link WeComOAuthService#getToken} 统一解析与获取（租户级 {@code connector_tenant_config}
 * 优先、平台级兜底），本类只负责「发消息」这一步；access_token 仅用于拼接官方接口 URL，
 * <b>绝不</b>写入日志或返回给模型。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WeComApiClient {

    private static final String SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send";
    private static final Duration TIMEOUT = Duration.ofSeconds(8);
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(TIMEOUT)
            .build();

    private final WeComOAuthService weComOAuthService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 以授权用户身份发送文本消息；errcode!=0 抛 BizException 带 errmsg。不落库正文。 */
    public Map<String, Object> sendTextMessage(Long tenantId, String touser, String content) {
        WeComOAuthService.WeComToken tk = weComOAuthService.getToken(tenantId);
        try {
            ObjectNode body = objectMapper.createObjectNode();
            body.put("touser", touser);
            body.put("msgtype", "text");
            body.put("agentid", tk.agentId());
            ObjectNode text = objectMapper.createObjectNode();
            text.put("content", content);
            body.set("text", text);

            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(SEND_URL + "?access_token=" + tk.accessToken()))
                    .timeout(TIMEOUT)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(
                            objectMapper.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
            JsonNode node = objectMapper.readTree(resp.body());
            int errcode = node.path("errcode").asInt(0);
            if (errcode != 0) {
                throw BizException.badRequest("企业微信发送失败：" + node.path("errmsg").asText("未知错误"));
            }
            return Map.of("ok", true, "errcode", 0, "msgid", node.path("msgid").asText(""));
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            log.debug("企业微信发送 HTTP 异常: {}", e.getClass().getSimpleName());
            throw BizException.badRequest("企业微信发送请求失败：" + e.getClass().getSimpleName());
        }
    }
}
