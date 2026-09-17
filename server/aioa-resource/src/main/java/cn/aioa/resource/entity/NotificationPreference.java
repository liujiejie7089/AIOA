package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户级通知通道偏好。
 *
 * <p>type 为 NULL 表示「该用户的默认偏好」；精确匹配 type 优先于默认行。
 * channels：逗号分隔通道码；NULL 表示沿用租户默认（全部启用通道）。</p>
 */
@Data
@TableName("notification_preference")
public class NotificationPreference {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    /** 通知类型；NULL=该用户默认偏好 */
    private String type;

    /** 逗号分隔通道码；NULL=沿用租户默认 */
    private String channels;

    private Long createdBy;

    private LocalDateTime createdAt;

    private Long updatedBy;

    private LocalDateTime updatedAt;
}
