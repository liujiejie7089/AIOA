package cn.aioa.admin.controller;

import cn.aioa.admin.entity.SysRole;
import cn.aioa.admin.entity.SysTenant;
import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.entity.SysUserRole;
import cn.aioa.admin.mapper.SysRoleMapper;
import cn.aioa.admin.mapper.SysTenantMapper;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.admin.mapper.SysUserRoleMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 平台级租户管理（多租户开通）。
 *
 * <p>市面 SaaS 通行做法：开通租户 = 建租户主体 + 开通租户管理员账号 + 初始化资源池，
 * 这三件事必须在一个事务里完成，否则会出现「有租户但没人能登录」或「能登录但没有额度」的半开通状态。
 *
 * <p>权限：仅平台管理员（ROLE_ADMIN，tenant_id = 0）。租户管理员不能自建租户。
 */
@RestController
@RequestMapping("/api/v1/admin/tenants")
public class TenantController {

    private final SysTenantMapper tenantMapper;
    private final SysUserMapper userMapper;
    private final SysRoleMapper roleMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final PasswordEncoder passwordEncoder;
    private final JdbcTemplate jdbc;

    public TenantController(SysTenantMapper tenantMapper, SysUserMapper userMapper,
                            SysRoleMapper roleMapper, SysUserRoleMapper userRoleMapper,
                            PasswordEncoder passwordEncoder, JdbcTemplate jdbc) {
        this.tenantMapper = tenantMapper;
        this.userMapper = userMapper;
        this.roleMapper = roleMapper;
        this.userRoleMapper = userRoleMapper;
        this.passwordEncoder = passwordEncoder;
        this.jdbc = jdbc;
    }

    private AuthUser requirePlatformAdmin() {
        AuthUser u = AuthUserContext.require();
        if (!u.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("租户管理仅平台管理员可访问");
        }
        return u;
    }

    /** 租户列表：附带机构数、成员数、资源池配额，便于一眼看清每个租户的规模。 */
    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list() {
        requirePlatformAdmin();
        List<SysTenant> tenants = tenantMapper.selectList(
                new LambdaQueryWrapper<SysTenant>().orderByAsc(SysTenant::getId));
        List<Map<String, Object>> out = new java.util.ArrayList<>();
        for (SysTenant t : tenants) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", t.getId());
            m.put("code", t.getCode());
            m.put("name", t.getName());
            m.put("status", t.getStatus());
            // V66：登录域名（平台需要一眼看清「哪些租户已分配域名」）
            m.put("domain", t.getDomain());
            m.put("institutionCount", count("org_institution", t.getId()));
            m.put("memberCount", count("org_member", t.getId()));
            m.put("userCount", count("sys_user", t.getId()));
            Map<String, Object> pool = jdbc.queryForMap(
                    "SELECT IFNULL(SUM(token_total),0) AS total, IFNULL(SUM(token_used),0) AS used, "
                            + "IFNULL(SUM(expert_seats),0) AS expertSeats, IFNULL(SUM(expert_used),0) AS expertUsed, "
                            + "IFNULL(SUM(skill_seats),0) AS skillSeats, IFNULL(SUM(skill_used),0) AS skillUsed "
                            + "FROM tenant_resource_pool WHERE tenant_id = ? AND deleted_at IS NULL",
                    t.getId());
            m.put("quotaTokens", pool.get("total"));
            m.put("usedTokens", pool.get("used"));
            // 席位回吐：管理端「调整资源」弹窗要能预填当前值，否则用户看不到自己正在改什么
            m.put("expertSeats", pool.get("expertSeats"));
            m.put("expertUsed", pool.get("expertUsed"));
            m.put("skillSeats", pool.get("skillSeats"));
            m.put("skillUsed", pool.get("skillUsed"));
            // 已分配 = 各机构配额之和（资源池表不冗余该字段，避免两处口径不一致）
            Long allocated = jdbc.queryForObject(
                    "SELECT IFNULL(SUM(quota_tokens),0) FROM org_quota WHERE tenant_id = ? AND deleted_at IS NULL",
                    Long.class, t.getId());
            m.put("allocatedTokens", allocated == null ? 0L : allocated);
            // 租户管理员账号
            List<Long> admins = jdbc.queryForList(
                    "SELECT u.id FROM sys_user u JOIN sys_user_role ur ON ur.user_id = u.id "
                            + "JOIN sys_role r ON r.id = ur.role_id "
                            + "WHERE u.tenant_id = ? AND r.role_code = 'ROLE_TENANT_ADMIN' "
                            + "AND u.deleted_at IS NULL ORDER BY u.id LIMIT 1", Long.class, t.getId());
            if (!admins.isEmpty()) {
                SysUser a = userMapper.selectById(admins.get(0));
                if (a != null) {
                    m.put("adminUsername", a.getUsername());
                    m.put("adminName", a.getNickname());
                }
            }
            out.add(m);
        }
        return ApiResponse.ok(out);
    }

    /**
     * 开通租户：建租户 + 开管理员账号（授 ROLE_TENANT_ADMIN）+ 初始化资源池，同一事务。
     * body: { code, name, domain?, adminUsername, adminName, adminPassword?, tokenTotal?, expertSeats?, skillSeats?, period? }
     *
     * <p>V66：新增 {@code domain}（平台分配的登录域名，可选但必须唯一）。
     * 平台开通的是<b>唯一一层</b>租户；「子租户」能力已于 2026-09-28 按决定移除（含 V68 删列），
     * 租户侧不再有「在本租户下再开一层」的入口。</p>
     */
    @PostMapping
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<Map<String, Object>> create(@RequestBody Map<String, Object> body) {
        AuthUser actor = requirePlatformAdmin();
        String code = str(body.get("code"), "租户编码");
        String name = str(body.get("name"), "租户名称");
        String adminUsername = str(body.get("adminUsername"), "租户管理员账号");
        String adminName = body.get("adminName") == null ? adminUsername : String.valueOf(body.get("adminName"));
        String domain = domainOf(body.get("domain"), null);

        if (tenantMapper.selectCount(new LambdaQueryWrapper<SysTenant>().eq(SysTenant::getCode, code)) > 0) {
            throw BizException.badRequest("租户编码已存在：" + code);
        }
        if (userMapper.selectCount(new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, adminUsername)) > 0) {
            throw BizException.badRequest("登录账号已存在：" + adminUsername);
        }

        // 1) 租户主体
        SysTenant t = new SysTenant();
        t.setCode(code);
        t.setName(name);
        t.setStatus("ENABLED");
        t.setDomain(domain);
        t.setTenantId(null); // 自身即租户，插入后再回填
        t.setCreatedAt(LocalDateTime.now());
        t.setCreatedBy(actor.getUserId());
        tenantMapper.insert(t);
        // tenant_id 自指，保证与其他业务表一致的租户隔离口径
        jdbc.update("UPDATE sys_tenant SET tenant_id = id WHERE id = ?", t.getId());
        t.setTenantId(t.getId());

        // 2) 租户管理员账号
        SysUser u = new SysUser();
        u.setTenantId(t.getId());
        u.setUsername(adminUsername);
        u.setNickname(adminName);
        u.setPasswordHash(passwordEncoder.encode(
                body.get("adminPassword") == null || String.valueOf(body.get("adminPassword")).isBlank()
                        ? "User@123" : String.valueOf(body.get("adminPassword"))));
        u.setStatus("ENABLED");
        userMapper.insert(u);
        bindRole(u.getId(), "ROLE_TENANT_ADMIN");

        // 3) 资源池初始化（没有额度则租户无法开展业务）
        String period = body.get("period") == null ? currentPeriod() : String.valueOf(body.get("period"));
        long tokenTotal = lng(body.get("tokenTotal"), 1_000_000L);
        int expertSeats = (int) lng(body.get("expertSeats"), 8L);
        int skillSeats = (int) lng(body.get("skillSeats"), 12L);
        jdbc.update("INSERT INTO tenant_resource_pool (tenant_id, period, token_total, token_used, "
                        + "expert_seats, expert_used, skill_seats, skill_used, "
                        + "warn_threshold, unit_price, status, created_at, created_by) "
                        + "VALUES (?,?,?,0,?,0,?,0,20,0.000120,'ACTIVE',NOW(6),?)",
                t.getId(), period, tokenTotal, expertSeats, skillSeats, actor.getUserId());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", t.getId());
        out.put("code", code);
        out.put("name", name);
        out.put("adminUsername", adminUsername);
        out.put("adminName", adminName);
        out.put("adminUserId", u.getId());
        out.put("period", period);
        out.put("tokenTotal", tokenTotal);
        out.put("domain", domain);
        return ApiResponse.ok(out);
    }

    /**
     * 编辑租户名称 / 编码 / 登录域名。
     *
     * <p><b>为什么用 {@link LambdaUpdateWrapper#set} 而不是 {@code updateById(entity)}</b>：
     * MyBatis-Plus 的 {@code updateById} 默认策略是 {@code NOT_NULL}，即实体里为 {@code null}
     * 的字段**不会进 SET 子句**。而「清空登录域名」恰恰就是要把 domain 写成 NULL ——
     * 于是接口回 {@code 200 + domain:null}、库里却纹丝不动：**清空变成假成功**
     * （用户把域名输入框清空点保存，界面提示「已保存」，域名其实还在）。
     * 2026-09-28 由 `scripts/e2e_tenant_domain_quota.py` 的 A7 断言实测抓到（A6 回 200 但库里没变）。
     * 这里显式 set，才能真的写 NULL；这也让「清空」与「未提交该字段」在语义上区分开：
     * 只有 body **含** domain 键（哪怕是 null）才动这一列。</p>
     */
    @PutMapping("/{id}")
    public ApiResponse<SysTenant> update(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        requirePlatformAdmin();
        SysTenant t = tenantMapper.selectById(id);
        if (t == null) {
            throw BizException.notFound("租户不存在：" + id);
        }
        LambdaUpdateWrapper<SysTenant> w = new LambdaUpdateWrapper<SysTenant>()
                .eq(SysTenant::getId, id);
        boolean touched = false;
        if (body.get("name") != null) {
            w.set(SysTenant::getName, String.valueOf(body.get("name")));
            touched = true;
        }
        if (body.get("code") != null) {
            String code = String.valueOf(body.get("code"));
            SysTenant dup = tenantMapper.selectOne(new LambdaQueryWrapper<SysTenant>()
                    .eq(SysTenant::getCode, code).ne(SysTenant::getId, id));
            if (dup != null) {
                throw BizException.badRequest("租户编码已存在：" + code);
            }
            w.set(SysTenant::getCode, code);
            touched = true;
        }
        if (body.containsKey("domain")) {
            // 含键即动该列：null / 空串 ⇒ 真的写成 NULL（清空），不是静默跳过
            w.set(SysTenant::getDomain, domainOf(body.get("domain"), id));
            touched = true;
        }
        if (touched) {
            w.set(SysTenant::getUpdatedAt, LocalDateTime.now());
            tenantMapper.update(null, w);
        }
        // 回吐改后实况（重新读库），而不是内存里那份可能没落库的实体 —— 展示必须与事实同源
        return ApiResponse.ok(tenantMapper.selectById(id));
    }

    /**
     * 域名的归一化 + 唯一性校验（唯一性必然在这里做，因为「同一个域名只能属于一个租户」是全局约束）。
     *
     * @param excludeTenantId 修改时排除自身；新建传 null
     */
    private String domainOf(Object raw, Long excludeTenantId) {
        String d = cn.aioa.common.util.TenantDomain.normalize(raw == null ? null : String.valueOf(raw));
        if (d == null) {
            return null;    // 允许清空 / 不分配
        }
        if (!cn.aioa.common.util.TenantDomain.isValid(d)) {
            throw BizException.badRequest("登录域名格式不合法（应为小写字母/数字/连字符组成的多级域名，如 dsj.aioa.local）：" + raw);
        }
        LambdaQueryWrapper<SysTenant> w = new LambdaQueryWrapper<SysTenant>().eq(SysTenant::getDomain, d);
        if (excludeTenantId != null) {
            w.ne(SysTenant::getId, excludeTenantId);
        }
        if (tenantMapper.selectCount(w) > 0) {
            throw BizException.badRequest("登录域名已被占用：" + d);
        }
        return d;
    }

    /** 启用 / 停用租户（停用后该租户成员将无法登录，由登录态校验拦截）。 */
    @PostMapping("/{id}/status")
    public ApiResponse<SysTenant> changeStatus(@PathVariable Long id,
                                               @RequestBody Map<String, Object> body) {
        requirePlatformAdmin();
        SysTenant t = tenantMapper.selectById(id);
        if (t == null) {
            throw BizException.notFound("租户不存在：" + id);
        }
        String status = String.valueOf(body == null ? "" : body.get("status"));
        if (!"ENABLED".equals(status) && !"DISABLED".equals(status)) {
            throw BizException.badRequest("状态只能为 ENABLED 或 DISABLED");
        }
        if (id == 1L && "DISABLED".equals(status)) {
            throw BizException.badRequest("默认租户不可停用");
        }
        t.setStatus(status);
        t.setUpdatedAt(LocalDateTime.now());
        tenantMapper.updateById(t);
        // 同步冻结/解冻该租户全部账号，避免停用后仍持有有效令牌
        jdbc.update("UPDATE sys_user SET status = ? WHERE tenant_id = ? AND deleted_at IS NULL",
                "ENABLED".equals(status) ? "ENABLED" : "DISABLED", id);
        return ApiResponse.ok(t);
    }

    /** 重置租户管理员密码（运营高频动作）。 */
    @PostMapping("/{id}/reset-admin-password")
    public ApiResponse<Map<String, Object>> resetAdminPassword(@PathVariable Long id,
                                                               @RequestBody Map<String, Object> body) {
        requirePlatformAdmin();
        List<Long> admins = jdbc.queryForList(
                "SELECT u.id FROM sys_user u JOIN sys_user_role ur ON ur.user_id = u.id "
                        + "JOIN sys_role r ON r.id = ur.role_id "
                        + "WHERE u.tenant_id = ? AND r.role_code = 'ROLE_TENANT_ADMIN' "
                        + "AND u.deleted_at IS NULL ORDER BY u.id LIMIT 1", Long.class, id);
        if (admins.isEmpty()) {
            throw BizException.notFound("该租户没有租户管理员账号");
        }
        String pwd = body == null || body.get("password") == null || String.valueOf(body.get("password")).isBlank()
                ? "User@123" : String.valueOf(body.get("password"));
        jdbc.update("UPDATE sys_user SET password_hash = ?, updated_at = NOW(6) WHERE id = ?",
                passwordEncoder.encode(pwd), admins.get(0));
        SysUser a = userMapper.selectById(admins.get(0));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", id);
        out.put("username", a == null ? null : a.getUsername());
        out.put("reset", true);
        return ApiResponse.ok(out);
    }

    /** 按机构维度查看某租户的入驻概况（平台视角下钻）。 */
    @GetMapping("/{id}/institutions")
    public ApiResponse<List<Map<String, Object>>> institutions(@PathVariable Long id,
                                                               @RequestParam(required = false) String keyword) {
        requirePlatformAdmin();
        String sql = "SELECT i.id, i.code, i.name, i.org_type AS orgType, i.status, "
                + "i.admin_name AS adminName, i.onboard_step AS onboardStep, "
                + "(SELECT COUNT(*) FROM org_department d WHERE d.institution_id = i.id AND d.deleted_at IS NULL) AS deptCount, "
                + "(SELECT COUNT(*) FROM org_member m WHERE m.institution_id = i.id AND m.deleted_at IS NULL) AS memberCount "
                + "FROM org_institution i WHERE i.tenant_id = ? AND i.deleted_at IS NULL ";
        if (keyword != null && !keyword.isBlank()) {
            sql += "AND (i.name LIKE ? OR i.code LIKE ?) ";
            return ApiResponse.ok(jdbc.queryForList(sql + "ORDER BY i.id",
                    id, "%" + keyword + "%", "%" + keyword + "%"));
        }
        return ApiResponse.ok(jdbc.queryForList(sql + "ORDER BY i.id", id));
    }

    // ------------------------------------------------------------------ helpers

    private long count(String table, Long tenantId) {
        Long n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM " + table + " WHERE tenant_id = ? AND deleted_at IS NULL",
                Long.class, tenantId);
        return n == null ? 0L : n;
    }

    private void bindRole(Long userId, String roleCode) {
        SysRole role = roleMapper.selectOne(new LambdaQueryWrapper<SysRole>()
                .eq(SysRole::getRoleCode, roleCode));
        if (role == null) {
            throw BizException.badRequest("角色不存在：" + roleCode);
        }
        SysUserRole ur = new SysUserRole();
        ur.setUserId(userId);
        ur.setRoleId(role.getId());
        userRoleMapper.insert(ur);
    }

    private static String str(Object v, String label) {
        if (v == null || String.valueOf(v).isBlank()) {
            throw BizException.badRequest(label + "不能为空");
        }
        return String.valueOf(v).trim();
    }

    private static long lng(Object v, long def) {
        if (v == null || String.valueOf(v).isBlank()) {
            return def;
        }
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static String currentPeriod() {
        java.time.LocalDate d = java.time.LocalDate.now();
        return d.getYear() + "-" + String.format("%02d", d.getMonthValue());
    }
}
