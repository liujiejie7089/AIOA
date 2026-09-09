package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.ClientActivityLog;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

@Mapper
public interface ClientActivityLogMapper extends BaseMapper<ClientActivityLog> {

    /** 操作审计：操作日志带用户名（管理端审计页），倒序取最新 N 条；userId=0 视为数字员工系统操作。 */
    @Select("SELECT l.id, l.user_id AS userId, "
            + "CASE WHEN l.user_id = 0 THEN '数字员工' "
            + "ELSE COALESCE(u.nickname, u.username, CONCAT('用户#', l.user_id)) END AS userName, "
            + "l.action, l.status, l.label, l.created_at AS createdAt "
            + "FROM client_activity_log l LEFT JOIN sys_user u ON u.id = l.user_id "
            + "WHERE l.tenant_id = #{tenantId} AND l.deleted_at IS NULL "
            + "ORDER BY l.id DESC LIMIT #{limit}")
    List<Map<String, Object>> selectRecentAudit(@Param("tenantId") Long tenantId, @Param("limit") int limit);
}
