package cn.aioa.admin.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 人员管理（系统管理 → 人员管理）的作用域与分类内核。
 *
 * <h3>为什么需要它</h3>
 * <p>历史实现把「系统管理」整块绑死在 {@code ROLE_ADMIN} 上：菜单 {@code v-if="isPlatformAdmin"}、
 * 路由 {@code minTier:'platform'}、接口 {@code requireAdmin()} 三层一致地只认平台管理员。
 * 机构管理员（{@code ROLE_ORG_ADMIN}）登录后既看不到菜单、路由又被重定向回首页，即便强闯接口
 * 也是 403 —— 于是出现「人员管理页面全部空白」的观感。而 {@code /admin/users} 本身又是
 * <b>无过滤全表分页</b>，任何拿到平台令牌的人都能看到全部租户账号，属于作用域缺失。</p>
 *
 * <h3>作用域模型（与 docs/16-组织与员工作用域模型.md 对齐）</h3>
 * <table>
 *   <tr><th>调用者角色</th><th>可见人员</th><th>分组维度（groupBy）</th></tr>
 *   <tr><td>平台管理员 ROLE_ADMIN</td><td>全平台（可按 tenantId 收窄）</td><td>TENANT 按租户</td></tr>
 *   <tr><td>租户管理员 ROLE_TENANT_ADMIN</td><td>本租户全部账号</td><td>INSTITUTION 按机构</td></tr>
 *   <tr><td>机构管理员 ROLE_ORG_ADMIN</td><td><b>本机构</b>（硬边界）</td><td>TIER 按档位</td></tr>
 *   <tr><td>部门负责人 ROLE_DEPT_LEADER</td><td><b>本部门</b>（硬边界）</td><td>TIER 按档位</td></tr>
 *   <tr><td>普通成员</td><td>403</td><td>—</td></tr>
 * </table>
 *
 * <h3>两条人员数据源的取舍</h3>
 * <p>{@code sys_user} 是<b>账号</b>（按 tenant_id 归属），{@code org_member} 是<b>机构花名册</b>
 * （按 institution_id / department_id 归属）。机构管理员问的「我的人」显然是花名册，
 * 所以机构/部门两级作用域一律走 {@code org_member} 过滤；平台/租户两级以 {@code sys_user}
 * 为主表（保证「有账号但未加入机构」的人也不会消失），再左连花名册补机构/部门与职级信息。</p>
 *
 * <p>注意：本模块（aioa-admin）只依赖 aioa-common / aioa-security，不能引用 aioa-org 的实体与
 * Mapper（模块依赖方向：org 不依赖 admin，admin 也不依赖 org，二者仅共享数据库表）。
 * 因此这里与 {@link AuthService} 一样，用原生 SQL 读组织域的表。</p>
 */
@Service
public class PersonnelService {

    public static final String ROLE_ADMIN = "ROLE_ADMIN";
    public static final String ROLE_TENANT_ADMIN = "ROLE_TENANT_ADMIN";
    public static final String ROLE_ORG_ADMIN = "ROLE_ORG_ADMIN";
    public static final String ROLE_DEPT_LEADER = "ROLE_DEPT_LEADER";

    /** 调用者的数据作用域。 */
    public static final String SCOPE_PLATFORM = "PLATFORM";
    public static final String SCOPE_TENANT = "TENANT";
    public static final String SCOPE_ORG = "ORG";
    public static final String SCOPE_DEPT = "DEPT";

    /** 被展示人员的档位分类（scopeClass）。 */
    public static final String CLASS_PLATFORM = "PLATFORM";
    public static final String CLASS_TENANT = "TENANT";
    public static final String CLASS_ORG = "ORG";
    public static final String CLASS_DEPT = "DEPT";
    public static final String CLASS_MEMBER = "MEMBER";

    /** 档位顺序（分组展示与统计的排序依据）。 */
    private static final List<String> CLASS_ORDER =
            List.of(CLASS_PLATFORM, CLASS_TENANT, CLASS_ORG, CLASS_DEPT, CLASS_MEMBER);

    private static final Map<String, String> CLASS_LABELS = Map.of(
            CLASS_PLATFORM, "平台管理员",
            CLASS_TENANT, "租户管理员",
            CLASS_ORG, "机构管理员",
            CLASS_DEPT, "部门负责人",
            CLASS_MEMBER, "普通成员");

    /**
     * 人员主查询。
     *
     * <p>{@code om} 子查询取每个用户在 org_member 中 id 最小的一条 ACTIVE 记录（与
     * {@code AuthService.institutionIdOf} 的 {@code ORDER BY id LIMIT 1} 同口径），
     * 避免一个用户挂在多个机构时主表被 JOIN 放大成重复行。</p>
     *
     * <p>注意本库开启了 {@code ONLY_FULL_GROUP_BY}：所有聚合都在标量子查询里完成，
     * 主查询不出现裸 GROUP BY。</p>
     */
    private static final String BASE_SELECT = """
            SELECT u.id AS user_id, u.username, u.nickname, u.mobile, u.email, u.status,
                   u.tenant_id, u.last_login_at, u.created_at,
                   t.name AS tenant_name,
                   om.institution_id, om.department_id, om.job_title, om.employee_no, om.is_org_admin,
                   i.name AS institution_name, d.name AS department_name,
                   (SELECT COUNT(*) FROM org_department x
                     WHERE x.leader_user_id = u.id AND x.deleted_at IS NULL AND x.status = 'ACTIVE') AS leads_dept,
                   (SELECT GROUP_CONCAT(r.role_code ORDER BY r.role_code)
                      FROM sys_user_role ur JOIN sys_role r ON r.id = ur.role_id
                     WHERE ur.user_id = u.id) AS role_codes
            FROM sys_user u
            LEFT JOIN sys_tenant t ON t.id = u.tenant_id
            LEFT JOIN (
                SELECT m1.user_id, m1.institution_id, m1.department_id, m1.job_title, m1.employee_no, m1.is_org_admin
                FROM org_member m1
                JOIN (SELECT user_id, MIN(id) AS mid FROM org_member
                       WHERE status = 'ACTIVE' AND deleted_at IS NULL GROUP BY user_id) p ON p.mid = m1.id
            ) om ON om.user_id = u.id
            LEFT JOIN org_institution i ON i.id = om.institution_id AND i.deleted_at IS NULL
            LEFT JOIN org_department d ON d.id = om.department_id AND d.deleted_at IS NULL
            WHERE u.deleted_at IS NULL
            """;

    private final JdbcTemplate jdbc;

    public PersonnelService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** 调用者作用域 + 硬边界锚点。 */
    private record ScopeInfo(String scope, Long tenantId, Long institutionId, Long departmentId) {
    }

    // ================================================================== 对外入口

    /**
     * 分类后的人员视图：按调用者权限作用域取数，再按 租户 / 机构 / 档位 自动分组。
     *
     * @param keyword  按用户名或昵称模糊过滤（可空）
     * @param tenantId 仅平台管理员有意义：把结果收窄到指定租户（可空）
     */
    public Map<String, Object> personnel(String keyword, Long tenantId) {
        AuthUser viewer = AuthUserContext.require();
        ScopeInfo scope = resolveScope(viewer);
        List<Map<String, Object>> rows = query(scope, keyword, tenantId);

        String groupBy = switch (scope.scope()) {
            case SCOPE_PLATFORM -> "TENANT";
            case SCOPE_TENANT -> "INSTITUTION";
            default -> "TIER";
        };

        Map<String, List<Map<String, Object>>> buckets = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            buckets.computeIfAbsent(groupKey(groupBy, row), k -> new ArrayList<>()).add(row);
        }
        List<Map<String, Object>> groups = new ArrayList<>();
        for (Map.Entry<String, List<Map<String, Object>>> e : buckets.entrySet()) {
            Map<String, Object> g = new LinkedHashMap<>();
            g.put("key", e.getKey());
            g.put("label", groupLabel(groupBy, e.getValue().get(0)));
            g.put("count", e.getValue().size());
            g.put("members", e.getValue());
            groups.add(g);
        }
        if ("TIER".equals(groupBy)) {
            groups.sort(Comparator.comparingInt(g -> CLASS_ORDER.indexOf(classOfKey(String.valueOf(g.get("key"))))));
        }

        Map<String, Object> classCounts = new LinkedHashMap<>();
        for (String c : CLASS_ORDER) {
            classCounts.put(c, 0);
        }
        for (Map<String, Object> row : rows) {
            String c = String.valueOf(row.get("scopeClass"));
            classCounts.put(c, ((Number) classCounts.getOrDefault(c, 0)).intValue() + 1);
        }

        boolean platform = SCOPE_PLATFORM.equals(scope.scope());
        String scopeName = scopeName(scope);

        Map<String, Object> capability = new LinkedHashMap<>();
        capability.put("canAssignRole", platform);
        capability.put("canChangeStatus", platform);
        capability.put("readOnly", !platform);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("scope", scope.scope());
        out.put("scopeName", scopeName);
        out.put("groupBy", groupBy);
        out.put("total", rows.size());
        out.put("groups", groups);
        out.put("classCounts", classCounts);
        out.put("capability", capability);
        out.put("tenantId", scope.tenantId());
        out.put("institutionId", scope.institutionId());
        out.put("departmentId", scope.departmentId());
        out.put("keyword", keyword == null ? "" : keyword.trim());
        out.put("hint", platform
                ? "平台管理员视角：可见全平台账号，可按租户查看并分配角色 / 启停账号。"
                : "当前账号为「" + scopeName + "」范围，人员列表按权限分类只读展示；"
                        + "角色分配与账号启停仅平台管理员可操作。");
        return out;
    }

    /**
     * 与 {@link #personnel} 同一作用域的平铺列表（供 {@code GET /admin/users} 兼容旧契约使用）。
     */
    public List<Map<String, Object>> visibleRows(String keyword, Long tenantId) {
        AuthUser viewer = AuthUserContext.require();
        return query(resolveScope(viewer), keyword, tenantId);
    }

    // ================================================================== 作用域

    /** 解析调用者的数据作用域；无任何管理档位直接 403（不再静默返回空列表）。 */
    private ScopeInfo resolveScope(AuthUser u) {
        List<String> roles = u.getRoles() == null ? List.of() : u.getRoles();
        if (roles.contains(ROLE_ADMIN)) {
            return new ScopeInfo(SCOPE_PLATFORM, null, null, null);
        }
        if (roles.contains(ROLE_TENANT_ADMIN)) {
            Long tid = u.getTenantId();
            if (tid == null || tid == 0L) {
                throw BizException.forbidden("当前租户管理员账号未绑定租户，无法查看人员列表");
            }
            return new ScopeInfo(SCOPE_TENANT, tid, null, null);
        }
        if (roles.contains(ROLE_ORG_ADMIN)) {
            // 令牌里的 institutionId 在登录时快照；用户后加入机构则可能为空，回查一次兜底
            Long iid = u.getInstitutionId() != null ? u.getInstitutionId() : memberAnchor(u.getUserId(), "institution_id");
            if (iid == null) {
                throw BizException.forbidden("当前机构管理员账号未绑定机构，无法查看人员列表");
            }
            return new ScopeInfo(SCOPE_ORG, null, iid, null);
        }
        if (roles.contains(ROLE_DEPT_LEADER)) {
            Long did = u.getDepartmentId() != null && u.getDepartmentId() != 0L
                    ? u.getDepartmentId()
                    : memberAnchor(u.getUserId(), "department_id");
            if (did == null || did == 0L) {
                throw BizException.forbidden("当前部门负责人账号未绑定部门，无法查看人员列表");
            }
            return new ScopeInfo(SCOPE_DEPT, null, null, did);
        }
        throw BizException.forbidden("当前账号无权查看人员管理列表（仅平台管理员 / 租户管理员 / 机构管理员 / 部门负责人可访问）");
    }

    private Long memberAnchor(Long userId, String column) {
        if (userId == null) {
            return null;
        }
        try {
            List<Long> rows = jdbc.queryForList(
                    "SELECT " + column + " FROM org_member WHERE user_id = ? AND status = 'ACTIVE' "
                            + "AND deleted_at IS NULL ORDER BY id LIMIT 1", Long.class, userId);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    // ================================================================== 查询

    private List<Map<String, Object>> query(ScopeInfo scope, String keyword, Long tenantId) {
        StringBuilder where = new StringBuilder();
        List<Object> args = new ArrayList<>();
        switch (scope.scope()) {
            case SCOPE_PLATFORM -> {
                if (tenantId != null) {
                    where.append(" AND u.tenant_id = ?");
                    args.add(tenantId);
                }
            }
            case SCOPE_TENANT -> {
                where.append(" AND u.tenant_id = ?");
                args.add(scope.tenantId());
            }
            case SCOPE_ORG -> {
                where.append(" AND om.institution_id = ?");
                args.add(scope.institutionId());
            }
            case SCOPE_DEPT -> {
                where.append(" AND om.department_id = ?");
                args.add(scope.departmentId());
            }
            default -> throw BizException.forbidden("未知的数据作用域");
        }
        if (keyword != null && !keyword.isBlank()) {
            where.append(" AND (u.username LIKE ? OR u.nickname LIKE ?)");
            String like = "%" + keyword.trim() + "%";
            args.add(like);
            args.add(like);
        }
        String sql = BASE_SELECT + where + " ORDER BY u.tenant_id, om.institution_id, om.department_id, u.id";

        List<Map<String, Object>> raw = args.isEmpty()
                ? jdbc.queryForList(sql)
                : jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(raw.size());
        for (Map<String, Object> r : raw) {
            out.add(toRow(r));
        }
        return out;
    }

    /** 数据库行 → 前端友好的人员行（含 scopeClass 档位分类与所属机构 / 部门名称）。 */
    private Map<String, Object> toRow(Map<String, Object> r) {
        List<String> roles = splitRoles(asString(r.get("role_codes")));
        boolean orgAdmin = isTrue(r.get("is_org_admin"));
        boolean leadsDept = numOf(r.get("leads_dept")) > 0;
        String cls = classOf(roles, orgAdmin, leadsDept);

        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", numOf(r.get("user_id")));
        row.put("username", asString(r.get("username")));
        row.put("nickname", asString(r.get("nickname")));
        row.put("mobile", asString(r.get("mobile")));
        row.put("email", asString(r.get("email")));
        row.put("status", asString(r.get("status")));
        row.put("tenantId", numOf(r.get("tenant_id")));
        row.put("tenantName", asString(r.get("tenant_name")));
        row.put("institutionId", numOf(r.get("institution_id")));
        row.put("institutionName", asString(r.get("institution_name")));
        row.put("departmentId", numOf(r.get("department_id")));
        row.put("departmentName", asString(r.get("department_name")));
        row.put("jobTitle", asString(r.get("job_title")));
        row.put("employeeNo", asString(r.get("employee_no")));
        row.put("lastLoginAt", asString(r.get("last_login_at")));
        row.put("createdAt", asString(r.get("created_at")));
        row.put("roles", roles);
        row.put("scopeClass", cls);
        row.put("scopeLabel", CLASS_LABELS.getOrDefault(cls, "普通成员"));
        row.put("orgAdmin", orgAdmin);
        row.put("deptLeader", leadsDept);
        return row;
    }

    /**
     * 档位判定（权威来源是角色码；组织域的两列作为补充信号）。
     *
     * <p>补充信号不是冗余：演示与历史数据里存在「花名册标了 is_org_admin / 是部门 leader_user_id，
     * 但 sys_user_role 仍是 ROLE_MEMBER」的账号（如 {@code scxsyb_ldr}）。只看角色码会把这些
     * 管理者混进「普通成员」，与他们真实的管理身份不符，也让上级看不到该看的边界。</p>
     */
    private String classOf(List<String> roles, boolean orgAdmin, boolean leadsDept) {
        if (roles.contains(ROLE_ADMIN)) return CLASS_PLATFORM;
        if (roles.contains(ROLE_TENANT_ADMIN)) return CLASS_TENANT;
        if (roles.contains(ROLE_ORG_ADMIN) || orgAdmin) return CLASS_ORG;
        if (roles.contains(ROLE_DEPT_LEADER) || leadsDept) return CLASS_DEPT;
        return CLASS_MEMBER;
    }

    // ================================================================== 分组

    private String groupKey(String groupBy, Map<String, Object> row) {
        return switch (groupBy) {
            case "TENANT" -> "TENANT:" + nz(row.get("tenantId"));
            case "INSTITUTION" -> "INSTITUTION:" + nz(row.get("institutionId"));
            default -> "TIER:" + row.get("scopeClass");
        };
    }

    private String groupLabel(String groupBy, Map<String, Object> row) {
        switch (groupBy) {
            case "TENANT": {
                String name = asString(row.get("tenantName"));
                return name != null && !name.isBlank() ? name : "平台账号（未归属租户）";
            }
            case "INSTITUTION": {
                String name = asString(row.get("institutionName"));
                return name != null && !name.isBlank() ? name : "租户直属（未加入机构）";
            }
            default:
                return String.valueOf(row.get("scopeLabel"));
        }
    }

    /** 从 {@code TIER:ORG} 这类分组键里取回档位码。 */
    private String classOfKey(String key) {
        int i = key.indexOf(':');
        return i < 0 ? key : key.substring(i + 1);
    }

    // ================================================================== 文案

    private String scopeName(ScopeInfo sc) {
        switch (sc.scope()) {
            case SCOPE_PLATFORM:
                return "全平台（跨租户）";
            case SCOPE_TENANT: {
                String name = one("SELECT name FROM sys_tenant WHERE id = ?", sc.tenantId());
                return name == null ? "租户 #" + sc.tenantId() : name;
            }
            case SCOPE_ORG: {
                String name = one("SELECT name FROM org_institution WHERE id = ? AND deleted_at IS NULL",
                        sc.institutionId());
                return name == null ? "机构 #" + sc.institutionId() : name;
            }
            default: {
                String dept = one("SELECT name FROM org_department WHERE id = ? AND deleted_at IS NULL",
                        sc.departmentId());
                return dept == null ? "部门 #" + sc.departmentId() : dept;
            }
        }
    }

    private String one(String sql, Object arg) {
        try {
            List<String> rows = jdbc.queryForList(sql, String.class, arg);
            return rows.isEmpty() ? null : rows.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    // ================================================================== 小工具

    private static List<String> splitRoles(String codes) {
        if (codes == null || codes.isBlank()) {
            return List.of();
        }
        List<String> out = new ArrayList<>();
        for (String c : codes.split(",")) {
            if (!c.isBlank()) {
                out.add(c.trim());
            }
        }
        return out;
    }

    private static boolean isTrue(Object v) {
        if (v == null) return false;
        if (v instanceof Boolean b) return b;
        if (v instanceof Number n) return n.intValue() != 0;
        String s = String.valueOf(v).trim();
        return "1".equals(s) || "true".equalsIgnoreCase(s);
    }

    /** 归一化为 Long（无值或 0 部门占位均为 null）。 */
    private static Long numOf(Object v) {
        if (v == null) return null;
        if (v instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Object nz(Object v) {
        return v == null ? 0 : v;
    }

    /** 时间戳与 BigDecimal 统一转字符串，避免 JSON 里出现纪元毫秒数与科学计数法。 */
    private static String asString(Object v) {
        if (v == null) return null;
        if (v instanceof CharSequence || v instanceof Number || v instanceof Boolean) {
            return String.valueOf(v);
        }
        return String.valueOf(v);
    }
}
