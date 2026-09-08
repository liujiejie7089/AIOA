package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 词元额度。user_id = 0 表示租户共享额度；否则为该用户的个人额度。
 */
@Data
@TableName("tenant_quota")
public class TenantQuota {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    private Long quotaTokens;

    private Long usedTokens;

    /** 赠送额度，独立于套餐额度 */
    private Long freeTokens;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
