package cn.aios.resource.connector.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.connector.service.ConnectorTenantConfigService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 租户级连接器配置管理端 API（管理员）。对齐 {@code /api/v1/admin/models} 模式：
 * URL 前缀 /api/v1/admin，方法内手动守卫 {@code ROLE_ADMIN || ROLE_TENANT_ADMIN}。
 *
 * <pre>
 *   GET    /api/v1/admin/connector-configs        可配置连接器清单（新增连接器无需改前端）
 *   GET    /api/v1/admin/connector-configs/{code}   掩码视图（绝不回明文密钥）
 *   PUT    /api/v1/admin/connector-configs/{code}   保存（掩码值/空 = 保留旧值）
 *   DELETE /api/v1/admin/connector-configs/{code}   清除（逻辑删，卡片回「待管理员配置」）
 * </pre>
 *
 * <p>凭据的<b>权威存储是 mcp-hub</b>（工具在那里跑）；本控制器把调用者的 Authorization
 * 原样转给 hub，hub 再回 {@code /api/v1/auth/me} 判身份与角色 —— Java 仍是唯一身份权威，
 * 不引入新的服务间密钥。</p>
 */
@RestController
@RequestMapping("/api/v1/admin/connector-configs")
@RequiredArgsConstructor
public class ConnectorTenantConfigController {

    private final ConnectorTenantConfigService service;

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization) {
        AuthUser admin = requireAdmin();
        return ApiResponse.ok(service.list(admin.getTenantId(), authorization));
    }

    @GetMapping("/{code}")
    public ApiResponse<Map<String, Object>> get(
            @PathVariable String code,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization) {
        AuthUser admin = requireAdmin();
        return ApiResponse.ok(service.view(admin.getTenantId(), code, authorization));
    }

    @PutMapping("/{code}")
    public ApiResponse<Map<String, Object>> put(
            @PathVariable String code,
            @RequestBody ConfigBody body,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization) {
        AuthUser admin = requireAdmin();
        Map<String, String> v = body == null || body.values() == null ? Map.of() : body.values();
        // schema 驱动：字段集合来自 connector_def.config_keys，控制器不认识任何具体字段名
        return ApiResponse.ok(service.upsertValues(admin.getTenantId(), admin.getUserId(), code, v,
                body == null ? null : body.enabled(), authorization));
    }

    @DeleteMapping("/{code}")
    public ApiResponse<Map<String, String>> delete(
            @PathVariable String code,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization) {
        AuthUser admin = requireAdmin();
        service.clear(admin.getTenantId(), code, authorization);
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
