package cn.aioa.org.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.service.OnboardingService;
import cn.aioa.org.service.OrgTreeService;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 企业入驻向导（8 步闭环编排）。
 *
 * <p>逐步可校验、可推进；每步门禁失败时返回**具体原因**，便于企业端/租户端自助排查。</p>
 */
@RestController
@RequestMapping("/api/v1/tenant/onboarding")
@RequiredArgsConstructor
public class OnboardingController {

    private final OrgGuard guard;
    private final OnboardingService onboardingService;

    /** 租户端入驻总览：本租户全部机构的入驻进度。 */
    @GetMapping
    public ApiResponse<Map<String, Object>> overview() {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(onboardingService.overview(guard.resolveRequestTenant(u)));
    }

    /** 单机构 8 步进度与阻塞原因。 */
    @GetMapping("/{institutionId}/progress")
    public ApiResponse<Map<String, Object>> progress(@PathVariable Long institutionId) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(onboardingService.progress(
                guard.resolveRequestTenant(u), institutionId));
    }

    /** 推进指定步骤（仅当门禁通过）。 */
    @PostMapping("/{institutionId}/step")
    public ApiResponse<Map<String, Object>> advance(@PathVariable Long institutionId,
                                                    @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Integer step = body == null ? null : Integer.valueOf(Vals.integer(body, "step", 0));
        return ApiResponse.ok(onboardingService.advance(
                guard.resolveRequestTenant(u), institutionId, step == 0 ? null : step, u));
    }

    /** 一键推进：逐级校验，遇到未通过门禁即停止并说明原因。 */
    @PostMapping("/{institutionId}/advance-all")
    public ApiResponse<Map<String, Object>> advanceAll(@PathVariable Long institutionId) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(onboardingService.advanceAll(
                guard.resolveRequestTenant(u), institutionId, u));
    }

    /** 步骤定义（前端向导文案，避免前后端硬编码不一致）。 */
    @GetMapping("/steps")
    public ApiResponse<Map<String, Object>> steps() {
        guard.requireTenantAdmin();
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("totalSteps", OnboardingService.TOTAL_STEPS);
        m.put("maxDeptDepth", OrgTreeService.MAX_DEPTH);
        m.put("note", "前 4 步租户端、5~7 步企业端、第 8 步回租户层（规格书第三章主链路）");
        m.put("owners", java.util.List.of(
                Map.of("scope", "租户管理员端", "steps", java.util.List.of(1, 2, 3, 4, 8)),
                Map.of("scope", "企业管理员端", "steps", java.util.List.of(5, 6)),
                Map.of("scope", "个人端", "steps", java.util.List.of(7))));
        return ApiResponse.ok(m);
    }
}
