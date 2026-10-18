package cn.aios.admin.controller;

import cn.aios.admin.entity.AppRegistry;
import cn.aios.admin.service.AppService;
import cn.aios.common.resp.ApiResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1/apps")
public class AppController {

    private final AppService appService;

    public AppController(AppService appService) {
        this.appService = appService;
    }

    public record AppItem(String appCode, String appName, String entryUrl, String routePrefix,
                          String hostType, String icon, String permissionCode, Integer sort) {

        static AppItem from(AppRegistry a) {
            return new AppItem(a.getAppCode(), a.getName(), a.getEntryUrl(), a.getRoutePrefix(),
                    a.getHostType(), a.getIcon(), a.getPermissionCode(), a.getSort());
        }
    }

    @GetMapping
    public ApiResponse<List<AppItem>> list() {
        // 可见范围过滤：ADMIN-only 的功能模块对普通用户隐藏（角色取当前登录态）
        List<String> roles = java.util.Optional.ofNullable(cn.aios.security.AuthUserContext.get())
                .map(cn.aios.security.AuthUser::getRoles).orElse(java.util.List.of());
        return ApiResponse.ok(appService.enabledAppsFor(roles).stream().map(AppItem::from).toList());
    }
}
