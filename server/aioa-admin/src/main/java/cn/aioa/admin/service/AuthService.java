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

    /**
     * 登录。
     *
     * @param tenantName 管理端登录时填写的租户名称。规则为「<b>声明即校验</b>」：
     * <ul>
     *   <li>{@code null}（旧客户端未声明，用户端 H5 与自动化脚本即属此类）→ 跳过，保持兼容；</li>
     *   <li>空白串且账号属租户侧（tenantId ≥ 2）→ 1004「请输入租户名称」；</li>
     *   <li>非空 → 与账号所属租户名称比对（忽略大小写与全部空白），不一致即 1004。</li>
     * </ul>
     * 该字段的作用是防「拿对了账号密码却登到了别的租户」这类误操作（用户名在全库唯一，
     * 但运维/客服同时持有多个租户账号时容易看错），不是认证因子 —— 认证仍由密码完成。
     */
    public LoginData login(String username, String password, String tenantName, String ip, String ua) {
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
        try {
            assertTenantName(user, tenantName);
        } catch (BizException e) {
            loginLog(user.getId(), ip, ua, false, e.getMessage());
            throw e;
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

    /**
     * 租户名称校验（管理端登录的「相关校验」落地）。
     *
     * <p>租户侧账号（tenantId ≥ 2）必须给出与所属租户一致的名称；平台侧账号
     * （tenantId 0/1，如 {@code admin}）不参与校验 —— 平台账号压根不属于任何业务租户，
     * 若强行比对会把平台管理员挡在门外。</p>
     *
     * <p><b>口径修正（2026-09-15）</b>：原实现要求「与租户名称逐字相等」，实测导致大量
     * 机构/企业账号登不进去 —— 用户看到登录框里写着「机构 / 企业账号填写所属租户全称」，
     * 自然会把<b>机构名称</b>填进去（如把「某某智能科技有限公司研发中心」填进租户名称），
     * 直接命中 1004「租户名称与账号不匹配」。现改为多形态匹配，见
     * {@link #tenantNameMatches}；校验强度不变（仍然只认本账号自己那个租户）。</p>
     */
    private void assertTenantName(SysUser user, String provided) {
        if (provided == null) {
            return; // 旧协议客户端：未声明该字段，跳过校验
        }
        boolean tenantSide = user.getTenantId() != null && user.getTenantId() >= 2L;
        if (!tenantSide) {
            return; // 平台侧账号：租户名称不参与校验
        }
        String want = normalizeTenantName(provided);
        if (want == null || want.isEmpty()) {
            throw new BizException(1004, "请输入租户名称");
        }
        if (tenantNameMatches(user.getTenantId(), want)) {
            return;
        }
        String actual = tenantNameOf(user.getTenantId());
        // 此处密码已校验通过，向持证人回显其所属租户名称不构成越权信息泄露，
        // 而「该填什么」正是原提示缺失的部分 —— 否则用户只能反复试。
        throw new BizException(1004, "租户名称与账号不匹配。该账号属于租户「"
                + (actual == null ? "未知" : actual) + "」，填该租户名称、租户编码或其下属机构名称均可");
    }

    /**
     * 租户归属匹配：入参只与「该账号自身所属租户」比对，因此不存在跨租户误配的可能。
     *
     * <p>四种形态均接受（先归一化：去全部空白 + 转小写）：</p>
     * <ol>
     *   <li>租户名称全称；</li>
     *   <li>租户编码（如 {@code MYQY-DEMO}，短、好敲）；</li>
     *   <li><b>该租户名下任一机构名称</b> —— 用户视角里「机构」就是他所属的那个组织，
     *       这是实际登录时最容易被填对的一项；</li>
     *   <li>上述任一名称与入参互为包含（两侧长度均 ≥ 3），容忍
     *       「某某市某某区大数据管理局」被写成「大数据管理局」这类省略前缀的输入。</li>
     * </ol>
     */
    private boolean tenantNameMatches(Long tenantId, String want) {
        List<String> accepted = new java.util.ArrayList<>(4);
        String tenantName = tenantNameOf(tenantId);
        if (tenantName != null) {
            accepted.add(tenantName);
        }
        try {
            SysTenant t = tenantMapper.selectById(tenantId);
            if (t != null && t.getCode() != null) {
                accepted.add(t.getCode());
            }
        } catch (Exception ignore) {
            // 编码取不到不影响其余形态的匹配
        }
        try {
            accepted.addAll(jdbc.queryForList(
                    "SELECT name FROM org_institution WHERE tenant_id = ? AND deleted_at IS NULL",
                    String.class, tenantId));
        } catch (Exception ignore) {
            // 机构表不可用（如未启用企业域）时退化为「只认租户名称 / 编码」
        }
        for (String raw : accepted) {
            String n = normalizeTenantName(raw);
            if (n == null || n.isEmpty()) {
                continue;
            }
            if (n.equals(want)) {
                return true;
            }
            if (want.length() >= 3 && n.contains(want)) {
                return true;
            }
            if (n.length() >= 3 && want.contains(n)) {
                return true;
            }
        }
        return false;
    }

    /** 归一化租户名称：去掉全部空白（含全角空格）并统一小写，容忍「多打一个空格」这类输入抖动。 */
    private static String normalizeTenantName(String raw) {
        if (raw == null) {
            return null;
        }
        StringBuilder sb = new StringBuilder(raw.length());
        for (int i = 0; i < raw.length(); i++) {
            char ch = raw.charAt(i);
            if (ch == '\u3000' || Character.isWhitespace(ch)) {
                continue;
            }
            sb.append(Character.toLowerCase(ch));
        }
        return sb.toString();
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
        List<String> out = new java.util.ArrayList<>();
        if (!roleIds.isEmpty()) {
            List<Long> permIds = rolePermissionMapper.selectList(
                            new LambdaQueryWrapper<SysRolePermission>().in(SysRolePermission::getRoleId, roleIds))
                    .stream().map(SysRolePermission::getPermId).distinct().toList();
            if (!permIds.isEmpty()) {
                permissionMapper.selectBatchIds(permIds).stream()
                        .map(SysPermission::getPermCode)
                        .forEach(out::add);
            }
        }
        // V36 需求①：并上「权限申请审批」发放的授权。与 JwtAuthenticationFilter 的
        // DbPermissionResolver 同一口径，保证 /auth/me 与请求上下文的权限视图一致
        // （否则前端按 /me 判断、后端按 token 判断，会出现「页面说没有、接口却能过」的分裂）。
        try {
            List<String> granted = jdbc.queryForList(
                    "SELECT DISTINCT permission_code FROM permission_grant WHERE user_id = ? "
                            + "AND status = 'ACTIVE' AND deleted_at IS NULL "
                            + "AND (expire_at IS NULL OR expire_at > NOW(6))", String.class, userId);
            for (String code : granted) {
                if (!out.contains(code)) {
                    out.add(code);
                }
            }
        } catch (Exception e) {
            // 迁移未完成时静默退回角色权限，认证链路不因此中断
            log.warn("resolve granted permissions failed: userId={} err={}", userId, e.getMessage());
        }
        return out;
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
        writeLog(userId, ip, ua, ok, failReason, "LOGIN");
    }

    /**
     * 退出登录留痕（V35）。
     *
     * <p>本系统使用无状态 JWT，服务端不持有会话，因此登出的「失效」动作发生在客户端
     * （丢弃 localStorage 中的令牌）；这里的职责是把登出事件写进审计链，便于按
     * userId + 时间还原一次完整会话。接口幂等：即便令牌缺失 / 已失效也按成功返回，
     * 避免登出过程本身报错——登出永远不应该失败。</p>
     */
    public void logout(String ip, String ua) {
        AuthUser auth = AuthUserContext.get();
        writeLog(auth == null ? null : auth.getUserId(), ip, ua, true, null, "LOGOUT");
    }

    private void writeLog(Long userId, String ip, String ua, boolean ok, String failReason, String action) {
        try {
            SysLoginLog entry = new SysLoginLog();
            entry.setUserId(userId);
            entry.setIp(ip);
            entry.setUa(ua == null || ua.length() > 512 ? (ua == null ? null : ua.substring(0, 512)) : ua);
            entry.setResult(ok);
            entry.setAction(action);
            entry.setFailReason(failReason);
            entry.setLoginAt(LocalDateTime.now());
            loginLogMapper.insert(entry);
        } catch (Exception e) {
            log.warn("login log persist failed: {}", e.getMessage());
        }
    }
}
