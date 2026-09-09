package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.TenantQuota;
import cn.aioa.resource.mapper.TenantQuotaMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 配额管理（管理端，技术方案 5.2 一期清单）：
 *   GET /api/v1/admin/quotas            —— 租户成员配额总览（本级配额查看）
 *   PUT /api/v1/admin/quotas/{userId}   —— 向成员二次分配配额（body: {quotaTokens}）
 *   GET /api/v1/admin/quotas/usage      —— 用量报表（本月按业务类型聚合 + 最近流水）
 */
@RestController
@RequestMapping("/api/v1/admin/quotas")
@RequiredArgsConstructor
public class AdminQuotaController {

    private final TenantQuotaMapper quotaMapper;

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("配额管理仅租户管理员可操作");
        }
        return user;
    }

    @GetMapping
    public ApiResponse<Map<String, Object>> overview() {
        AuthUser user = requireAdmin();
        List<Map<String, Object>> users = quotaMapper.selectTenantQuotaOverview(user.getTenantId());
        long totalQuota = users.stream().mapToLong(u -> num(u.get("quotaTokens"))).sum();
        long totalUsed = users.stream().mapToLong(u -> num(u.get("usedTokens"))).sum();
        long totalFree = users.stream().mapToLong(u -> num(u.get("freeTokens"))).sum();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("totalQuota", totalQuota);
        data.put("totalUsed", totalUsed);
        data.put("totalFree", Math.max(0, totalQuota + totalFree - totalUsed));
        data.put("memberCount", users.size());
        data.put("users", users);
        return ApiResponse.ok(data);
    }

    /** 向成员二次分配：直接设定该成员的词元配额（含已用不变，剩余随新配额变化）。 */
    @PutMapping("/{userId}")
    public ApiResponse<Map<String, Object>> assign(@PathVariable Long userId,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser user = requireAdmin();
        long quota = num(body.get("quotaTokens"));
        if (quota < 0) {
            throw BizException.badRequest("配额不能为负数");
        }
        if (quota > 1_000_000_000L) {
            throw BizException.badRequest("单成员配额上限 10 亿词元");
        }
        TenantQuota row = quotaMapper.selectOne(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<TenantQuota>()
                .eq(TenantQuota::getTenantId, user.getTenantId())
                .eq(TenantQuota::getUserId, userId)
                .last("limit 1"));
        if (row == null) {
            row = new TenantQuota();
            row.setTenantId(user.getTenantId());
            row.setUserId(userId);
            row.setQuotaTokens(quota);
            row.setUsedTokens(0L);
            row.setFreeTokens(0L);
            row.setCreatedAt(LocalDateTime.now());
            row.setCreatedBy(user.getUserId());
        } else {
            row.setQuotaTokens(quota);
        }
        row.setUpdatedAt(LocalDateTime.now());
        if (row.getId() == null) {
            quotaMapper.insert(row);
        } else {
            quotaMapper.updateById(row);
        }
        return ApiResponse.ok(Map.of("userId", userId, "quotaTokens", quota));
    }

    @GetMapping("/usage")
    public ApiResponse<Map<String, Object>> usage(@RequestParam(name = "days", defaultValue = "30") int days) {
        AuthUser user = requireAdmin();
        LocalDateTime since = LocalDate.now().minusDays(Math.max(1, Math.min(days, 365))).atStartOfDay();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("since", since.toLocalDate().toString());
        data.put("byBizType", quotaMapper.selectUsageByBizType(user.getTenantId(), since));
        data.put("recentLedger", quotaMapper.selectRecentLedger(user.getTenantId(), 20));
        return ApiResponse.ok(data);
    }

    private static long num(Object v) {
        if (v == null) return 0L;
        if (v instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(v));
        } catch (NumberFormatException e) {
            return 0L;
        }
    }
}
