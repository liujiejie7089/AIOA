package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 支付订单（FR-G4 交易凭证，连接账本与支付）。 */
@Data
@TableName("payment_order")
public class PaymentOrder {

    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_PAID = "PAID";
    public static final String STATUS_CANCELLED = "CANCELLED";

    @TableId(type = IdType.AUTO)
    private Long id;
    private String orderNo;
    private Long tenantId;
    private Long userId;
    private Long packageId;
    private String packageName;
    private Long tokens;
    private Integer amountCents;
    private String status;
    private String payChannel;
    private LocalDateTime payTime;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
}
