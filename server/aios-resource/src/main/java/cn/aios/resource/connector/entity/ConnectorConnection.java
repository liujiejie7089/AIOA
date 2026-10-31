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
 *
 * <p><b>{@link #STATUS_DISABLED}（2026-10-31 新增）</b>：用户主动「关闭」连接器。
 * 与 {@code NEED_AUTH} 的区别是**凭据仍然保留** —— 关闭只是「先别给 AI 用」，
 * 再开启时直接回到 {@code CONNECTED}，不需要重新填授权码 / 重新扫码。
 * 所有闸门（MCP manifest、MailService）只认 {@code CONNECTED} ⇒ 关闭态自动不注入工具。</p>
 */
@Data
@TableName("connector_connection")
public class ConnectorConnection {

    public static final String STATUS_NEED_AUTH = "NEED_AUTH";
    public static final String STATUS_CONNECTED = "CONNECTED";
    public static final String STATUS_UNVERIFIED = "UNVERIFIED";
    /** 已关闭（授权保留）：不是「未连接」，只是暂时不给 AI 用。 */
    public static final String STATUS_DISABLED = "DISABLED";

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
