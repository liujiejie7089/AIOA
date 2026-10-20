package cn.aios.resource.connector.wecom;

import cn.aios.common.exception.BizException;
import cn.aios.resource.connector.mcp.spi.McpBuiltinHandler;
import cn.aios.resource.connector.service.WeComOAuthService;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 企业微信内置 MCP 工具实现（serverCode = {@code wechat_work}，docs/59 §10.3）。
 *
 * <p>实现 {@link McpBuiltinHandler}：Spring 自动把本 Bean 注入 {@code McpBuiltinBridge} 的
 * {@code List<McpBuiltinHandler>}，按 serverCode + supports 派发，无需改动桥接代码。</p>
 *
 * <p>凭据一律来自 {@link WeComOAuthService#getToken(tenantId)}（当前用户所在租户），<b>禁止</b>从入参
 * 接受 tenantId/userId；access_token 明文不返回给模型。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WeComMcpHandler implements McpBuiltinHandler {

    private final WeComOAuthService weComOAuthService;
    private final WeComApiClient weComApiClient;

    @Override
    public String serverCode() {
        return "wechat_work";
    }

    @Override
    public boolean supports(String tool) {
        return "check_connection".equals(tool) || "send_text_message".equals(tool);
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
        throw BizException.badRequest("不支持的工具：" + tool);
    }

    private static String asString(Object v) {
        return v == null ? null : String.valueOf(v);
    }
}
