package cn.aios.resource.connector.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * OAuth 防伪 state（一次性、10 分钟过期）。见 docs/58 §3.3。
 * state 由应用侧生成（UUID），故用 INPUT 主键。
 */
@Data
@TableName("connector_oauth_state")
public class ConnectorOauthState {

    @TableId(type = IdType.INPUT)
    private String state;
    private Long tenantId;
    private Long userId;
    private String connectorCode;
    private String returnPath;
    private String origin;
    private LocalDateTime createdAt;
    private LocalDateTime usedAt;
}
