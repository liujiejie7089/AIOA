package cn.aios.resource.connector.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 租户接入授权（docs/92 阶段 1，V115）。
 *
 * <p><b>与 {@link ConnectorTenantConfig} 的分工</b>：那张表存「租户级应用凭据（密文）」，
 * 供 {@code config_keys} 非空的连接器判定配置就绪；本表存「该租户是否授权接入某个连接器 +
 * 允许调用的机构范围 + 租户级数据源配置」。两者语义正交，不是两套开关源：scfy 无凭据，
 * 只走本表；QQ 邮箱/企微等无需租户授权的连接器不出现在本表。</p>
 *
 * <p><b>四态口径</b>（{@code ConnectorTenantAccessService#status}）：</p>
 * <ul>
 *   <li>无行 ⇒ {@code NOT_CONNECTED}（未接入，新租户默认态）；</li>
 *   <li>有行 + {@code enabled=0} + 无配置 ⇒ {@code CONFIGURED_DISABLED}（已配置待启用）；</li>
 *   <li>有行 + {@code enabled=0} + 曾有 enabled_at ⇒ {@code DISABLED}（已停用）；</li>
 *   <li>有行 + {@code enabled=1} ⇒ {@code ENABLED}。</li>
 * </ul>
 */
@Data
@TableName("connector_tenant_access")
public class ConnectorTenantAccess {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String connectorCode;
    private Boolean enabled;
    /** 允许调用的机构 ID 白名单（JSON 数组文本）；空 / "[]" = 不限制机构（全租户）。 */
    private String scopeInstitutions;
    /** 租户级接入配置（JSON 文本，如 baseUrl 覆盖）；空 = 用平台默认。 */
    private String configJson;
    private Long enabledBy;
    private LocalDateTime enabledAt;
    private Long createdBy;
    private Long updatedBy;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
