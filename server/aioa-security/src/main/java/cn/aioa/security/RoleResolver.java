package cn.aioa.security;

import java.util.List;

/**
 * 角色实时解析 SPI：让过滤器拿到「当前数据库中的角色」而非 JWT 签发时刻的快照，
 * 支撑管理端「角色变更即时生效」。由持有用户/角色表的模块（aioa-admin）提供实现。
 */
public interface RoleResolver {

    /** 返回用户当前角色编码列表（如 ROLE_ADMIN）；查不到返回空列表。 */
    List<String> rolesOf(Long userId);
}
