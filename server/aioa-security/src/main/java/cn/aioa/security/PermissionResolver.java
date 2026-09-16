package cn.aioa.security;

import java.util.List;

/**
 * 实时细粒度权限解析：给 {@link JwtAuthenticationFilter} 填充 {@link AuthUser#getPermissions()}。
 *
 * <p>与 {@link RoleResolver} 的分工：角色决定「是哪一类人」，权限码决定「具体能做什么」。
 * 权限码有两处来源，由实现方合并后返回：</p>
 * <ol>
 *   <li><b>角色内置</b> —— {@code sys_role_permission}（静态配置）；</li>
 *   <li><b>授权发放</b> —— {@code permission_grant} 中 {@code status='ACTIVE'} 的行
 *       （V36 需求①：普通员工申请 → 部门审批 → 租户管理员发放，全链路过审）。</li>
 * </ol>
 *
 * <p>为什么做成接口而不是直接在过滤器里查库：{@code aioa-security} 不引 MyBatis，
 * 也不该知道业务表结构。与 {@code RoleResolver} 保持一致，实现方放在业务模块
 * （当前为 {@code cn.aioa.org.security.DbPermissionResolver}），
 * 由 {@code ObjectProvider} 惰性注入 —— 部署裁剪掉业务模块时过滤器自动退化为「仅角色判定」。</p>
 *
 * <p><b>与 {@code RoleResolver} 的关键差异</b>：本接口<b>不承担认证否决</b>。
 * 返回空集合只代表「没有额外权限码」，不代表用户无效 —— 用户有效性已经由角色解析负责。</p>
 */
public interface PermissionResolver {

    /**
     * 用户的实时权限码集合。允许返回 {@code null}（等同空集合）。
     * 实现方不应抛异常：解析失败时返回空集合，让认证继续走角色判定这条兼容路径。
     */
    List<String> permissionsOf(Long userId);
}
