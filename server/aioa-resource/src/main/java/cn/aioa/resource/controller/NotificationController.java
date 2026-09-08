package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.Notification;
import cn.aioa.resource.service.NotificationService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 站内通知（审批事件驱动）：
 *   GET  /api/v1/notifications             —— 我的通知（默认 20 条，含 unread 计数）
 *   POST /api/v1/notifications/{id}/read   —— 单条标记已读（仅本人的）
 *   POST /api/v1/notifications/read-all    —— 全部标记已读
 */
@RestController
@RequestMapping("/api/v1/notifications")
@RequiredArgsConstructor
public class NotificationController {

    private final NotificationService notificationService;

    public record NotificationView(Long id, String type, String title, String content, Long refId,
                                   boolean unread, String readAt, String createdAt) {

        static NotificationView from(Notification n) {
            return new NotificationView(n.getId(), n.getType(), n.getTitle(), n.getContent(), n.getRefId(),
                    n.getReadAt() == null,
                    n.getReadAt() == null ? null : n.getReadAt().toString(),
                    n.getCreatedAt() == null ? null : n.getCreatedAt().toString());
        }
    }

    @GetMapping
    public ApiResponse<Map<String, Object>> list(@RequestParam(name = "limit", defaultValue = "20") int limit) {
        AuthUser user = AuthUserContext.require();
        List<Notification> items = notificationService.listMine(user.getTenantId(), user.getUserId(), limit);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("items", items.stream().map(NotificationView::from).toList());
        data.put("unread", notificationService.unreadCount(user.getTenantId(), user.getUserId()));
        return ApiResponse.ok(data);
    }

    @PostMapping("/{id}/read")
    public ApiResponse<Boolean> read(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        if (!notificationService.markRead(user.getTenantId(), user.getUserId(), id)) {
            throw BizException.notFound("通知不存在或已读：" + id);
        }
        return ApiResponse.ok(Boolean.TRUE);
    }

    @PostMapping("/read-all")
    public ApiResponse<Integer> readAll() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(notificationService.markAllRead(user.getTenantId(), user.getUserId()));
    }
}
