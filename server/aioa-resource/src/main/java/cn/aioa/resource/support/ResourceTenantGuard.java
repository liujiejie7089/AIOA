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
 * aioa-resource 模块的<b>租户作用域守卫</b>（aioa-resource 不依赖 aioa-org，无法用 OrgGuard）。
 *
 * <p>首用者是消息中心（通道配置 / 投递记录）；2026-09-28 起配额管理（{@code /admin/quotas}）
 * 复用同一实现。「谁是租户级管理员」「跨租户怎么判」在这一处判定，不再各控制器各写一份
 * —— 与 docs/37 §S3「把谁吃 tenantId 写成接口侧声明」同一方向。</p>
 *
 * <ul>
 *   <li>{@link #requireTenantAdmin()}：仅 {@code ROLE_ADMIN}/{@code ROLE_TENANT_ADMIN}
 *       （即 {@link PermissionCatalog#isAdmin}）可执行。</li>
 *   <li>{@link #resolveTenant}（严格）：租户管理员硬绑定本租户；平台管理员须经 {@code ?tenantId=}
 *       指定，且校验租户存在并启用（跨租户一律 404，不泄露存在性）。</li>
 *   <li>{@link #resolveTenantOrOwn}（宽松）：未指定时回落为登录账号自身租户。仅用于那些
 *       「不带 tenantId 也有明确历史语义」的端点，见该方法的注释。</li>
 * </ul>
 */
@Component
@RequiredArgsConstructor
public class ResourceTenantGuard {

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
     * 解析本次请求应作用的租户（严格）。
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

    /**
     * 解析本次请求应作用的租户（宽松）：{@code requested == null} 时回落为登录账号自身租户。
     *
     * <p><b>为什么需要这个变体</b>：配额管理（{@code /admin/quotas*}）在支持「切换租户」之前，
     * 平台管理员不带 {@code tenantId} 时看到的是**自己所属租户**（tenant 0）的成员配额 —— 这是
     * 既有口径，且 `scripts/e2e_full_system.py` 的 S8-14 正是这样调的。若直接换成
     * {@link #resolveTenant}，该套件会从 200 变 400（判据变化却无迁移，属"改口径不回头看"）。
     * 故：**带了就按跨租户严格校验，没带就保持原语义**；调用方（前端）始终会带上当前租户。</p>
     */
    public Long resolveTenantOrOwn(AuthUser u, Long requested) {
        if (requested == null) {
            return u.getTenantId() == null ? 0L : u.getTenantId();
        }
        return resolveTenant(u, requested);
    }
}
