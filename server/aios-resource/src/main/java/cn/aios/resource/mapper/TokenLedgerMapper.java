package cn.aios.resource.mapper;

import cn.aios.resource.entity.TokenLedger;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Mapper
public interface TokenLedgerMapper extends BaseMapper<TokenLedger> {

    /**
     * 统计的时间窗条件（两条 SQL 共用，避免手改一处漏一处）。
     * 用半开区间 {@code [since, until)}：月末 23:59:59.999 之后、次月 1 日 0 点之前不会重复计入。
     */
    String WINDOW = " AND l.tenant_id = #{tenantId} AND l.deleted_at IS NULL"
            + " AND l.created_at >= #{since} AND l.created_at < #{until} ";

    /** 按<b>账号</b>聚合：每把 Key 花了多少、几个人在用。未绑定账号的归「平台默认通道」。 */
    @Select("SELECT COALESCE(l.credential_id, 0) AS keyId, "
            + "COALESCE(c.name, '平台默认通道') AS name, "
            + "COALESCE(c.owner_type, 'UNKNOWN') AS ownerType, "
            + "COALESCE(l.company_charged, -1) AS companyCharged, "
            + "COALESCE(SUM(l.total_tokens), 0) AS tokens, "
            + "COUNT(*) AS calls, "
            + "COUNT(DISTINCT l.bearer_user_id) AS members "
            + "FROM token_ledger l LEFT JOIN model_credential c ON c.id = l.credential_id "
            + "WHERE 1 = 1" + WINDOW
            + "GROUP BY COALESCE(l.credential_id, 0), COALESCE(c.name, '平台默认通道'), "
            + "COALESCE(c.owner_type, 'UNKNOWN'), COALESCE(l.company_charged, -1) "
            + "ORDER BY tokens DESC")
    List<Map<String, Object>> selectStatsByCredential(@Param("tenantId") Long tenantId,
                                                      @Param("since") LocalDateTime since,
                                                      @Param("until") LocalDateTime until);

    /** 按<b>使用者</b>聚合：谁在用（含借用别人账号的人）。 */
    @Select("SELECT COALESCE(l.bearer_user_id, l.user_id, 0) AS keyId, "
            + "COALESCE(u.nickname, u.username, CONCAT('用户#', COALESCE(l.bearer_user_id, l.user_id, 0))) AS name, "
            + "NULL AS ownerType, -1 AS companyCharged, "
            + "COALESCE(SUM(l.total_tokens), 0) AS tokens, "
            + "COUNT(*) AS calls, "
            + "COUNT(DISTINCT l.credential_id) AS members "
            + "FROM token_ledger l LEFT JOIN sys_user u ON u.id = COALESCE(l.bearer_user_id, l.user_id) "
            + "WHERE 1 = 1" + WINDOW
            + "GROUP BY COALESCE(l.bearer_user_id, l.user_id, 0), "
            + "COALESCE(u.nickname, u.username, CONCAT('用户#', COALESCE(l.bearer_user_id, l.user_id, 0))) "
            + "ORDER BY tokens DESC")
    List<Map<String, Object>> selectStatsByBearer(@Param("tenantId") Long tenantId,
                                                  @Param("since") LocalDateTime since,
                                                  @Param("until") LocalDateTime until);

    /**
     * 按<b>付费人</b>聚合：谁承担（个人 / 公司）。
     * charge_user_id = 0 是公司池，不 join 到任何个人。
     */
    @Select("SELECT COALESCE(l.charge_user_id, l.user_id, 0) AS keyId, "
            + "CASE WHEN COALESCE(l.charge_user_id, l.user_id, 0) = 0 THEN '公司池' "
            + "ELSE COALESCE(u.nickname, u.username, CONCAT('用户#', COALESCE(l.charge_user_id, l.user_id, 0))) END AS name, "
            + "COALESCE(l.charge_owner_type, 'UNKNOWN') AS ownerType, "
            + "COALESCE(l.company_charged, -1) AS companyCharged, "
            + "COALESCE(SUM(l.total_tokens), 0) AS tokens, "
            + "COUNT(*) AS calls, "
            + "COUNT(DISTINCT l.bearer_user_id) AS members "
            + "FROM token_ledger l LEFT JOIN sys_user u ON u.id = COALESCE(l.charge_user_id, l.user_id) "
            + "WHERE 1 = 1" + WINDOW
            + "GROUP BY COALESCE(l.charge_user_id, l.user_id, 0), COALESCE(l.charge_owner_type, 'UNKNOWN'), "
            + "COALESCE(l.company_charged, -1), "
            + "CASE WHEN COALESCE(l.charge_user_id, l.user_id, 0) = 0 THEN '公司池' "
            + "ELSE COALESCE(u.nickname, u.username, CONCAT('用户#', COALESCE(l.charge_user_id, l.user_id, 0))) END "
            + "ORDER BY tokens DESC")
    List<Map<String, Object>> selectStatsByCharge(@Param("tenantId") Long tenantId,
                                                  @Param("since") LocalDateTime since,
                                                  @Param("until") LocalDateTime until);

    /**
     * 「是否公司收费」三段汇总 —— 与维度无关，任何统计都带这一块。
     * {@code company_charged IS NULL} 单列「未标注」，不并进「个人自付」。
     */
    @Select("SELECT "
            + "COALESCE(SUM(CASE WHEN l.company_charged = 1 THEN l.total_tokens ELSE 0 END), 0) AS companyTokens, "
            + "COALESCE(SUM(CASE WHEN l.company_charged = 0 THEN l.total_tokens ELSE 0 END), 0) AS personalTokens, "
            + "COALESCE(SUM(CASE WHEN l.company_charged IS NULL THEN l.total_tokens ELSE 0 END), 0) AS unmarkedTokens, "
            + "COALESCE(SUM(l.total_tokens), 0) AS totalTokens, "
            + "COUNT(*) AS calls "
            + "FROM token_ledger l WHERE 1 = 1" + WINDOW)
    Map<String, Object> selectChargedSplit(@Param("tenantId") Long tenantId,
                                           @Param("since") LocalDateTime since,
                                           @Param("until") LocalDateTime until);
}
