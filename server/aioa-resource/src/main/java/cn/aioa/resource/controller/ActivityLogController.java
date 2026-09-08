package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.ClientActivityLog;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 用户端操作记录（对应原型「我的操作记录」）。
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class ActivityLogController {

    private final ActivityLogService activityLogService;

    public record LogView(Long id, String action, String status, String label, String createdAt) {

        static LogView from(ClientActivityLog l) {
            return new LogView(l.getId(), l.getAction(), l.getStatus(), l.getLabel(),
                    l.getCreatedAt() == null ? null : l.getCreatedAt().toString());
        }
    }

    @GetMapping("/logs")
    public ApiResponse<List<LogView>> list(@RequestParam(name = "limit", defaultValue = "50") int limit) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(activityLogService.list(user.getTenantId(), user.getUserId(), limit)
                .stream().map(LogView::from).toList());
    }
}
