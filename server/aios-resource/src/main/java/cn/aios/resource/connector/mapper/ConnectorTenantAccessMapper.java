package cn.aios.resource.connector.mapper;

import cn.aios.resource.connector.entity.ConnectorTenantAccess;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * 租户接入授权 Mapper（V115）。
 *
 * <p>沿用 {@link ConnectorTenantConfigMapper} 的软删坑处理：唯一键
 * {@code uk_tenant_access(tenant_id, connector_code)} 不含 {@code deleted_at}，
 * 软删行会永久占位；{@code @TableLogic} 又让 {@code selectOne} / {@code updateById}
 * 看不见、改不到软删行。故 upsert 前必须 {@link #selectIncludingDeleted} 探场，
 * 命中死行走 {@link #reviveAndUpdate} 裸 SQL 复活，否则 insert 撞唯一键 500。</p>
 */
@Mapper
public interface ConnectorTenantAccessMapper extends BaseMapper<ConnectorTenantAccess> {

    @Select("SELECT * FROM connector_tenant_access "
            + "WHERE tenant_id = #{tenantId} AND connector_code = #{code} "
            + "ORDER BY id DESC LIMIT 1")
    ConnectorTenantAccess selectIncludingDeleted(@Param("tenantId") Long tenantId,
                                                 @Param("code") String code);

    /** 复活软删行并覆盖启用态/配置（updateById 带 deleted_at IS NULL 条件，够不到死行）。 */
    @Update("UPDATE connector_tenant_access SET enabled = #{enabled}, "
            + "scope_institutions = #{scope}, config_json = #{config}, "
            + "enabled_by = #{userId}, enabled_at = CASE WHEN #{enabled} = 1 THEN #{now} ELSE enabled_at END, "
            + "updated_by = #{userId}, updated_at = #{now}, deleted_at = NULL WHERE id = #{id}")
    int reviveAndUpdate(@Param("id") Long id,
                        @Param("enabled") Boolean enabled,
                        @Param("scope") String scope,
                        @Param("config") String config,
                        @Param("userId") Long userId,
                        @Param("now") java.time.LocalDateTime now);
}
