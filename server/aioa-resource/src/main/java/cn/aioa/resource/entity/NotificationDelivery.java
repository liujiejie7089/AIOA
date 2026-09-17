package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 通知投递记录（单条通知 × 单通道一行）。
 *
 * <p>status：SENT（成功）/ FAILED（异常）/ SKIPPED（无收件地址，已知限制如实记录）。
 * notification_id 可空：机构侧历史通知在拿不到自增 id 时也能登记一条投递。</p>
 */
@Data
@TableName("notification_delivery")
public class NotificationDelivery {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long notificationId;

    private String channelCode;

    private String status;

    private Integer attempts;

    private String lastError;

    private LocalDateTime sentAt;

    private Long createdBy;

    private LocalDateTime createdAt;

    private Long updatedBy;

    private LocalDateTime updatedAt;
}
