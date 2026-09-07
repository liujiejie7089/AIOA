package cn.aioa.admin.service;

import cn.aioa.admin.entity.SysLoginLog;
import cn.aioa.admin.entity.SysPermission;
import cn.aioa.admin.entity.SysRole;
import cn.aioa.admin.entity.SysRolePermission;
import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.entity.SysUserRole;
import cn.aioa.admin.mapper.SysLoginLogMapper;
import cn.aioa.admin.mapper.SysPermissionMapper;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysRolePermissionMapper;
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
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;

    public AuthService(SysUserMapper userMapper, SysUserRoleMapper userRoleMapper,
                       SysRoleMapper roleMapper, SysRolePermissionMapper rolePermissionMapper,
                       SysPermissionMapper permissionMapper, SysLoginLogMapper loginLogMapper,
                       PasswordEncoder passwordEncoder, JwtTokenProvider jwtTokenProvider) {
        this.userMapper = userMapper;
        this.userRoleMapper = userRoleMapper;
        this.roleMapper = roleMapper;
        this.rolePermissionMapper = rolePermissionMapper;
        this.permissionMapper = permissionMapper;
        this.loginLogMapper = loginLogMapper;
        this.passwordEncoder = passwordEncoder;
        this.jwtTokenProvider = jwtTokenProvider;
    }

    public record LoginData(String accessToken, String refreshToken, long expiresIn, UserBrief user) {
    }

    public record UserBrief(long id, String username, String nickname, List<String> roles) {
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
                new UserBrief(user.getId(), user.getUsername(), user.getNickname(), roles));
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

    public record MeData(long id, String username, String nickname, List<String> roles, List<String> permissions) {
    }

    public MeData me() {
        AuthUser auth = AuthUserContext.get();
        if (auth == null) {
            throw new BizException(401, "未登录");
        }
        List<String> roles = roleCodesOf(auth.getUserId());
        List<String> permissions = permCodesOfUser(auth.getUserId());
        return new MeData(auth.getUserId(), auth.getUsername(), auth.getNickname(), roles, permissions);
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
        return AuthUser.builder()
                .userId(user.getId())
                .tenantId(user.getTenantId() == null ? 0L : user.getTenantId())
                .username(user.getUsername())
                .nickname(user.getNickname())
                .roles(roles == null ? List.of() : roles)
                .permissions(List.of())
                .build();
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
