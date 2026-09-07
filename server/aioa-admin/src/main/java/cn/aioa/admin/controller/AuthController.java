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

    public record LoginRequest(String username, String password) {
    }

    public record RefreshRequest(String refreshToken) {
    }

    @PostMapping("/auth/login")
    public ApiResponse<AuthService.LoginData> login(@RequestBody LoginRequest body,
                                                    HttpServletRequest request) {
        AuthService.LoginData data = authService.login(
                body.username(), body.password(), clientIp(request), request.getHeader("User-Agent"));
        return ApiResponse.ok(data);
    }

    @PostMapping("/auth/refresh")
    public ApiResponse<Map<String, Object>> refresh(@RequestBody RefreshRequest body) {
        String access = authService.refresh(body.refreshToken());
        return ApiResponse.ok(Map.of("accessToken", access));
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
