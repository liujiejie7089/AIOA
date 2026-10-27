package cn.aios.resource.connector.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.service.ConnectorTenantConfigService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 租户级连接器配置管理端 API（管理员）。对齐 {@code /api/v1/admin/models} 模式：
 * URL 前缀 /api/v1/admin，方法内手动守卫 {@code ROLE_ADMIN || ROLE_TENANT_ADMIN}。
 *
 * <pre>
 *   GET    /api/v1/admin/connector-configs/{code}   掩码视图（绝不回明文密钥）
 *   PUT    /api/v1/admin/connector-configs/{code}   保存（掩码值/空 = 保留旧值）
 *   DELETE /api/v1/admin/connector-configs/{code}   清除（逻辑删，卡片回「待管理员配置」）
 * </pre>
 *
 * <p>保存成功后用户端 {@code configReady} 即刻为 true（{@code resolveWeCom} 租户级优先），
 * H5 卡片从「待管理员配置」变为「未连接」，可发起 OAuth。</p>
 */
@RestController
@RequestMapping("/api/v1/admin/connector-configs")
@RequiredArgsConstructor
public class ConnectorTenantConfigController {

    private final ConnectorTenantConfigService service;

    @GetMapping("/{code}")
    public ApiResponse<Map<String, Object>> get(@PathVariable String code) {
        AuthUser admin = requireAdmin();
        return ApiResponse.ok(service.view(admin.getTenantId(), code));
    }

    @PutMapping("/{code}")
    public ApiResponse<Map<String, Object>> put(@PathVariable String code,
                                                @RequestBody ConfigBody body) {
        AuthUser admin = requireAdmin();
        Map<String, String> v = body == null || body.values() == null ? Map.of() : body.values();
        return ApiResponse.ok(service.upsert(admin.getTenantId(), admin.getUserId(), code,
                v.get("corpId"), v.get("agentId"), v.get("corpSecret"), body == null ? null : body.enabled()));
    }

    @DeleteMapping("/{code}")
    public ApiResponse<Map<String, String>> delete(@PathVariable String code) {
        AuthUser admin = requireAdmin();
        service.clear(admin.getTenantId(), code);
        return ApiResponse.ok(Map.of("status", "CLEARED"));
    }

    private static AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN") && !user.getRoles().contains("ROLE_TENANT_ADMIN")) {
            throw BizException.forbidden("需要管理员角色");
        }
        return user;
    }

    public record ConfigBody(Map<String, String> values, Boolean enabled) {
    }
}
