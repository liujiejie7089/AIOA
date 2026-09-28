package cn.aioa.org.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.service.QuotaService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.PermissionCatalog;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 平台管理员「调整某个租户的资源上限」（V66 / docs/38 批次 A）。
 *
 * <p><b>为什么这个端点在 aioa-org 而不是平台租户控制器所在的 aioa-admin</b>：
 * 资源池的写入口径（总量不得低于已分配量、要写分配流水、要留审计前后值）已经在
 * {@link QuotaService#upsertPool} 里实现了。若为了「路径好看」在 aioa-admin 重写一遍，
 * 就变成同一判定点两处实现 —— 本项目最常复现的缺陷形态（docs/37 §6 就是它）。
 * 路径前缀 {@code /api/v1/admin/tenants} 与 aioa-admin 的 {@code TenantController} 并存不冲突：
 * 两者映射的 (方法, 路径) 无交集。</p>
 *
 * <p><b>权限</b>：仅平台管理员。租户管理员不得调整租户资源上限 —— 那是平台的分配权。</p>
 */
@RestController
@RequestMapping("/api/v1/admin/tenants")
@RequiredArgsConstructor
public class PlatformTenantQuotaController {

    private final OrgStatMapper statMapper;
    private final QuotaService quotaService;

    /**
     * body: {@code { period?, tokenTotal?, expertSeats?, skillSeats?, warnThreshold?, expireAt? }}
     *
     * <p>回执含 {@code before / after}，前端可以展示「调整前 → 调整后」。</p>
     */
    @PutMapping("/{id}/quota")
    public ApiResponse<Map<String, Object>> updateQuota(@PathVariable("id") Long tenantId,
                                                        @RequestBody Map<String, Object> body) {
        AuthUser actor = AuthUserContext.require();
        if (!PermissionCatalog.isPlatformAdmin(actor)) {
            throw BizException.forbidden("调整租户资源上限仅平台管理员可执行");
        }
        Map<String, Object> tenant = statMapper.selectTenantWithHierarchy(tenantId);
        if (tenant == null) {
            throw BizException.notFound("租户不存在：" + tenantId);
        }
        Map<String, Object> req = body == null ? Map.of() : body;
        String period = req.get("period") == null || String.valueOf(req.get("period")).isBlank()
                ? null : String.valueOf(req.get("period"));
        String p = period == null ? cn.aioa.org.support.Vals.nowPeriod() : period;
        Map<String, Object> before = quotaService.pool(tenantId, p);
        Map<String, Object> after = quotaService.upsertPool(tenantId, actor, req);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", tenantId);
        out.put("tenantName", tenant.get("name"));
        out.put("period", p);
        out.put("before", before);
        out.put("after", after);
        return ApiResponse.ok(out);
    }
}
