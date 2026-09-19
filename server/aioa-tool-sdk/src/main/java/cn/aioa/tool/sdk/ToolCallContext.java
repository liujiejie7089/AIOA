package cn.aioa.tool.sdk;

import java.util.List;

/**
 * 调用者上下文（SDK 的中立载体）。
 *
 * <p>刻意不复用安全层的 {@code AuthUser}：SDK 会被独立模块甚至外部子应用引入，
 * 不该被迫依赖平台的认证实现。谁调用谁转换 —— 网关把 {@code AuthUser} 转成本记录，
 * 工具方法只认识这一个朴素结构。</p>
 *
 * @param tenantId      租户
 * @param userId        调用者
 * @param username      账号名
 * @param institutionId 所属机构（可空）
 * @param roles         角色码
 */
public record ToolCallContext(Long tenantId, Long userId, String username,
                             Long institutionId, List<String> roles) {

    public static ToolCallContext system() {
        return new ToolCallContext(0L, 0L, "system", null, List.of());
    }

    public boolean hasRole(String role) {
        return role != null && roles != null && roles.contains(role);
    }
}
