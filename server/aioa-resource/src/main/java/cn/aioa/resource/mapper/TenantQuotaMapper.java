package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.TenantQuota;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Mapper
public interface TenantQuotaMapper extends BaseMapper<TenantQuota> {

    /** 租户成员配额总览：启用用户全员列出（未建配额行的人显示 0），供管理端二次分配。 */
    @Select("SELECT u.id AS userId, COALESCE(u.nickname, u.username) AS nickname, "
            + "COALESCE(q.quota_tokens, 0) AS quotaTokens, COALESCE(q.used_tokens, 0) AS usedTokens, "
            + "COALESCE(q.free_tokens, 0) AS freeTokens, q.updated_at AS updatedAt "
            + "FROM sys_user u "
            + "LEFT JOIN tenant_quota q ON q.user_id = u.id AND q.tenant_id = u.tenant_id AND q.deleted_at IS NULL "
            + "WHERE u.tenant_id = #{tenantId} AND u.status = 'ENABLED' AND u.deleted_at IS NULL "
            + "ORDER BY u.id")
    List<Map<String, Object>> selectTenantQuotaOverview(@Param("tenantId") Long tenantId);

    /** 用量报表：按业务类型聚合（自起始时间起），供管理端用量看板。 */
    @Select("SELECT biz_type AS bizType, COUNT(*) AS cnt, "
            + "COALESCE(SUM(total_tokens), 0) AS totalTokens, "
            + "COALESCE(SUM(prompt_tokens), 0) AS promptTokens, "
            + "COALESCE(SUM(completion_tokens), 0) AS completionTokens "
            + "FROM token_ledger WHERE tenant_id = #{tenantId} AND deleted_at IS NULL AND created_at >= #{since} "
            + "GROUP BY biz_type ORDER BY totalTokens DESC")
    List<Map<String, Object>> selectUsageByBizType(@Param("tenantId") Long tenantId,
                                                   @Param("since") LocalDateTime since);

    /** 最近词元流水（对账用，倒序）。 */
    @Select("SELECT l.id, l.user_id AS userId, COALESCE(u.nickname, u.username, CONCAT('用户#', l.user_id)) AS userName, "
            + "l.biz_type AS bizType, l.biz_title AS bizTitle, l.total_tokens AS totalTokens, l.created_at AS createdAt "
            + "FROM token_ledger l LEFT JOIN sys_user u ON u.id = l.user_id "
            + "WHERE l.tenant_id = #{tenantId} AND l.deleted_at IS NULL "
            + "ORDER BY l.id DESC LIMIT #{limit}")
    List<Map<String, Object>> selectRecentLedger(@Param("tenantId") Long tenantId, @Param("limit") int limit);
}
