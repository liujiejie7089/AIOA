package cn.aioa.admin.security;

import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.admin.service.AuthService;
import cn.aioa.security.RoleResolver;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 数据库实时角色解析：给 JwtAuthenticationFilter 提供当前角色，
 * 使管理端「分配角色 / 停用账号」后无需重新登录即可生效。
 * 约定：用户不存在或已停用（DISABLED）时返回 null，过滤器将拒绝该次认证。
 */
@Component
@RequiredArgsConstructor
public class DbRoleResolver implements RoleResolver {

    private final AuthService authService;
    private final SysUserMapper userMapper;

    @Override
    public List<String> rolesOf(Long userId) {
        if (userId == null) {
            return List.of();
        }
        SysUser user = userMapper.selectById(userId);
        if (user == null || "DISABLED".equals(user.getStatus())) {
            return null; // 停用/不存在 → 过滤器拒绝认证
        }
        return authService.roleCodesOf(userId);
    }
}
