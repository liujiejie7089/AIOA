package cn.aios.resource.connector.mapper;

import cn.aios.resource.connector.entity.ConnectorTenantConfig;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface ConnectorTenantConfigMapper extends BaseMapper<ConnectorTenantConfig> {

    /**
     * 含软删行的查询。唯一键 {@code uk_tenant_config(tenant_id, connector_code)} **不含 deleted_at**，
     * 软删行会永久占位 —— 直接 insert 会 Duplicate entry（与 mcp_server 注册坑同款）。
     * upsert 前必须用本方法探场，命中软删行走 {@link #reviveAndUpdate} 复活。
     */
    @Select("SELECT * FROM connector_tenant_config "
            + "WHERE tenant_id = #{tenantId} AND connector_code = #{code} "
            + "ORDER BY id DESC LIMIT 1")
    ConnectorTenantConfig selectIncludingDeleted(@Param("tenantId") Long tenantId,
                                                 @Param("code") String code);

    /** 复活软删行并覆盖配置（updateById 会带 {@code deleted_at IS NULL} 条件，软删行必须走原生 SQL）。 */
    @Update("UPDATE connector_tenant_config SET secret_json = #{secretJson}, enabled = #{enabled}, "
            + "updated_by = #{userId}, updated_at = #{now}, deleted_at = NULL WHERE id = #{id}")
    int reviveAndUpdate(@Param("id") Long id,
                        @Param("secretJson") String secretJson,
                        @Param("enabled") Boolean enabled,
                        @Param("userId") Long userId,
                        @Param("now") java.time.LocalDateTime now);
}
