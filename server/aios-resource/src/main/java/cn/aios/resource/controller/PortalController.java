package cn.aios.resource.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.service.PortalService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 管理端首页门户模块（对齐 OA 工作台设计稿）：
 *   GET /api/v1/portal/announcements            —— 公告列表（PUBLISHED，publish_at 倒序，本租户 + 公共）
 *   GET /api/v1/portal/meetings?scope=mine|invited —— 会议（mine=我组织的 / invited=邀请我的）
 *   GET /api/v1/portal/schedules?month=yyyy-MM   —— 当月日程（当前用户）
 *   GET /api/v1/portal/schedules/today           —— 今日日程（当前用户）
 * 全部按租户隔离：本租户数据 + tenant_id=0 平台公共数据。
 */
@RestController
@RequestMapping("/api/v1/portal")
@RequiredArgsConstructor
public class PortalController {

    private final PortalService portalService;

    @GetMapping("/announcements")
    public ApiResponse<Map<String, Object>> announcements(
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "10") int size) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.listAnnouncements(user.getTenantId(), page, size));
    }

    @GetMapping("/meetings")
    public ApiResponse<Map<String, Object>> meetings(
            @RequestParam(name = "scope", defaultValue = "mine") String scope,
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "10") int size) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.listMeetings(user.getTenantId(), user.getUserId(), scope, page, size));
    }

    @GetMapping("/schedules")
    public ApiResponse<Map<String, Object>> schedules(
            @RequestParam(name = "month") String month) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.listSchedules(user.getTenantId(), user.getUserId(), month));
    }

    @GetMapping("/schedules/today")
    public ApiResponse<Map<String, Object>> schedulesToday() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.listSchedulesToday(user.getTenantId(), user.getUserId()));
    }
}
