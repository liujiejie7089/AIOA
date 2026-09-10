package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.ApprovalOrder;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

@Mapper
public interface ApprovalOrderMapper extends BaseMapper<ApprovalOrder> {

    /** 查用户显示名（昵称优先）：JWT 不携带昵称时，提交审批快照发起人姓名用。 */
    @Select("SELECT COALESCE(nickname, username, CONCAT('用户#', #{userId})) FROM sys_user "
            + "WHERE id = #{userId} AND deleted_at IS NULL LIMIT 1")
    String selectDisplayName(@Param("userId") Long userId);

    /**
     * 查同租户管理员联系信息（用户端「无权限 → 联系管理员」展示）。
     * 通过 sys_user_role 关联 ROLE_ADMIN 角色，去重返回。
     */
    @Select("SELECT DISTINCT u.username AS username, COALESCE(u.nickname, u.username) AS nickname "
            + "FROM sys_user u "
            + "JOIN sys_user_role ur ON ur.user_id = u.id "
            + "JOIN sys_role r ON r.id = ur.role_id "
            + "WHERE u.tenant_id = #{tenantId} AND u.deleted_at IS NULL AND u.status = 'ENABLED' "
            + "AND r.role_code = 'ROLE_ADMIN' LIMIT 10")
    List<Map<String, Object>> selectTenantAdmins(@Param("tenantId") Long tenantId);
}

