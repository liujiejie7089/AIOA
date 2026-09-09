package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.Notification;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface NotificationMapper extends BaseMapper<Notification> {

    /**
     * 租户内全部启用的管理员 id（用于审批提交时定向通知）。
     * 原生 SQL 跨 sys_user / sys_user_role / sys_role 三表；手动排除软删。
     */
    @Select("SELECT u.id FROM sys_user u "
            + "JOIN sys_user_role ur ON ur.user_id = u.id AND ur.deleted_at IS NULL "
            + "JOIN sys_role r ON r.id = ur.role_id AND r.deleted_at IS NULL "
            + "WHERE u.tenant_id = #{tenantId} AND r.role_code = 'ROLE_ADMIN' "
            + "AND u.status = 'ENABLED' AND u.deleted_at IS NULL")
    List<Long> selectTenantAdminIds(@Param("tenantId") Long tenantId);

    /** 租户内全部启用用户 id（数字员工定时任务到点后全员弹窗提醒）。 */
    @Select("SELECT id FROM sys_user "
            + "WHERE tenant_id = #{tenantId} AND status = 'ENABLED' AND deleted_at IS NULL")
    List<Long> selectTenantUserIds(@Param("tenantId") Long tenantId);
}
