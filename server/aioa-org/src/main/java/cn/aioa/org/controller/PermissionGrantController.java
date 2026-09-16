package cn.aioa.org.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.service.PermissionGrantService;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 权限申请与审批（V36 需求①）。
 *
 * <pre>
 * GET  /api/v1/org/permissions/catalog         —— 可申请权限目录（含我是否持有 / 是否在途）
 * GET  /api/v1/org/permissions/holdings        —— 我已生效的权限（标注来源：角色 / 授权）
 * GET  /api/v1/org/permissions/mine            —— 我的权限申请（含流转路径）
 * POST /api/v1/org/permissions/apply           —— 提交申请（body: {permissionCode, targetWorkerType, reason}）
 * POST /api/v1/org/permissions/{id}/revoke     —— 回收授权（本人或租户管理员）
 * GET  /api/v1/org/permissions/pending         —— 本租户 / 本单位的授权单（租户管理员 / 企业管理员）
 * </pre>
 *
 * <p>「通过 AI 提交申请」走工具网关 {@code apply_permission}（{@code PermissionGrantToolHandler}），
 * 最终落到同一个 {@link PermissionGrantService#apply}，两条入口共用一套校验，
 * 不会出现「AI 能绕开规则」的口径分裂。</p>
 */
@RestController
@RequestMapping("/api/v1/org/permissions")
@RequiredArgsConstructor
public class PermissionGrantController {

    private final PermissionGrantService grantService;
    private final OrgGuard guard;

    /** 申请页数据源：哪些权限可申请、我是否已持有、是否有在途申请。 */
    @GetMapping("/catalog")
    public ApiResponse<Map<String, Object>> catalog() {
        AuthUser user = guard.user();
        return ApiResponse.ok(grantService.catalog(user));
    }

    /** 我持有的权限（角色内置 + 授权发放），用于「我的权限」页。 */
    @GetMapping("/holdings")
    public ApiResponse<List<Map<String, Object>>> holdings() {
        AuthUser user = guard.user();
        return ApiResponse.ok(grantService.holdings(user));
    }

    /** 我的权限申请（含审批流转路径，用户端「我的申请」直接复用）。 */
    @GetMapping("/mine")
    public ApiResponse<List<Map<String, Object>>> mine() {
        AuthUser user = guard.user();
        return ApiResponse.ok(grantService.mine(user));
    }

    /** 提交权限申请：本地存档 → 部门审批 → 租户管理员发放。 */
    @PostMapping("/apply")
    public ApiResponse<Map<String, Object>> apply(@RequestBody PermissionGrantService.ApplyReq req) {
        AuthUser user = guard.user();
        Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        return ApiResponse.ok(grantService.apply(tenantId, user, req));
    }

    /** 回收授权：本人可撤销自己的；租户管理员可回收本租户的。 */
    @PostMapping("/{id}/revoke")
    public ApiResponse<Map<String, Object>> revoke(@PathVariable("id") Long id) {
        AuthUser user = guard.user();
        return ApiResponse.ok(grantService.revoke(id, user));
    }

    /**
     * 本租户 / 本单位的授权单。
     *
     * <p>机构成员（企业管理员 / 部门负责人）只看本单位；租户管理员看本租户全部；
     * 平台管理员只读全量。机构维度即需求①的「存档至所在单位」在查询侧的兑现。</p>
     */
    @GetMapping("/pending")
    public ApiResponse<Map<String, Object>> pending(
            @RequestParam(value = "institutionId", required = false) Long institutionId) {
        AuthUser user = AuthUserGuard.requireAdminOrOrgUser(guard);
        Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        Long scopeInstitution;
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_ADMIN)) {
            // 平台管理员：全量只读，不做机构约束
            scopeInstitution = institutionId;
        } else if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)) {
            // 租户管理员：可切本租户机构；未指定则全租户
            scopeInstitution = institutionId;
        } else {
            // 机构成员：硬绑本单位，忽略入参（防探测）
            Long own = guard.resolveInstitutionId(user.getUserId());
            if (own == null) {
                throw BizException.forbidden("你未绑定任何机构，无法查看单位授权");
            }
            if (institutionId != null && !institutionId.equals(own)) {
                throw BizException.notFound("机构不存在或无权访问：" + institutionId);
            }
            scopeInstitution = own;
        }
        return ApiResponse.ok(grantService.pending(tenantId, user, scopeInstitution));
    }

    /** 内联守卫：避免再引一个类，同时把「谁能看列表」的口径集中在这里。 */
    private static final class AuthUserGuard {
        static AuthUser requireAdminOrOrgUser(OrgGuard guard) {
            AuthUser user = guard.user();
            if (OrgGuard.hasRole(user, OrgGuard.ROLE_ADMIN)
                    || OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)
                    || OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)
                    || OrgGuard.hasRole(user, OrgGuard.ROLE_DEPT_LEADER)) {
                return user;
            }
            throw BizException.forbidden("仅企业管理员、部门负责人或租户管理员可查看授权清单");
        }
    }
}
