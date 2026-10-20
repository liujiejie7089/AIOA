package cn.aios.resource.connector.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 租户级应用凭据（管理员配）。secret_json 为密文（SecretCodec 加密）。见 docs/58 §5。
 */
@Data
@TableName("connector_tenant_config")
public class ConnectorTenantConfig {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String connectorCode;
    /** 加密后的应用配置 JSON（含 corpId / agentId / corpSecret 等，按连接器而定）。 */
    private String secretJson;
    private Boolean enabled;
    private Long updatedBy;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
