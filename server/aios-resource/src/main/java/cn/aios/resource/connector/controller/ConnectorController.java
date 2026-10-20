package cn.aios.resource.connector.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.service.ConnectorCatalogService;
import cn.aios.resource.connector.service.ConnectorConnectionService;
import cn.aios.resource.connector.service.WeComOAuthService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.List;
import java.util.Map;

/**
 * 连接器用户端接口（docs/58 §4）。前缀 /api/v1/connectors；callback 返回 302。
 *
 * <pre>
 *   GET    /api/v1/connectors                           目录 + 我的状态 + 就绪度
 *   GET    /api/v1/connectors/{code}                    详情（mode / fields / helpText / helpUrl）
 *   POST   /api/v1/connectors/{code}/connect/start      CREDENTIAL→fields；OAUTH2→authUrl
 *   POST   /api/v1/connectors/{code}/connect/credential 提交凭据（真实校验后落库）
 *   POST   /api/v1/connectors/{code}/verify             重新检测
 *   POST   /api/v1/connectors/{code}/disconnect         断开
 *   GET    /api/v1/connectors/{code}/callback           OAuth 回跳（302）
 * </pre>
 */
@RestController
@RequestMapping("/api/v1/connectors")
@RequiredArgsConstructor
public class ConnectorController {

    private final ConnectorCatalogService catalogService;
    private final ConnectorConnectionService connectionService;
    private final WeComOAuthService weComService;

    @GetMapping
    public ApiResponse<List<ConnectorCatalogService.ConnectorItem>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(catalogService.list(user.getTenantId(), user.getUserId()));
    }

    @GetMapping("/{code}")
    public ApiResponse<ConnectorCatalogService.ConnectorDetail> detail(@PathVariable String code) {
        AuthUserContext.require();
        return ApiResponse.ok(catalogService.detail(code, AuthUserContext.tenantIdOrDefault()));
    }

    @PostMapping("/{code}/connect/start")
    public ApiResponse<ConnectorCatalogService.ConnectorStart> start(@PathVariable String code,
                                                                    @RequestBody(required = false) StartBody body,
                                                                    HttpServletRequest request) {
        AuthUser user = AuthUserContext.require();
        ConnectorDef def = catalogService.requireDef(code);
        if (ConnectorDef.AUTH_MODE_CREDENTIAL.equals(def.getAuthMode())) {
            return ApiResponse.ok(new ConnectorCatalogService.ConnectorStart(
                    "CREDENTIAL", null, catalogService.credentialFields(code)));
        }
        String returnPath = body == null ? null : body.returnPath();
        String origin = resolveOrigin(request);
        String host = request.getHeader("Host");
        return ApiResponse.ok(weComService.start(user, code, returnPath, origin, host));
    }

    @PostMapping("/{code}/connect/credential")
    public ApiResponse<ConnectorConnectionService.ConnectResult> connectCredential(
            @PathVariable String code, @RequestBody CredentialBody body) {
        AuthUser user = AuthUserContext.require();
        Map<String, String> values = (body == null || body.values() == null) ? Map.of() : body.values();
        return ApiResponse.ok(connectionService.connectWithCredential(user, code, values));
    }

    @PostMapping("/{code}/verify")
    public ApiResponse<ConnectorConnectionService.VerifyResult> verify(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(connectionService.verify(user, code));
    }

    @PostMapping("/{code}/disconnect")
    public ApiResponse<Map<String, String>> disconnect(@PathVariable String code) {
        AuthUser user = AuthUserContext.require();
        connectionService.disconnect(user, code);
        return ApiResponse.ok(Map.of("status", "NEED_AUTH"));
    }

    @GetMapping("/{code}/callback")
    public ResponseEntity<Void> callback(@RequestParam("code") String code,
                                         @RequestParam("state") String state) {
        String location = weComService.callback(code, state);
        return ResponseEntity.status(HttpStatus.FOUND).location(URI.create(location)).build();
    }

    /** 取回调页安全用的 Origin：优先 Origin 头，否则从 Referer 推导 scheme+host。 */
    private static String resolveOrigin(HttpServletRequest request) {
        String origin = request.getHeader("Origin");
        if (origin != null && !origin.isBlank()) {
            return origin;
        }
        String referer = request.getHeader("Referer");
        if (referer != null && !referer.isBlank()) {
            try {
                URI u = URI.create(referer);
                if (u.getHost() != null) {
                    String scheme = u.getScheme() == null ? "https" : u.getScheme();
                    int port = u.getPort();
                    String hostPart = (port != -1 && port != 80 && port != 443)
                            ? u.getHost() + ":" + port : u.getHost();
                    return scheme + "://" + hostPart;
                }
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    public record StartBody(String returnPath) {
    }

    public record CredentialBody(Map<String, String> values) {
    }
}
