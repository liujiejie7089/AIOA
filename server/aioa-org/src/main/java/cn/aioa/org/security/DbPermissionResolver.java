package cn.aioa.org.security;

import cn.aioa.org.service.PermissionGrantService;
import cn.aioa.security.PermissionResolver;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 数据库实时权限码解析（V36 需求①）：给 {@code JwtAuthenticationFilter} 提供
 * 「角色内置权限 ∪ 已发放授权」的并集。
 *
 * <p><b>两处来源</b>：</p>
 * <ol>
 *   <li>{@code sys_role_permission} —— 角色静态配置（管理端可维护）；</li>
 *   <li>{@code permission_grant} 中 {@code status='ACTIVE'} 且未过期 / 未回收的行
 *       —— 由权限申请审批链路的终态回调写入。</li>
 * </ol>
 *
 * <p><b>为什么不放 aioa-admin</b>（与 {@code DbRoleResolver} 同处）：授权表的 mapper 属于审批域
 * （{@code aioa-org}），而 {@code aioa-admin} 不依赖 {@code aioa-org}（兄弟模块）。
 * 放在 org 侧只需依赖 {@code aioa-security}，两端都满足，且不需要引入反向依赖。</p>
 *
 * <p><b>失败语义</b>：本接口不承担认证否决 —— 任何异常都吞掉并返回已有部分，
 * 让认证继续走「角色判定」这条兼容路径（与 {@code DbRoleResolver} 返回 null 即拒绝的语义不同）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DbPermissionResolver implements PermissionResolver {

    private final JdbcTemplate jdbc;
    private final PermissionGrantService grantService;

    @Override
    public List<String> permissionsOf(Long userId) {
        List<String> out = new ArrayList<>(rolePermissionsOf(userId));
        try {
            for (String code : grantService.activePermissionsOf(userId)) {
                if (!out.contains(code)) {
                    out.add(code);
                }
            }
        } catch (Exception e) {
            // 授权表尚未迁移完成时也不能让认证崩掉：退回角色权限
            log.warn("resolve granted permissions failed: userId={} err={}", userId, e.getMessage());
        }
        return out;
    }

    /** 角色内置权限：sys_user_role → sys_role_permission → sys_permission.perm_code。 */
    private List<String> rolePermissionsOf(Long userId) {
        if (userId == null) {
            return List.of();
        }
        try {
            return jdbc.queryForList(
                    "SELECT DISTINCT p.perm_code FROM sys_user_role ur "
                            + "JOIN sys_role_permission rp ON rp.role_id = ur.role_id "
                            + "JOIN sys_permission p ON p.id = rp.perm_id "
                            + "WHERE ur.user_id = ?", String.class, userId);
        } catch (Exception e) {
            log.warn("resolve role permissions failed: userId={} err={}", userId, e.getMessage());
            return List.of();
        }
    }
}
