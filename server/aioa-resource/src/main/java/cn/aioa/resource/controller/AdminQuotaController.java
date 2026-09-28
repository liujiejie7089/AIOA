package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.TenantQuota;
import cn.aioa.resource.mapper.TenantQuotaMapper;
import cn.aioa.resource.support.ResourceTenantGuard;
import cn.aioa.security.AuthUser;
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
 *
 * <p><b>租户作用域（2026-09-28 补齐）</b>：三个端点均接受可选 {@code ?tenantId=}，
 * 由 {@link ResourceTenantGuard} 统一裁决 —— 平台管理员可跨租户运维，租户管理员硬绑定本租户。
 * 此前这里只认 {@code user.getTenantId()}，而平台管理员的 own tenant 恒为 0，
 * 于是「顶部切换租户 → 本页数据不变」（与 docs/37 §3 同型缺陷），前端补 {@code /admin/quotas}
 * 作用域声明后才真正连通。</p>
 */
@RestController
@RequestMapping("/api/v1/admin/quotas")
@RequiredArgsConstructor
public class AdminQuotaController {

    private final TenantQuotaMapper quotaMapper;
    private final ResourceTenantGuard guard;

    /**
     * 解析本次请求应作用的租户。
     *
     * <p>带了 {@code tenantId} → 严格校验（租户管理员传非本租户 404；平台管理员传不存在/停用租户 404）；
     * 没带 → 回落为登录账号自身租户（保持既有口径，见 {@link ResourceTenantGuard#resolveTenantOrOwn}）。</p>
     */
    private Long tenantOf(AuthUser actor, Long tenantId) {
        return guard.resolveTenantOrOwn(actor, tenantId);
    }

    @GetMapping
    public ApiResponse<Map<String, Object>> overview(
            @RequestParam(name = "tenantId", required = false) Long tenantId) {
        AuthUser actor = guard.requireTenantAdmin();
        Long tid = tenantOf(actor, tenantId);
        List<Map<String, Object>> users = quotaMapper.selectTenantQuotaOverview(tid);
        long totalQuota = users.stream().mapToLong(u -> num(u.get("quotaTokens"))).sum();
        long totalUsed = users.stream().mapToLong(u -> num(u.get("usedTokens"))).sum();
        long totalFree = users.stream().mapToLong(u -> num(u.get("freeTokens"))).sum();
        Map<String, Object> data = new LinkedHashMap<>();
        // 回执带上「实际作用的租户」：前端可据此核对「当前展示的是哪个租户」，
        // 免得出现「切换器显示 A、数据其实是 B」这类只有肉眼能发现的错位（铁律 #1）。
        data.put("tenantId", tid);
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
                                                   @RequestParam(name = "tenantId", required = false) Long tenantId,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser actor = guard.requireTenantAdmin();
        Long tid = tenantOf(actor, tenantId);
        long quota = num(body.get("quotaTokens"));
        if (quota < 0) {
            throw BizException.badRequest("配额不能为负数");
        }
        if (quota > 1_000_000_000L) {
            throw BizException.badRequest("单成员配额上限 10 亿词元");
        }
        TenantQuota row = quotaMapper.selectOne(new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<TenantQuota>()
                .eq(TenantQuota::getTenantId, tid)
                .eq(TenantQuota::getUserId, userId)
                .last("limit 1"));
        if (row == null) {
            row = new TenantQuota();
            row.setTenantId(tid);
            row.setUserId(userId);
            row.setQuotaTokens(quota);
            row.setUsedTokens(0L);
            row.setFreeTokens(0L);
            row.setCreatedAt(LocalDateTime.now());
            row.setCreatedBy(actor.getUserId());
        } else {
            row.setQuotaTokens(quota);
        }
        row.setUpdatedAt(LocalDateTime.now());
        if (row.getId() == null) {
            quotaMapper.insert(row);
        } else {
            quotaMapper.updateById(row);
        }
        return ApiResponse.ok(Map.of("tenantId", tid, "userId", userId, "quotaTokens", quota));
    }

    @GetMapping("/usage")
    public ApiResponse<Map<String, Object>> usage(
            @RequestParam(name = "days", defaultValue = "30") int days,
            @RequestParam(name = "tenantId", required = false) Long tenantId) {
        AuthUser actor = guard.requireTenantAdmin();
        Long tid = tenantOf(actor, tenantId);
        LocalDateTime since = LocalDate.now().minusDays(Math.max(1, Math.min(days, 365))).atStartOfDay();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("tenantId", tid);
        data.put("since", since.toLocalDate().toString());
        data.put("byBizType", quotaMapper.selectUsageByBizType(tid, since));
        data.put("recentLedger", quotaMapper.selectRecentLedger(tid, 20));
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
