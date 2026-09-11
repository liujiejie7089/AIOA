package cn.aioa.resource.support;

import cn.aioa.security.AuthUser;

import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 权限目录 —— 权限码 → 允许的角色集合。
 *
 * <p>口径与平台既有审批权限保持一致（审批相关一律 {@code ROLE_ADMIN}，见
 * {@code ApprovalController} 的 todo/decision 校验），避免出现两套互相矛盾的权限语义。</p>
 *
 * <p>说明：{@code AuthUser.permissions} 目前始终为空（JWT 不携带细粒度权限），
 * 故此处以**角色**作为权限的判定依据；若将来接入 {@code sys_permission}，
 * 只需在 {@link #holds} 中优先判断 {@code user.getPermissions()} 即可，调用方无需改动。</p>
 */
public final class PermissionCatalog {

    /** 请假审批：与请假类数字人绑定，仅租户管理员持有。 */
    public static final String APPROVAL_LEAVE = "approval:leave";
    /** 通用对话：所有登录用户。 */
    public static final String CHAT_BASIC = "chat:basic";
    /** 知识库检索：所有登录用户（受自身知识库范围约束）。 */
    public static final String KB_READ = "kb:read";
    /** 公文起草：所有登录用户。 */
    public static final String DOC_DRAFT = "doc:draft";

    private static final String ROLE_ADMIN = "ROLE_ADMIN";
    private static final String ROLE_USER = "ROLE_USER";

    /** 权限码 → 允许的角色。 */
    private static final Map<String, Set<String>> GRANTS = Map.of(
            CHAT_BASIC, Set.of(ROLE_USER, ROLE_ADMIN),
            KB_READ, Set.of(ROLE_USER, ROLE_ADMIN),
            DOC_DRAFT, Set.of(ROLE_USER, ROLE_ADMIN),
            APPROVAL_LEAVE, Set.of(ROLE_ADMIN));

    /** 角色 → 中文名（用于权限不足时的提示，避免把英文角色码裸露给用户）。 */
    private static final Map<String, String> ROLE_NAMES = Map.of(
            ROLE_ADMIN, "租户管理员",
            ROLE_USER, "普通成员");

    private PermissionCatalog() {
    }

    /** 权限码 → 允许的角色集合；未知权限码返回空集合（默认拒绝）。 */
    public static Set<String> rolesOf(String permission) {
        return GRANTS.getOrDefault(permission, Set.of());
    }

    /** 允许角色的中文描述，如「租户管理员」。 */
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
     * 是否为租户管理员。数字员工的**管理类操作**（创建/修改/启停/立即执行/删除）一律以此为唯一判定，
     * 与 {@code ApprovalController} 审批动作的口径一致——避免同一平台出现两套管理员语义。
     */
    public static boolean isAdmin(AuthUser user) {
        return user != null && user.getRoles() != null && user.getRoles().contains(ROLE_ADMIN);
    }
}
