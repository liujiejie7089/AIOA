package cn.aios.resource.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.service.PortalService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
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

    // ══════════════════════════════════════════════════════════════════════════
    //  写链路（2026-10-31）：V94 只建了表与只读查询，业务上没有入口 ⇒ 补到四层全通
    //    POST   /api/v1/portal/schedules                 新建日程
    //    PUT    /api/v1/portal/schedules/{id}            改日程（仅本人）
    //    DELETE /api/v1/portal/schedules/{id}            删日程（逻辑删，仅本人）
    //    POST   /api/v1/portal/meetings                  发起会议（带参会人 + 房间冲突校验）
    //    POST   /api/v1/portal/meetings/{id}/cancel      取消会议（仅组织者）
    //    POST   /api/v1/portal/meetings/{id}/respond?decision=ACCEPTED|DECLINED  应答（仅受邀人）
    // 参数校验失败统一由 FormRuleExceptionHandler 之类转 400 业务错误；归属/越权在服务层抛 404。
    // ══════════════════════════════════════════════════════════════════════════

    @PostMapping("/schedules")
    public ApiResponse<Map<String, Object>> createSchedule(@RequestBody Map<String, Object> body) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.createSchedule(user.getTenantId(), user.getUserId(), body));
    }

    @PutMapping("/schedules/{id}")
    public ApiResponse<Map<String, Object>> updateSchedule(@PathVariable("id") Long id,
                                                           @RequestBody Map<String, Object> body) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.updateSchedule(user.getTenantId(), user.getUserId(), id, body));
    }

    @DeleteMapping("/schedules/{id}")
    public ApiResponse<Map<String, Object>> deleteSchedule(@PathVariable("id") Long id) {
        AuthUser user = AuthUserContext.require();
        portalService.deleteSchedule(user.getTenantId(), user.getUserId(), id);
        return ApiResponse.ok(Map.of("id", id));
    }

    @PostMapping("/meetings")
    public ApiResponse<Map<String, Object>> createMeeting(@RequestBody Map<String, Object> body) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(portalService.createMeeting(user.getTenantId(), user.getUserId(),
                user.getUsername(), body));
    }

    @PostMapping("/meetings/{id}/cancel")
    public ApiResponse<Map<String, Object>> cancelMeeting(@PathVariable("id") Long id) {
        AuthUser user = AuthUserContext.require();
        portalService.cancelMeeting(user.getTenantId(), user.getUserId(), id);
        return ApiResponse.ok(Map.of("id", id, "status", "CANCELED"));
    }

    @PostMapping("/meetings/{id}/respond")
    public ApiResponse<Map<String, Object>> respondMeeting(@PathVariable("id") Long id,
                                                           @RequestParam("decision") String decision) {
        AuthUser user = AuthUserContext.require();
        portalService.respondMeeting(user.getTenantId(), user.getUserId(), id, decision);
        return ApiResponse.ok(Map.of("id", id, "inviteStatus", decision));
    }
}
