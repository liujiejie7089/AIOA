package cn.aioa.admin.service;

import cn.aioa.admin.entity.SysLoginLog;
import cn.aioa.admin.entity.SysPermission;
import cn.aioa.admin.entity.SysRole;
import cn.aioa.admin.entity.SysRolePermission;
import cn.aioa.admin.entity.SysTenant;
import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.entity.SysUserRole;
import cn.aioa.admin.mapper.SysLoginLogMapper;
import cn.aioa.admin.mapper.SysPermissionMapper;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysRolePermissionMapper;
import cn.aioa.admin.mapper.SysTenantMapper;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.admin.mapper.SysUserRoleMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import cn.aioa.security.JwtTokenProvider;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.jsonwebtoken.Claims;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 登录 / 刷新 / 当前用户。M1 自建账号体系；M3 预留 OAuth2/LDAP（AuthProvider 接口化）。
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    private final SysUserMapper userMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final SysRoleMapper roleMapper;
    private final SysRolePermissionMapper rolePermissionMapper;
    private final SysPermissionMapper permissionMapper;
    private final SysLoginLogMapper loginLogMapper;
    private final SysTenantMapper tenantMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;
    /** 跨模块读取 org_member / org_institution（V24 企业入驻域），用原生 SQL 避免模块耦合。 */
    private final org.springframework.jdbc.core.JdbcTemplate jdbc;

    public AuthService(SysUserMapper userMapper, SysUserRoleMapper userRoleMapper,
                       SysRoleMapper roleMapper, SysRolePermissionMapper rolePermissionMapper,
                       SysPermissionMapper permissionMapper, SysLoginLogMapper loginLogMapper,
                       SysTenantMapper tenantMapper,
                       PasswordEncoder passwordEncoder, JwtTokenProvider jwtTokenProvider,
                       org.springframework.jdbc.core.JdbcTemplate jdbc) {
        this.userMapper = userMapper;
        this.userRoleMapper = userRoleMapper;
        this.roleMapper = roleMapper;
        this.rolePermissionMapper = rolePermissionMapper;
        this.permissionMapper = permissionMapper;
        this.loginLogMapper = loginLogMapper;
        this.tenantMapper = tenantMapper;
        this.passwordEncoder = passwordEncoder;
        this.jwtTokenProvider = jwtTokenProvider;
        this.jdbc = jdbc;
    }

    public record LoginData(String accessToken, String refreshToken, long expiresIn, UserBrief user) {
    }

    /**
     * 登录返回的用户摘要。
     *
     * <p>tenantId / institutionId 是前端的数据锚点：没有它，前端无法判断当前账号属于哪个租户/机构，
     * 个人信息页只能显示「租户 ID —」，也无法按租户过滤数据。市面通行做法是在 /me 与登录响应中
     * 一并下发主体归属，前端不再另行反查。</p>
     */
    public record UserBrief(long id, String username, String nickname, List<String> roles,
                            long tenantId, String tenantName, Long institutionId, String institutionName) {
    }

    public LoginData login(String username, String password, String ip, String ua) {
        SysUser user = userMapper.selectOne(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, username));
        if (user == null || !passwordEncoder.matches(password, user.getPasswordHash())) {
            loginLog(null, ip, ua, false, "用户名或密码错误");
            throw new BizException(1001, "用户名或密码错误");
        }
        String st = user.getStatus();
        if (st == null || (!"ENABLED".equals(st) && !"ACTIVE".equals(st))) {
            loginLog(user.getId(), ip, ua, false, "账号已禁用");
            throw new BizException(1002, "账号已禁用");
        }
        List<String> roles = roleCodesOf(user.getId());
        AuthUser auth = toAuthUser(user, roles);
        String access = jwtTokenProvider.generateAccessToken(auth);
        String refresh = jwtTokenProvider.generateRefreshToken(auth);
        user.setLastLoginAt(LocalDateTime.now());
        userMapper.updateById(user);
        loginLog(user.getId(), ip, ua, true, null);
        return new LoginData(access, refresh, jwtTokenProvider.accessTtlSeconds(),
                new UserBrief(user.getId(), user.getUsername(), user.getNickname(), roles,
                        user.getTenantId() == null ? 0L : user.getTenantId(),
                        tenantNameOf(user.getTenantId()),
                        institutionIdOf(user.getId()), institutionNameOf(user.getId())));
    }

    public String refresh(String refreshToken) {
        Claims claims;
        try {
            claims = jwtTokenProvider.parse(refreshToken);
        } catch (Exception e) {
            throw new BizException(1003, "refreshToken 无效或已过期");
        }
        if (!JwtTokenProvider.TYPE_REFRESH.equals(claims.get(JwtTokenProvider.CLAIM_TYPE, String.class))) {
            throw new BizException(1003, "令牌类型错误");
        }
        SysUser user = userMapper.selectOne(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, claims.getSubject()));
        if (user == null) {
            throw new BizException(1003, "用户不存在");
        }
        List<String> roles = roleCodesOf(user.getId());
        return jwtTokenProvider.generateAccessToken(toAuthUser(user, roles));
    }

    public record MeData(long id, String username, String nickname, List<String> roles,
                         List<String> permissions, long tenantId, String tenantName,
                         Long institutionId, String institutionName) {
    }

    public MeData me() {
        AuthUser auth = AuthUserContext.get();
        if (auth == null) {
            throw new BizException(401, "未登录");
        }
        List<String> roles = roleCodesOf(auth.getUserId());
        List<String> permissions = permCodesOfUser(auth.getUserId());
        long tenantId = auth.getTenantId() == null ? 0L : auth.getTenantId();
        return new MeData(auth.getUserId(), auth.getUsername(), auth.getNickname(), roles, permissions,
                tenantId, tenantNameOf(tenantId), institutionIdOf(auth.getUserId()),
                institutionNameOf(auth.getUserId()));
    }

    private String tenantNameOf(Long tenantId) {
        if (tenantId == null || tenantId == 0L) {
            return null;
        }
        try {
            SysTenant t = tenantMapper.selectById(tenantId);
            return t == null ? null : t.getName();
        } catch (Exception e) {
            return null;
        }
    }

    /** 机构锚点：从 org_member 解析（V24 企业入驻域）。未加入任何机构返回 null。 */
    private Long institutionIdOf(Long userId) {
        try {
            List<Long> rows = jdbc.queryForList(
                    "SELECT institution_id FROM org_member WHERE user_id = ? AND status = 'ACTIVE' "
                            + "AND deleted_at IS NULL ORDER BY id LIMIT 1", Long.class, userId);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    private String institutionNameOf(Long userId) {
        Long iid = institutionIdOf(userId);
        if (iid == null) {
            return null;
        }
        try {
            List<String> rows = jdbc.queryForList(
                    "SELECT name FROM org_institution WHERE id = ? AND deleted_at IS NULL",
                    String.class, iid);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    public List<String> roleCodesOf(Long userId) {
        List<Long> roleIds = userRoleMapper.selectList(
                        new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, userId))
                .stream().map(SysUserRole::getRoleId).toList();
        if (roleIds.isEmpty()) {
            return List.of();
        }
        return roleMapper.selectBatchIds(roleIds).stream().map(SysRole::getRoleCode).toList();
    }

    public List<String> permCodesOfUser(Long userId) {
        List<Long> roleIds = userRoleMapper.selectList(
                        new LambdaQueryWrapper<SysUserRole>().eq(SysUserRole::getUserId, userId))
                .stream().map(SysUserRole::getRoleId).toList();
        if (roleIds.isEmpty()) {
            return List.of();
        }
        List<Long> permIds = rolePermissionMapper.selectList(
                        new LambdaQueryWrapper<SysRolePermission>().in(SysRolePermission::getRoleId, roleIds))
                .stream().map(SysRolePermission::getPermId).distinct().toList();
        if (permIds.isEmpty()) {
            return List.of();
        }
        return permissionMapper.selectBatchIds(permIds).stream().map(SysPermission::getPermCode).toList();
    }

    private AuthUser toAuthUser(SysUser user, List<String> roles) {
        // 机构/部门锚点：专家配置的 INSTITUTION / DEPT 层覆盖规则依赖它，
        // 登录时一次性解析进上下文，避免每次解析配置都回查。
        Long institutionId = institutionIdOf(user.getId());
        return AuthUser.builder()
                .userId(user.getId())
                .tenantId(user.getTenantId() == null ? 0L : user.getTenantId())
                .institutionId(institutionId)
                .departmentId(departmentIdOf(user.getId()))
                .username(user.getUsername())
                .nickname(user.getNickname())
                .roles(roles == null ? List.of() : roles)
                .permissions(List.of())
                .build();
    }

    private Long departmentIdOf(Long userId) {
        try {
            List<Long> rows = jdbc.queryForList(
                    "SELECT department_id FROM org_member WHERE user_id = ? AND status = 'ACTIVE' "
                            + "AND deleted_at IS NULL ORDER BY id LIMIT 1", Long.class, userId);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    private void loginLog(Long userId, String ip, String ua, boolean ok, String failReason) {
        try {
            SysLoginLog entry = new SysLoginLog();
            entry.setUserId(userId);
            entry.setIp(ip);
            entry.setUa(ua == null || ua.length() > 512 ? (ua == null ? null : ua.substring(0, 512)) : ua);
            entry.setResult(ok);
            entry.setFailReason(failReason);
            entry.setLoginAt(LocalDateTime.now());
            loginLogMapper.insert(entry);
        } catch (Exception e) {
            log.warn("login log persist failed: {}", e.getMessage());
        }
    }
}
