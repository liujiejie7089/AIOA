package cn.aioa.admin.controller;

import cn.aioa.admin.entity.AppRegistry;
import cn.aioa.admin.service.AppService;
import cn.aioa.admin.service.AuthService;
import cn.aioa.common.resp.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class AuthController {

    private final AuthService authService;
    private final AppService appService;

    public AuthController(AuthService authService, AppService appService) {
        this.authService = authService;
        this.appService = appService;
    }

    /**
     * 登录请求体。
     *
     * <p>{@code tenantName} 为管理端登录页的「租户名称」字段：前端必填，用于防止
     * 「账号密码正确但登错租户」。为兼容既有客户端（用户端 H5、自动化脚本）该字段可为空，
     * 为空时后端跳过校验（详见 {@code AuthService.login} 的注释）。</p>
     */
    public record LoginRequest(String username, String password, String tenantName) {
    }

    public record RefreshRequest(String refreshToken) {
    }

    @PostMapping("/auth/login")
    public ApiResponse<AuthService.LoginData> login(@RequestBody LoginRequest body,
                                                    HttpServletRequest request) {
        AuthService.LoginData data = authService.login(
                body.username(), body.password(), body.tenantName(),
                clientIp(request), request.getHeader("User-Agent"));
        return ApiResponse.ok(data);
    }

    @PostMapping("/auth/refresh")
    public ApiResponse<Map<String, Object>> refresh(@RequestBody RefreshRequest body) {
        String access = authService.refresh(body.refreshToken());
        return ApiResponse.ok(Map.of("accessToken", access));
    }

    /**
     * 退出登录。
     *
     * <p>V46 起<b>服务端吊销令牌</b>（D-1）：access 与 refresh 两个令牌的 jti 都会写入
     * {@code revoked_token}，旧令牌立刻失效（此前只做审计，令牌在 TTL 内继续可用）。
     * 请求体里的 {@code refreshToken} 可选 —— 缺省时只吊销 Authorization 头携带的 access 令牌。</p>
     *
     * <p>端点仍然幂等且永不失败：令牌缺失 / 过期时也返回成功，
     * 否则前端登出流程会被 401 打断（此时它已经在清会话了）。</p>
     */
    @PostMapping("/auth/logout")
    public ApiResponse<Map<String, Object>> logout(HttpServletRequest request,
                                                   @RequestBody(required = false) RefreshRequest body) {
        authService.logout(bearerToken(request), body == null ? null : body.refreshToken(),
                clientIp(request), request.getHeader("User-Agent"));
        return ApiResponse.ok(Map.of("loggedOut", true));
    }

    /** 从 Authorization 头取 Bearer 令牌（缺失 / 形态不符返回 null）。 */
    private static String bearerToken(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            return null;
        }
        String token = header.substring(7).trim();
        return token.isEmpty() ? null : token;
    }

    @GetMapping("/auth/me")
    public ApiResponse<AuthService.MeData> me() {
        return ApiResponse.ok(authService.me());
    }

    /**
     * M1 菜单：静态结构 + 我的应用（app_registry）。
     * 前端按此渲染左侧菜单；M3 改为纯权限驱动。
     */
    @GetMapping("/auth/menus")
    public ApiResponse<List<Map<String, Object>>> menus() {
        List<Map<String, Object>> appChildren = appService.enabledApps().stream()
                .map(a -> Map.<String, Object>of(
                        "key", a.getRoutePrefix(),
                        "title", a.getName(),
                        "icon", a.getIcon() == null ? "grid" : a.getIcon()))
                .toList();
        return ApiResponse.ok(List.of(
                Map.of("key", "/home", "title", "首页", "icon", "home"),
                Map.of("key", "apps", "title", "我的应用", "icon", "menu", "children", appChildren),
                Map.of("key", "/approvals", "title", "审批中心", "icon", "checked"),
                Map.of("key", "/kb", "title", "知识库", "icon", "collection"),
                Map.of("key", "/admin", "title", "系统管理", "icon", "setting")));
    }

    private String clientIp(HttpServletRequest request) {
        String ip = request.getHeader("X-Forwarded-For");
        if (ip != null && !ip.isBlank()) {
            return ip.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
