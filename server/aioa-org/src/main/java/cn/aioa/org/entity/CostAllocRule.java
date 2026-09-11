package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
/**
 * 费用分摊规则（FR-D1）
 *
 * 表：cost_alloc_rule（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("cost_alloc_rule")
public class CostAllocRule {
    public static final String TYPE_FIXED_RATIO = "FIXED_RATIO";
    public static final String TYPE_USAGE = "USAGE";
    public static final String TYPE_COST_CENTER = "COST_CENTER";
    public static final String PERIOD_MONTH = "MONTH";
    public static final String PERIOD_QUARTER = "QUARTER";
    public static final String STATUS_ACTIVE = "ACTIVE";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String name;

    private String ruleType;

    private String periodType;

    private String configJson;

    private Integer version;

    private LocalDate effectiveFrom;

    private String status;

    private String remark;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
