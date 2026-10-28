package cn.aios.admin.wecom;

import cn.aios.common.resp.ApiResponse;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
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

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.util.Map;

/**
 * 企业微信 OAuth 网页授权「静默登录」端点（{@code /api/v1/auth/wecom/*}）。
 *
 * <pre>
 *   GET  /api/v1/auth/wecom/start?returnPath=/aios/h5/   302 跳企业微信授权页（公开）
 *   GET  /api/v1/auth/wecom/callback?code&state          302 回 H5（公开；hash 带令牌）
 *   GET  /api/v1/auth/wecom/status?state=                待绑定身份（公开；state 即能力）
 *   POST /api/v1/auth/wecom/bind  {state}                本地登录后建立绑定（需登录态）
 * </pre>
 *
 * <p>start/callback/status 均在 {@code /api/v1/auth/**} 公开白名单内（浏览器跳转无 JWT），
 * 安全由一次性 state（10 分钟 + 用后即废）与 Origin/Host 一致性校验保证。</p>
 */
@RestController
@RequestMapping("/api/v1/auth/wecom")
@RequiredArgsConstructor
public class WeComLoginController {

    private final WeComLoginService service;

    @GetMapping("/start")
    public ResponseEntity<Void> start(@RequestParam(value = "returnPath", required = false) String returnPath,
                                      HttpServletRequest request) {
        String origin = resolveOrigin(request);
        String location = service.start(
                returnPath == null || returnPath.isBlank() ? "/aios/h5/" : returnPath,
                origin, request.getHeader("Host"));
        return ResponseEntity.status(HttpStatus.FOUND).location(URI.create(location)).build();
    }

    @GetMapping("/callback")
    public ResponseEntity<Void> callback(@RequestParam("code") String code,
                                         @RequestParam("state") String state,
                                         HttpServletRequest request) {
        String location = service.callback(code, state, clientIp(request), request.getHeader("User-Agent"));
        return ResponseEntity.status(HttpStatus.FOUND).location(URI.create(location)).build();
    }

    @GetMapping("/status")
    public ApiResponse<Map<String, Object>> status(@RequestParam("state") String state) {
        return ApiResponse.ok(service.pendingStatus(state));
    }

    @PostMapping("/bind")
    public ApiResponse<Map<String, Object>> bind(@RequestBody BindBody body) {
        AuthUser user = AuthUserContext.require();
        String state = body == null ? null : body.state();
        return ApiResponse.ok(service.bind(state, user));
    }

    public record BindBody(String state) {
    }

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

    private static String clientIp(HttpServletRequest request) {
        String xff = request.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            return xff.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
