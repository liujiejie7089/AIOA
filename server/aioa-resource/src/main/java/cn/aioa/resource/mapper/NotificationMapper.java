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
     *
     * <p><b>为什么是 IN ('ROLE_ADMIN','ROLE_TENANT_ADMIN')</b>：本方法服务的是
     * {@code ApprovalService} 的「新审批待处理」——「租户的管理员」。真实数据里
     * 每个业务租户的管理员角色是 {@code ROLE_TENANT_ADMIN}，而 {@code ROLE_ADMIN}
     * 是平台管理员（全库仅 1 个，且挂在 tenant 0）。原先只匹配 {@code ROLE_ADMIN}
     * （再叠加 {@code u.tenant_id = #{tenantId}}）导致：tenant 0 命中 1 人，而
     * tenant 2–9 一律命中 0 人 —— 通知循环空转，租户管理员从未收到过该通知。
     * 改为 IN 是<b>纯增量</b>：保留原有 ROLE_ADMIN 命中（tenant 0 行为不变），
     * 同时补上各租户真正的 ROLE_TENANT_ADMIN，不会摘掉任何既有收件人。
     * 与 {@code OrgGuard.requireApprover()}（TENANT_ADMIN + ROLE_ADMIN）口径一致。</p>
     */
    @Select("SELECT DISTINCT u.id FROM sys_user u "
            + "JOIN sys_user_role ur ON ur.user_id = u.id AND ur.deleted_at IS NULL "
            + "JOIN sys_role r ON r.id = ur.role_id AND r.deleted_at IS NULL "
            + "WHERE u.tenant_id = #{tenantId} "
            + "AND r.role_code IN ('ROLE_ADMIN', 'ROLE_TENANT_ADMIN') "
            + "AND u.status = 'ENABLED' AND u.deleted_at IS NULL")
    List<Long> selectTenantAdminIds(@Param("tenantId") Long tenantId);

    /** 租户内全部启用用户 id（数字员工定时任务到点后全员弹窗提醒）。 */
    @Select("SELECT id FROM sys_user "
            + "WHERE tenant_id = #{tenantId} AND status = 'ENABLED' AND deleted_at IS NULL")
    List<Long> selectTenantUserIds(@Param("tenantId") Long tenantId);
}
