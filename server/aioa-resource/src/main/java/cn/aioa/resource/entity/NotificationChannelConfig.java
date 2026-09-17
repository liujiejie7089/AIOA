package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 每租户通知通道配置（启用开关 + 网关参数）。
 *
 * <p>INAPP 站内信恒可用，永不入库；其余通道由管理员开启并填写 config_json 后才生效。
 * config_json 原样保存未知键以保证「打开-保存」无损往返。</p>
 */
@Data
@TableName("notification_channel_config")
public class NotificationChannelConfig {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String channelCode;

    /** 1=已启用 */
    private Integer enabled;

    /** 网关配置 JSON（未知键原样保留） */
    private String configJson;

    private Long createdBy;

    private LocalDateTime createdAt;

    private Long updatedBy;

    private LocalDateTime updatedAt;
}
