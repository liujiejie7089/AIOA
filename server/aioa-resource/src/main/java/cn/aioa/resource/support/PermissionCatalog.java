package cn.aioa.resource.support;

import cn.aioa.security.AuthUser;

import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 权限目录 —— 权限码 → 允许的角色集合。
 *
 * <p>本目录覆盖平台全部 6 个内置角色（与 {@code sys_role.role_code} 一一对应），
 * 避免出现「角色存在但没有任何权限码」的真空状态。</p>
 *
 * <p>两个维度的分工：</p>
 * <ul>
 *   <li><b>权限点</b>（本类）：决定「能做什么」，如创建 vs 使用数字员工；</li>
 *   <li><b>数据范围</b>（{@code sys_role.data_scope}）：决定「能看到谁的数据」，
 *       取值 ALL / TENANT / ORG / DEPT / SELF。</li>
 * </ul>
 * 二者必须同时校验：有权限点才谈得上范围，有范围才不会越界。
 *
 * <p>{@code AuthUser.permissions} 目前始终为空（JWT 不携带细粒度权限），故以角色判定；
 * 将来接入 {@code sys_permission} 只需在 {@link #holds} 优先判断 permissions，调用方无需改动。</p>
 */
public final class PermissionCatalog {

    /** 请假审批：与请假类数字人绑定。 */
    public static final String APPROVAL_LEAVE = "approval:leave";
    /** 通用对话：所有登录用户。 */
    public static final String CHAT_BASIC = "chat:basic";
    /** 知识库检索：所有登录用户。 */
    public static final String KB_READ = "kb:read";
    /** 公文起草：所有登录用户。 */
    public static final String DOC_DRAFT = "doc:draft";

    // ---- 数字员工：创建 / 使用 / 管理 三分，支撑最小权限与部门分发 ----
    /** 使用数字员工（发起对话、提交业务申请）。所有登录用户。 */
    public static final String WORKER_USE = "worker:use";
    /**
     * 创建数字员工。租户管理员 + 企业管理员（后者受 {@code institution_id} 约束，仅本机构）。
     *
     * <p>放开企业管理员是为了消除「能管理却不能创建」的自相矛盾；
     * 越权风险由归属机构兜底——创建的员工自动打上本机构标记，改不了其他机构的。</p>
     */
    public static final String WORKER_CREATE = "worker:create";
    /** 管理数字员工（修改/启停/删除）。租户管理员、企业管理员（限本机构）。 */
    public static final String WORKER_MANAGE = "worker:manage";

    // ---- 平台全部内置角色 ----
    public static final String ROLE_ADMIN = "ROLE_ADMIN";
    public static final String ROLE_USER = "ROLE_USER";
    public static final String ROLE_TENANT_ADMIN = "ROLE_TENANT_ADMIN";
    public static final String ROLE_ORG_ADMIN = "ROLE_ORG_ADMIN";
    public static final String ROLE_DEPT_LEADER = "ROLE_DEPT_LEADER";
    public static final String ROLE_MEMBER = "ROLE_MEMBER";

    /** 所有登录用户。 */
    private static final Set<String> ALL = Set.of(
            ROLE_ADMIN, ROLE_USER, ROLE_TENANT_ADMIN, ROLE_ORG_ADMIN, ROLE_DEPT_LEADER, ROLE_MEMBER);
    /** 租户管理员级：系统管理员 + 租户管理员。 */
    private static final Set<String> TENANT_ADMINS = Set.of(ROLE_ADMIN, ROLE_TENANT_ADMIN);
    /** 机构管理员级：租户管理员级 + 企业管理员。 */
    private static final Set<String> ORG_ADMINS = Set.of(ROLE_ADMIN, ROLE_TENANT_ADMIN, ROLE_ORG_ADMIN);

    /** 权限码 → 允许的角色。 */
    private static final Map<String, Set<String>> GRANTS = Map.of(
            CHAT_BASIC, ALL,
            KB_READ, ALL,
            DOC_DRAFT, ALL,
            WORKER_USE, ALL,
            WORKER_CREATE, ORG_ADMINS,
            WORKER_MANAGE, ORG_ADMINS,
            APPROVAL_LEAVE, TENANT_ADMINS);

    /** 角色 → 中文名（用于提示，避免把英文角色码裸露给用户）。 */
    private static final Map<String, String> ROLE_NAMES = Map.of(
            ROLE_ADMIN, "系统管理员",
            ROLE_TENANT_ADMIN, "租户管理员",
            ROLE_ORG_ADMIN, "企业管理员",
            ROLE_DEPT_LEADER, "部门负责人",
            ROLE_MEMBER, "机构成员",
            ROLE_USER, "普通用户");

    private PermissionCatalog() {
    }

    /** 权限码 → 允许的角色集合；未知权限码返回空集合（默认拒绝）。 */
    public static Set<String> rolesOf(String permission) {
        return GRANTS.getOrDefault(permission, Set.of());
    }

    /** 允许角色的中文描述，如「系统管理员、租户管理员」。 */
    public static String rolesText(String permission) {
        List<String> names = rolesOf(permission).stream()
                .map(r -> ROLE_NAMES.getOrDefault(r, r))
                .sorted()
                .toList();
        return names.isEmpty() ? "（无）" : String.join("、", names);
    }

    /** 当前用户是否持有该权限：先看细粒度 permissions，再按角色判定。 */
    public static boolean holds(AuthUser user, String permission) {
        if (user == null) {
            return false;
        }
        if (permission == null || permission.isBlank()) {
            return true;
        }
        if (user.getPermissions() != null && user.getPermissions().contains(permission)) {
            return true;
        }
        Set<String> allowed = rolesOf(permission);
        if (allowed.isEmpty()) {
            return false;
        }
        return user.getRoles() != null && user.getRoles().stream().anyMatch(allowed::contains);
    }

    /**
     * 是否为租户管理员（含系统管理员）。数字员工的管理类操作以此为判定。
     *
     * <p>此前仅认 {@code ROLE_ADMIN}，导致租户管理员调用 {@code /api/v1/workers} 创建时
     * 收到 403，且提示语自相矛盾（提示「仅租户管理员可执行」却把租户管理员拒之门外）。</p>
     */
    public static boolean isAdmin(AuthUser user) {
        return holdsAny(user, TENANT_ADMINS);
    }

    /** 是否为平台（系统）管理员：仅 {@code ROLE_ADMIN}，用于跨租户与平台级操作。 */
    public static boolean isPlatformAdmin(AuthUser user) {
        return holdsAny(user, Set.of(ROLE_ADMIN));
    }

    /** 是否具备机构管理员及以上身份。 */
    public static boolean isOrgAdmin(AuthUser user) {
        return holdsAny(user, ORG_ADMINS);
    }

    private static boolean holdsAny(AuthUser user, Set<String> roles) {
        return user != null && user.getRoles() != null && user.getRoles().stream().anyMatch(roles::contains);
    }
}
