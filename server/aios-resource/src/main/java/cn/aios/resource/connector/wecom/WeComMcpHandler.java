package cn.aios.resource.connector.wecom;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.mapper.ConnectorConnectionMapper;
import cn.aios.resource.connector.mcp.spi.McpBuiltinHandler;
import cn.aios.resource.connector.service.WeComOAuthService;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 企业微信内置 MCP 工具实现（serverCode = {@code wechat_work}，docs/59 §10.3）。
 *
 * <p>实现 {@link McpBuiltinHandler}：Spring 自动把本 Bean 注入 {@code McpBuiltinBridge} 的
 * {@code List<McpBuiltinHandler>}，按 serverCode + supports 派发，无需改动桥接代码。</p>
 *
 * <p>凭据一律来自 {@link WeComOAuthService#getToken(tenantId)}（当前用户所在租户），<b>禁止</b>从入参
 * 接受 tenantId/userId；access_token 明文不返回给模型。</p>
 *
 * <p>{@code get_my_profile}（V99，snsapi_privateinfo 网页授权链路）只从本用户已连接的
 * {@code connector_connection.credential_json}（SecretCodec 加密）读 userid / biz_mail，
 * 绝不回传 user_ticket（1800s 一次性，授权回调后即弃）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WeComMcpHandler implements McpBuiltinHandler {

    private final WeComOAuthService weComOAuthService;
    private final WeComApiClient weComApiClient;
    private final ConnectorConnectionMapper connectionMapper;
    private final SecretCodec secretCodec;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public String serverCode() {
        return "wechat_work";
    }

    @Override
    public boolean supports(String tool) {
        return "check_connection".equals(tool) || "send_text_message".equals(tool)
                || "get_my_profile".equals(tool);
    }

    @Override
    public Object call(String tool, Map<String, Object> args, AuthUser user) {
        if ("check_connection".equals(tool)) {
            WeComOAuthService.WeComToken tk = weComOAuthService.getToken(user.getTenantId());
            // 只回传 agentId 与有效期，绝不回传 access_token 明文
            return Map.of("ok", true, "agentId", tk.agentId(), "expiresIn", tk.expiresIn());
        }
        if ("send_text_message".equals(tool)) {
            Map<String, Object> a = args == null ? Map.of() : args;
            String touser = asString(a.get("touser"));
            String content = asString(a.get("content"));
            if (touser == null || touser.isBlank()) {
                throw BizException.badRequest("缺少参数 touser");
            }
            if (content == null || content.isBlank()) {
                throw BizException.badRequest("缺少参数 content");
            }
            return weComApiClient.sendTextMessage(user.getTenantId(), touser, content);
        }
        if ("get_my_profile".equals(tool)) {
            return myProfile(user);
        }
        throw BizException.badRequest("不支持的工具：" + tool);
    }

    /** 读当前用户的企业微信身份（userid / biz_mail），credential_json 由授权回调加密写入。 */
    private Object myProfile(AuthUser user) {
        ConnectorConnection c = connectionMapper.selectOne(new LambdaQueryWrapper<ConnectorConnection>()
                .eq(ConnectorConnection::getTenantId, user.getTenantId())
                .eq(ConnectorConnection::getUserId, user.getUserId())
                .eq(ConnectorConnection::getConnectorCode, "wechat_work"));
        if (c == null || !ConnectorConnection.STATUS_CONNECTED.equals(c.getStatus())) {
            throw BizException.badRequest("企业微信尚未授权连接：请在「插件-技能-连接器」完成企业微信授权（须在企业微信客户端内打开）");
        }
        Map<String, Object> profile = new LinkedHashMap<>();
        profile.put("ok", true);
        profile.put("userid", c.getAccountLabel());
        try {
            JsonNode cred = objectMapper.readTree(secretCodec.decrypt(c.getCredentialJson()));
            if (cred.hasNonNull("userid")) {
                profile.put("userid", cred.get("userid").asText());
            }
            if (cred.hasNonNull("biz_mail")) {
                profile.put("biz_mail", cred.get("biz_mail").asText());
            }
            if (cred.hasNonNull("name")) {
                profile.put("name", cred.get("name").asText());
            } else {
                // snsapi_privateinfo 才拿得到 biz_mail；PC 扫码授权的旧连接如实缺省，不编造
                profile.put("biz_mail", null);
                profile.put("hint", "当前连接由 PC 扫码授权建立，未包含企业邮箱；请重新授权（企业微信客户端内）");
            }
        } catch (Exception e) {
            log.debug("credential_json 解析失败: {}", e.getClass().getSimpleName());
        }
        return profile;
    }

    private static String asString(Object v) {
        return v == null ? null : String.valueOf(v);
    }
}
