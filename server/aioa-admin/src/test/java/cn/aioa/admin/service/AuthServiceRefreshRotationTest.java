package cn.aioa.admin.service;

import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.mapper.SysLoginLogMapper;
import cn.aioa.admin.mapper.SysPermissionMapper;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysRolePermissionMapper;
import cn.aioa.admin.mapper.SysTenantMapper;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.admin.mapper.SysUserRoleMapper;
import cn.aioa.admin.security.DbTokenRevocationChecker;
import cn.aioa.common.exception.BizException;
import cn.aioa.security.AuthUser;
import cn.aioa.security.JwtProperties;
import cn.aioa.security.JwtTokenProvider;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * H-7：refresh token 轮换 + 撤销旧 jti。
 *
 * <p>判据（可复跑）：用一张 refresh 成功刷新后，再用<b>同一张旧</b> refresh 刷新必须失败
 * （旧 jti 已被吊销）；而<b>新</b> refresh 仍可刷新。</p>
 *
 * <p>说明：本测试用 Mockito 桩掉 DB/映射依赖，复用真实 {@link JwtTokenProvider} 与既有
 * {@link DbTokenRevocationChecker} 接口（只是用内存 Set 模拟其写入/查询路径），
 * 验证的是轮换+吊销的业务逻辑，不依赖任何常驻服务。</p>
 */
class AuthServiceRefreshRotationTest {

    private JwtTokenProvider jwtTokenProvider;
    private DbTokenRevocationChecker revocationChecker;
    private AuthService authService;
    private Set<String> revoked;

    @BeforeEach
    void setUp() {
        JwtProperties props = new JwtProperties();
        props.setSecret("test-secret-needs-at-least-32-chars-abcdefghij");
        jwtTokenProvider = new JwtTokenProvider(props);

        revoked = ConcurrentHashMap.newKeySet();
        revocationChecker = Mockito.mock(DbTokenRevocationChecker.class);
        Mockito.when(revocationChecker.isRevoked(Mockito.anyString()))
                .thenAnswer(inv -> revoked.contains(inv.getArgument(0)));
        Mockito.when(revocationChecker.revoke(Mockito.any(), Mockito.any(), Mockito.any(),
                        Mockito.any(), Mockito.any()))
                .thenAnswer(inv -> {
                    String jti = inv.getArgument(0);
                    if (jti == null || jti.isBlank()) {
                        return false;
                    }
                    return revoked.add(jti);
                });

        SysUserMapper userMapper = Mockito.mock(SysUserMapper.class);
        SysUser user = new SysUser();
        ReflectionTestUtils.setField(user, "id", 1L);
        ReflectionTestUtils.setField(user, "username", "alice");
        ReflectionTestUtils.setField(user, "status", "ENABLED");
        ReflectionTestUtils.setField(user, "tenantId", 0L);
        Mockito.when(userMapper.selectOne(Mockito.any())).thenReturn(user);

        SysUserRoleMapper userRoleMapper = Mockito.mock(SysUserRoleMapper.class);
        Mockito.when(userRoleMapper.selectList(Mockito.any())).thenReturn(List.of());
        SysRoleMapper roleMapper = Mockito.mock(SysRoleMapper.class);
        Mockito.when(roleMapper.selectBatchIds(Mockito.any())).thenReturn(List.of());
        SysRolePermissionMapper rolePermissionMapper = Mockito.mock(SysRolePermissionMapper.class);
        SysPermissionMapper permissionMapper = Mockito.mock(SysPermissionMapper.class);
        SysLoginLogMapper loginLogMapper = Mockito.mock(SysLoginLogMapper.class);
        SysTenantMapper tenantMapper = Mockito.mock(SysTenantMapper.class);
        PasswordEncoder passwordEncoder = Mockito.mock(PasswordEncoder.class);
        JdbcTemplate jdbc = Mockito.mock(JdbcTemplate.class);
        Mockito.when(jdbc.queryForList(Mockito.anyString(), Mockito.eq(Long.class), Mockito.anyLong()))
                .thenReturn(List.of());
        Mockito.when(jdbc.queryForList(Mockito.anyString(), Mockito.eq(String.class), Mockito.anyLong()))
                .thenReturn(List.of());

        authService = new AuthService(userMapper, userRoleMapper, roleMapper, rolePermissionMapper,
                permissionMapper, loginLogMapper, tenantMapper, passwordEncoder,
                jwtTokenProvider, jdbc, revocationChecker);
    }

    private String newRefresh() {
        AuthUser auth = AuthUser.builder().userId(1L).tenantId(0L).username("alice")
                .roles(List.of()).permissions(List.of()).build();
        return jwtTokenProvider.generateRefreshToken(auth);
    }

    @Test
    @DisplayName("旧 refresh 刷新一次后再用必须失败（jti 已吊销）")
    void oldRefreshRejectedAfterUse() {
        String oldRefresh = newRefresh();

        // 第一次刷新：成功，返回新 refresh
        AuthService.RefreshData data = authService.refresh(oldRefresh);
        assertDoesNotThrow(() -> jwtTokenProvider.parse(data.refreshToken()));

        // 第二次用同一张旧 refresh：必须失败
        assertThrows(BizException.class, () -> authService.refresh(oldRefresh),
                "旧 refresh 在已被刷新后必须失效");

        // 新 refresh 仍可刷新（未被吊销）
        assertDoesNotThrow(() -> authService.refresh(data.refreshToken()),
                "新 refresh 应仍可刷新");
    }

    @Test
    @DisplayName("refresh 返回新 refresh token（与旧不同、新 jti）")
    void returnsNewRefresh() {
        String oldRefresh = newRefresh();
        AuthService.RefreshData data = authService.refresh(oldRefresh);
        org.junit.jupiter.api.Assertions.assertNotEquals(oldRefresh, data.refreshToken());
        String oldJti = jwtTokenProvider.parse(oldRefresh).getId();
        String newJti = jwtTokenProvider.parse(data.refreshToken()).getId();
        org.junit.jupiter.api.Assertions.assertNotEquals(oldJti, newJti);
    }
}
