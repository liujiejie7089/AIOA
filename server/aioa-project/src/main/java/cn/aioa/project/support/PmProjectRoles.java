package cn.aioa.project.support;

import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 项目内角色（BR-05）：固定 5 档，**不支持租户自建**。
 *
 * <p><b>为什么不让租户自建角色</b>：自建角色会让「角色 × 权限」矩阵不可穷举 ——
 * 无法写断言（不知道会出现哪些组合）、无法在界面上枚举（配置页无从渲染）、
 * 也无法给出确定的越权边界。这与本项目的权限码单入口（{@code PermissionCatalog}）纪律直接冲突。</p>
 *
 * <p><b>它是「项目内」角色，不是系统角色</b>：存 {@code pm_project_member.role_code}，
 * 不会进入 {@code AuthUser.roles}。判定必须带 {@code project_id} —— 同一人在 A 项目是 PM、
 * 在 B 项目可以是 VIEWER，这正是本项目级角色的意义。</p>
 */
public final class PmProjectRoles {

    /** 项目负责人：项目的第一责任人，可管成员与任务。 */
    public static final String OWNER = "OWNER";
    /** 项目经理：可管成员与任务。 */
    public static final String PM = "PM";
    /** 开发：可管任务（开发项目里通常也是仓库协作者）。 */
    public static final String DEV = "DEV";
    /** 普通成员：只读 + 可更新自己负责的任务进度。 */
    public static final String MEMBER = "MEMBER";
    /** 只读：只能看。 */
    public static final String VIEWER = "VIEWER";

    /** 管理序（用于下拉渲染与「角色是否覆盖」比较），与业务优先级一致。 */
    public static final List<String> ORDER = List.of(OWNER, PM, DEV, MEMBER, VIEWER);

    public static final Set<String> ALL = Set.of(OWNER, PM, DEV, MEMBER, VIEWER);

    /** 可管理「项目本身」（改基础信息、改状态、绑/解绑仓库）。 */
    private static final Set<String> PROJECT_MANAGERS = Set.of(OWNER, PM);

    /** 可管理「任务」（CRUD + 改状态）。 */
    private static final Set<String> TASK_MANAGERS = Set.of(OWNER, PM, DEV);

    /** 可管理「成员」。 */
    private static final Set<String> MEMBER_MANAGERS = Set.of(OWNER, PM);

    private static final Map<String, String> LABELS = Map.of(
            OWNER, "项目负责人",
            PM, "项目经理",
            DEV, "开发",
            MEMBER, "成员",
            VIEWER, "只读");

    private PmProjectRoles() {
    }

    public static boolean isValid(String role) {
        return role != null && ALL.contains(role);
    }

    public static String label(String role) {
        return LABELS.getOrDefault(role, role);
    }

    public static boolean canManageProject(String role) {
        return role != null && PROJECT_MANAGERS.contains(role);
    }

    public static boolean canManageTask(String role) {
        return role != null && TASK_MANAGERS.contains(role);
    }

    public static boolean canManageMember(String role) {
        return role != null && MEMBER_MANAGERS.contains(role);
    }

    /** 是否至少能修改任务进度（成员可改自己负责任务的进度）。 */
    public static boolean canUpdateOwnTask(String role) {
        return role != null && ALL.contains(role) && !VIEWER.equals(role);
    }

    /** 允许的目标角色选项（供前端下拉，避免两端各写一份）。 */
    public static List<Map<String, String>> options() {
        return ORDER.stream()
                .map(r -> Map.of("value", r, "label", label(r)))
                .toList();
    }
}
