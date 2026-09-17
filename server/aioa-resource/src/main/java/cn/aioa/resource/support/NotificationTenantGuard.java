package cn.aioa.resource.support;

import cn.aioa.common.exception.BizException;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.PermissionCatalog;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 消息中心接口的作用域守卫（aioa-resource 不依赖 aioa-org，无法用 OrgGuard）。
 *
 * <p>与 OrgGuard 的同名语义对齐：</p>
 * <ul>
 *   <li>{@link #requireTenantAdmin()}：仅 {@code ROLE_ADMIN}/{@code ROLE_TENANT_ADMIN}
 *       （即 {@link PermissionCatalog#isAdmin}）可执行。</li>
 *   <li>{@link #resolveTenant}：租户管理员硬绑定本租户；平台管理员须经 {@code ?tenantId=}
 *       指定，且校验租户存在并启用（跨租户一律 404，不泄露存在性）。</li>
 * </ul>
 */
@Component
@RequiredArgsConstructor
public class NotificationTenantGuard {

    private final JdbcTemplate jdbc;

    /** 当前用户须为租户级管理员（含系统管理员），否则 403。 */
    public AuthUser requireTenantAdmin() {
        AuthUser u = AuthUserContext.require();
        if (!PermissionCatalog.isAdmin(u)) {
            throw BizException.forbidden("仅租户管理员可执行该操作");
        }
        return u;
    }

    /**
     * 解析本次请求应作用的租户。
     *
     * @param requested 显式请求的租户 id（平台管理员切换租户用，可空）
     * @return 实际作用租户 id
     */
    public Long resolveTenant(AuthUser u, Long requested) {
        if (PermissionCatalog.hasRole(u, PermissionCatalog.ROLE_TENANT_ADMIN)
                && !PermissionCatalog.isPlatformAdmin(u)) {
            Long own = u.getTenantId() == null ? 0L : u.getTenantId();
            if (requested != null && !requested.equals(own)) {
                throw BizException.notFound("租户不存在或无权访问：" + requested);
            }
            return own;
        }
        if (PermissionCatalog.isPlatformAdmin(u)) {
            if (requested == null) {
                throw BizException.badRequest("平台管理员需指定 tenantId 参数");
            }
            List<Long> ids = jdbc.queryForList(
                    "SELECT id FROM sys_tenant WHERE id = ? AND status = 'ENABLED' AND deleted_at IS NULL",
                    Long.class, requested);
            if (ids.isEmpty()) {
                throw BizException.notFound("租户不存在或已停用：" + requested);
            }
            return requested;
        }
        throw BizException.forbidden("仅租户管理员可执行该操作");
    }
}
