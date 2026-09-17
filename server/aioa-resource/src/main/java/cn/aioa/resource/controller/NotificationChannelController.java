package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.NotificationDelivery;
import cn.aioa.resource.mapper.NotificationDeliveryMapper;
import cn.aioa.resource.service.notify.NotificationChannelConfigService;
import cn.aioa.resource.service.notify.NotificationDispatcher;
import cn.aioa.resource.service.notify.NotificationPreferenceService;
import cn.aioa.resource.support.NotificationTenantGuard;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 统一消息中心管理接口（租户管理员端 + 本人偏好端）。
 *
 * <p>作用域纪律（与 GiteeController V50 端点一致，但用本模块可用的
 * {@link NotificationTenantGuard} 替代 OrgGuard，因为 aioa-resource 不依赖 aioa-org）：
 * 租户级端点先 {@code requireTenantAdmin()} 再 {@code resolveTenant(...)}；
 * 偏好端点只认当前登录用户本人。</p>
 */
@RestController
@RequestMapping("/api/v1/notifications")
@RequiredArgsConstructor
public class NotificationChannelController {

    private final NotificationTenantGuard guard;
    private final NotificationChannelConfigService channelConfigService;
    private final NotificationPreferenceService preferenceService;
    private final NotificationDeliveryMapper deliveryMapper;
    private final NotificationDispatcher dispatcher;

    // ======================================================================
    // 通道配置（租户管理员）
    // ======================================================================

    /** 通道列表（含启用状态与配置完备性）。 */
    @GetMapping("/channels")
    public ApiResponse<Map<String, Object>> channels(@RequestParam(required = false) Long tenantId) {
        AuthUser u = guard.requireTenantAdmin();
        Long tid = guard.resolveTenant(u, tenantId);
        List<Map<String, Object>> items = channelConfigService.list(tid);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("items", items);
        data.put("total", items.size());
        return ApiResponse.ok(data);
    }

    /** 单条通道保存（启用开关 + 配置）。 */
    @PutMapping("/channels/{code}")
    public ApiResponse<Map<String, Object>> saveChannel(@PathVariable String code,
                                                        @RequestParam(required = false) Long tenantId,
                                                        @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Long tid = guard.resolveTenant(u, tenantId);
        boolean enabled = bool(body == null ? null : body.get("enabled"), false);
        @SuppressWarnings("unchecked")
        Map<String, Object> config = (body != null && body.get("config") instanceof Map)
                ? (Map<String, Object>) body.get("config") : null;
        return ApiResponse.ok(channelConfigService.save(tid, code, enabled, config, u.getUserId()));
    }

    /** 真实发送一条测试消息。 */
    @PostMapping("/channels/{code}/test")
    public ApiResponse<Map<String, Object>> testChannel(@PathVariable String code,
                                                        @RequestParam(required = false) Long tenantId,
                                                        @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Long tid = guard.resolveTenant(u, tenantId);
        String to = body == null ? null : str(body.get("to"));
        return ApiResponse.ok(channelConfigService.test(tid, code, to, u.getUserId()));
    }

    // ======================================================================
    // 投递记录（租户管理员）
    // ======================================================================

    /** 投递记录列表（分页遵守 total 纪律，不用列表长度冒充总数）。 */
    @GetMapping("/deliveries")
    public ApiResponse<Map<String, Object>> deliveries(@RequestParam(required = false) Long tenantId,
                                                       @RequestParam(required = false) String status,
                                                       @RequestParam(required = false) Long notificationId,
                                                       @RequestParam(defaultValue = "50") int limit) {
        AuthUser u = guard.requireTenantAdmin();
        Long tid = guard.resolveTenant(u, tenantId);

        LambdaQueryWrapper<NotificationDelivery> base = new LambdaQueryWrapper<NotificationDelivery>()
                .eq(NotificationDelivery::getTenantId, tid);
        if (status != null && !status.isBlank()) {
            base.eq(NotificationDelivery::getStatus, status);
        }
        if (notificationId != null) {
            base.eq(NotificationDelivery::getNotificationId, notificationId);
        }
        long total = deliveryMapper.selectCount(base);

        int cap = Math.max(1, Math.min(limit, 200));
        LambdaQueryWrapper<NotificationDelivery> pageQ = new LambdaQueryWrapper<NotificationDelivery>()
                .eq(NotificationDelivery::getTenantId, tid);
        if (status != null && !status.isBlank()) {
            pageQ.eq(NotificationDelivery::getStatus, status);
        }
        if (notificationId != null) {
            pageQ.eq(NotificationDelivery::getNotificationId, notificationId);
        }
        pageQ.orderByDesc(NotificationDelivery::getId).last("LIMIT " + cap);
        List<NotificationDelivery> rows = deliveryMapper.selectList(pageQ);

        List<Map<String, Object>> items = rows.stream().map(d -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", d.getId());
            m.put("tenantId", d.getTenantId());
            m.put("notificationId", d.getNotificationId());
            m.put("channelCode", d.getChannelCode());
            m.put("status", d.getStatus());
            m.put("attempts", d.getAttempts());
            m.put("lastError", d.getLastError());
            m.put("sentAt", d.getSentAt() == null ? null : d.getSentAt().toString());
            m.put("createdAt", d.getCreatedAt() == null ? null : d.getCreatedAt().toString());
            return m;
        }).toList();

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("items", items);
        data.put("total", total);
        return ApiResponse.ok(data);
    }

    /** 重投一条 FAILED/SKIPPED 投递。 */
    @PostMapping("/deliveries/{id}/retry")
    public ApiResponse<Map<String, Object>> retryDelivery(@PathVariable Long id,
                                                          @RequestParam(required = false) Long tenantId) {
        AuthUser u = guard.requireTenantAdmin();
        Long tid = guard.resolveTenant(u, tenantId);
        return ApiResponse.ok(dispatcher.retryDelivery(tid, id, u.getUserId()));
    }

    // ======================================================================
    // 用户偏好（本人）
    // ======================================================================

    /** 当前用户的通道偏好。 */
    @GetMapping("/preferences")
    public ApiResponse<Map<String, Object>> preferences() {
        AuthUser u = AuthUserContext.require();
        return ApiResponse.ok(preferenceService.get(
                u.getTenantId() == null ? 0L : u.getTenantId(), u.getUserId()));
    }

    /** 保存当前用户的通道偏好。 */
    @PutMapping("/preferences")
    public ApiResponse<Map<String, Object>> savePreferences(@RequestBody Map<String, Object> body) {
        AuthUser u = AuthUserContext.require();
        Long tid = u.getTenantId() == null ? 0L : u.getTenantId();
        @SuppressWarnings("unchecked")
        List<String> defaultChannels = (body != null && body.get("defaultChannels") instanceof List)
                ? (List<String>) body.get("defaultChannels") : List.of();
        @SuppressWarnings("unchecked")
        Map<String, Object> byType = (body != null && body.get("byType") instanceof Map)
                ? (Map<String, Object>) body.get("byType") : Map.of();
        return ApiResponse.ok(preferenceService.put(tid, u.getUserId(), defaultChannels, byType, u.getUserId()));
    }

    // -------------------------------------------------------------- 工具

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o).trim();
    }

    private static boolean bool(Object o, boolean def) {
        if (o == null) {
            return def;
        }
        if (o instanceof Boolean b) {
            return b;
        }
        String s = String.valueOf(o).trim();
        return s.isEmpty() ? def : ("true".equalsIgnoreCase(s) || "1".equals(s));
    }
}
