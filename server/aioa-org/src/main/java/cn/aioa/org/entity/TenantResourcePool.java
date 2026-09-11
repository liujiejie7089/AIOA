package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
/**
 * 租户资源池 —— 平台交付的词元套餐与订阅席位（FR-C1）
 *
 * 表：tenant_resource_pool（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("tenant_resource_pool")
public class TenantResourcePool {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String period;

    private Long tokenTotal;

    private Long tokenUsed;

    private Integer expertSeats;

    private Integer expertUsed;

    private Integer skillSeats;

    private Integer skillUsed;

    private Integer warnThreshold;

    private BigDecimal unitPrice;

    private LocalDate expireAt;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
