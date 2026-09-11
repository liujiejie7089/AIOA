package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
/**
 * 分摊账单 —— 与平台账本逐笔一致的凭证（FR-D2）
 *
 * 表：cost_alloc_bill（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("cost_alloc_bill")
public class CostAllocBill {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long ruleId;

    private Integer ruleVersion;

    private Long institutionId;

    private String period;

    private Long usageTokens;

    private BigDecimal unitPrice;

    private BigDecimal amount;

    private String serialNo;

    private Boolean ledgerChecked;

    private LocalDateTime generatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
