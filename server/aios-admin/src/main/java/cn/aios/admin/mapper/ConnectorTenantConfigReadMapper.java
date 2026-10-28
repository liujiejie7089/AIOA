package cn.aios.admin.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 只读 {@code connector_tenant_config.secret_json}（resource 模块的表与实体 admin 不可见，
 * 故只取密文字符串，在本模块内用 SecretCodec 解密）。原生 SQL 手工过滤 deleted_at / enabled。
 */
@Mapper
public interface ConnectorTenantConfigReadMapper {

    @Select("SELECT secret_json FROM connector_tenant_config "
            + "WHERE tenant_id = #{tenantId} AND connector_code = #{code} "
            + "AND enabled = 1 AND deleted_at IS NULL LIMIT 1")
    String selectActiveSecretJson(@Param("tenantId") Long tenantId, @Param("code") String code);
}
