package cn.aios.resource.connector.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 连接器目录（平台级，tenant_id=0）。见 docs/58 §5。
 */
@Data
@TableName("connector_def")
public class ConnectorDef {

    public static final String AUTH_MODE_CREDENTIAL = "CREDENTIAL";
    public static final String AUTH_MODE_OAUTH2 = "OAUTH2";
    /** 租户级凭据（管理员填 key，无用户授权环节），如企业微信群机器人。 */
    public static final String AUTH_MODE_API_KEY = "API_KEY";
    public static final String STATUS_ACTIVE = "ACTIVE";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String code;
    private String name;
    private String groupName;
    private String icon;
    private String summary;
    private String authMode;
    /** 应用配置键（JSON 数组文本，如 ["corpId","agentId","corpSecret"]）；读时按需要解析。 */
    private String configKeys;
    private String helpText;
    private String helpUrl;
    private Integer sort;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
