package cn.aios.resource.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.common.exception.BizException;
import cn.aios.resource.entity.WorkerCapability;
import cn.aios.resource.service.WorkerCapabilityService;
import cn.aios.resource.service.WorkerCapabilityService.CapabilitySave;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import cn.aios.security.PermissionCatalog;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 数字人能力声明控制器（docs/52 P1/P3）。
 *
 * <pre>
 *   GET  /api/v1/workers/{id}/capabilities    列能力（worker:capability）
 *   PUT  /api/v1/workers/{id}/capabilities    批量保存（worker:capability，先软删后插）
 * </pre>
 *
 * <p>判定只在此处做：不在 WorkerController 里重复实现能力判定。</p>
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class WorkerCapabilityController {

    private final WorkerCapabilityService capabilityService;

    @GetMapping("/workers/{id}/capabilities")
    public ApiResponse<List<WorkerCapability>> list(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        requireCapability(user, "查看数字人能力");
        return ApiResponse.ok(capabilityService.listByWorker(id));
    }

    @PutMapping("/workers/{id}/capabilities")
    public ApiResponse<List<WorkerCapability>> save(@PathVariable Long id,
                                                   @RequestBody List<CapabilitySave> items) {
        AuthUser user = AuthUserContext.require();
        requireCapability(user, "编排数字人能力");
        capabilityService.saveBatch(user.getTenantId(), id, items, user.getUserId());
        return ApiResponse.ok(capabilityService.listByWorker(id));
    }

    private static void requireCapability(AuthUser user, String action) {
        if (!PermissionCatalog.holds(user, PermissionCatalog.WORKER_CAPABILITY)) {
            throw BizException.forbidden(action + "需要权限（" + PermissionCatalog.rolesText(PermissionCatalog.WORKER_CAPABILITY)
                    + "）；当前账号角色为「" + roleText(user) + "」。数字人能力编排属管理配置，请联系本租户管理员。");
        }
    }

    private static String roleText(AuthUser user) {
        return user.getRoles() == null || user.getRoles().isEmpty() ? "无角色"
                : String.join("、", user.getRoles());
    }
}
