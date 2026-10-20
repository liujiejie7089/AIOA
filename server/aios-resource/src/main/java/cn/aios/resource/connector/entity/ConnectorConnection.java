package cn.aios.resource.connector.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户级连接状态。状态机唯一判定点在 ConnectorConnectionService（docs/58 §3.4）。
 * credential_json 为密文。disconnect 只置 NEED_AUTH + 清凭据，不物理删行。
 */
@Data
@TableName("connector_connection")
public class ConnectorConnection {

    public static final String STATUS_NEED_AUTH = "NEED_AUTH";
    public static final String STATUS_CONNECTED = "CONNECTED";
    public static final String STATUS_UNVERIFIED = "UNVERIFIED";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long userId;
    private String connectorCode;
    private String status;
    private String accountLabel;
    /** 加密后的凭据 JSON（CREDENTIAL：{email,authCode}；OAUTH2：{userid}）。 */
    private String credentialJson;
    private LocalDateTime expiresAt;
    private String lastError;
    private LocalDateTime connectedAt;
    private LocalDateTime lastCheckedAt;
    private LocalDateTime disconnectedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
