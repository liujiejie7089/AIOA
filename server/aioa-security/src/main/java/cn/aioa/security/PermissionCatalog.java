package cn.aioa.security;


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
 * <p>{@code AuthUser.permissions} 的来源见 {@link PermissionResolver}（V36 起可由权限申请审批链路发放）；
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
     * 创建数字员工。所有登录用户均可创建（V33 放开普通成员）。
     *
     * <p>放开普通成员的依据：数字员工本质是「个人 AI 助理」，要求人人都找管理员代建
     * 既不现实也放大审批负担。风险由<b>可见范围</b>兜底，而非剥夺创建权：</p>
     * <ul>
     *   <li>企业管理员：受 {@code institution_id} 约束，仅本机构；</li>
     *   <li>部门负责人：受 {@code visible_scope} 约束，新建即锁定到本部门；</li>
     *   <li>普通成员：新建即锁定为 {@code SELF}（仅本人可见），他人列表里根本不出现。</li>
     * </ul>
     * <p>越权类型是另一道闸：请假审批类仍需 {@code approval:leave}，
     * 普通成员即使能建通用助理，也建不了有审批权的数字人。</p>
     */
    public static final String WORKER_CREATE = "worker:create";
    /**
     * 修改<b>自己创建</b>的数字员工（配置、启停）。
     *
     * <p>与 {@link #WORKER_MANAGE} 的区别：后者管全租户/全机构的资产，前者只管自己的。
     * 「创建者即所有者」是最小权限的常规做法——能建就能改，但不因此获得删他人资产的权力，
     * 删除仍只认 {@link #WORKER_MANAGE}。</p>
     */
    public static final String WORKER_EDIT_SELF = "worker:edit:self";
    /**
     * 管理数字员工（修改/启停/删除）。
     *
     * <p>租户管理员（全租户）、企业管理员（限本机构）、部门负责人（限已分发到本部门的）。</p>
     */
    public static final String WORKER_MANAGE = "worker:manage";

    /**
     * 专家（AI 专家）的创建与配置：从全局模板导入租户副本、改参数、启停、删除。
     *
     * <p>此前 {@code ExpertConfigController} 只认 {@code ROLE_ADMIN || ROLE_TENANT_ADMIN}，
     * 企业管理员无法为自己的机构引入专家。现纳入企业管理员，范围仍受其机构约束。</p>
     */
    public static final String EXPERT_MANAGE = "expert:manage";

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
    /**
     * 数字员工管理者：机构管理员级 + 部门负责人。
     *
     * <p>部门负责人的范围在 {@code WorkerController} 内另行收紧（只看本部门可见的员工），
     * 不能仅凭本集合判定「能管全部」。</p>
     */
    private static final Set<String> WORKER_MANAGERS = Set.of(
            ROLE_ADMIN, ROLE_TENANT_ADMIN, ROLE_ORG_ADMIN, ROLE_DEPT_LEADER);

    /**
     * 专家管理者：机构管理员级（不含部门负责人）。
     *
     * <p>专家是面向整个租户/机构的知识资产，部门负责人不参与专家治理；
     * 其可配置的是「本部门数字员工」。</p>
     */
    private static final Set<String> EXPERT_MANAGERS = Set.of(
            ROLE_ADMIN, ROLE_TENANT_ADMIN, ROLE_ORG_ADMIN);

    /** 权限码 → 允许的角色。 */
    private static final Map<String, Set<String>> GRANTS = Map.of(
            CHAT_BASIC, ALL,
            KB_READ, ALL,
            DOC_DRAFT, ALL,
            WORKER_USE, ALL,
            WORKER_CREATE, ALL,
            WORKER_EDIT_SELF, ALL,
            WORKER_MANAGE, WORKER_MANAGERS,
            EXPERT_MANAGE, EXPERT_MANAGERS,
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

    /** 权限码 → 中文名（用于申请单与目录展示，避免把英文码裸露给用户）。 */
    private static final Map<String, String> PERMISSION_NAMES = Map.of(
            CHAT_BASIC, "通用对话",
            KB_READ, "知识库检索",
            DOC_DRAFT, "公文起草",
            WORKER_USE, "使用数字员工",
            WORKER_CREATE, "创建数字员工",
            WORKER_EDIT_SELF, "修改自己的数字员工",
            WORKER_MANAGE, "管理数字员工",
            EXPERT_MANAGE, "专家管理",
            APPROVAL_LEAVE, "请假审批");

    /**
     * 权限码 → 对应数字员工类型（申请单「目的」展示用）。
     *
     * <p>只有真正对应某类越权数字员工的权限码才在此登记，其余返回 null。
     * 用 {@code Map.of} 不能存 null，故只登记有映射的项。</p>
     */
    private static final Map<String, String> WORKER_TYPE_OF = Map.of(
            APPROVAL_LEAVE, "LEAVE_APPROVER");

    /** 权限码中文名；未知返回权限码本身。 */
    public static String nameOf(String permission) {
        if (permission == null) {
            return null;
        }
        return PERMISSION_NAMES.getOrDefault(permission, permission);
    }

    /** 权限码对应的数字员工类型；无映射返回 null。 */
    public static String workerTypeOf(String permission) {
        return permission == null ? null : WORKER_TYPE_OF.get(permission);
    }

    /**
     * 可申请权限码清单。
     *
     * <p>排除 {@code ALL} 类权限（全体登录用户天然持有，申请无意义），
     * 只保留需要审批发放的「稀缺权限」。排序固定，便于前端稳定渲染。</p>
     */
    public static List<String> applicablePermissions() {
        return GRANTS.entrySet().stream()
                .filter(e -> !ALL.equals(e.getValue()))
                .map(Map.Entry::getKey)
                .sorted()
                .toList();
    }

    /** 该权限码是否可申请（既存在定义、又非全员持有）。 */
    public static boolean applicable(String permission) {
        return permission != null && GRANTS.containsKey(permission)
                && !ALL.equals(GRANTS.get(permission));
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
        return holdsByRole(user, permission);
    }

    /**
     * 仅按<b>角色</b>判定是否持有该权限（不含细粒度授权）。
     *
     * <p>为什么要单独一个方法：{@link #holds} 是「角色 ∪ 授权」的并集，无法回答
     * 「这个权限到底是怎么来的」。权限来源对用户是有意义的信息 ——
     * 角色内置的权限收回需要改角色，而申请来的授权可以自己回收，
     * 前端必须区分展示，否则会把「可回收」误显示成「不可变」。</p>
     */
    public static boolean holdsByRole(AuthUser user, String permission) {
        if (user == null || permission == null || permission.isBlank()) {
            return false;
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

    /** 是否具备「部门负责人」身份且不高于该层级（即范围必须收紧到本部门）。 */
    public static boolean isDeptLeaderOnly(AuthUser user) {
        return hasRole(user, ROLE_DEPT_LEADER) && !holdsAny(user, ORG_ADMINS);
    }

    /**
     * 是否为「数字员工管理者」（系统管理员 / 租户管理员 / 企业管理员 / 部门负责人）。
     *
     * <p>用于区分两类创建者：管理者创建的资产面向团队（{@code TENANT}/{@code ORG}/{@code DEPT} 可见），
     * 普通成员创建的只能本人可见（{@code SELF}）。</p>
     */
    public static boolean isWorkerManager(AuthUser user) {
        return holdsAny(user, WORKER_MANAGERS);
    }

    /**
     * 是否为该数字员工的创建者（{@code created_by} 匹配）。
     *
     * <p>创建者拥有「改自己的」权力，但不因此管到别人的资产；
     * 两侧都为 null 时返回 false（宁可拒绝，不可放行）。</p>
     */
    public static boolean isCreator(AuthUser user, Long createdBy) {
        return user != null && user.getUserId() != null && createdBy != null
                && user.getUserId().equals(createdBy);
    }

    /** 当前用户是否持有某角色码。 */
    public static boolean hasRole(AuthUser user, String role) {
        return user != null && user.getRoles() != null && user.getRoles().contains(role);
    }

    private static boolean holdsAny(AuthUser user, Set<String> roles) {
        return user != null && user.getRoles() != null && user.getRoles().stream().anyMatch(roles::contains);
    }
}
