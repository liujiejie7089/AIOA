package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
/**
 * 机构配额 —— 租户向机构分配的配额上限与占用（FR-C2/C3）
 *
 * 表：org_quota（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("org_quota")
public class OrgQuota {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private String period;

    private Long quotaTokens;

    private Long usedTokens;

    private Long freeTokens;

    private Integer warnThreshold;

    private Boolean frozen;

    private LocalDate effectiveFrom;

    private LocalDate effectiveTo;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
