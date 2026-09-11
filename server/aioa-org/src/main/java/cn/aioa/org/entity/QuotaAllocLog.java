package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
/**
 * 配额分配流水 —— 贯穿四级链路，审计依据
 *
 * 表：quota_alloc_log（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("quota_alloc_log")
public class QuotaAllocLog {
    public static final String ACTION_ALLOCATE = "ALLOCATE";
    public static final String ACTION_ADJUST = "ADJUST";
    public static final String ACTION_FREEZE = "FREEZE";
    public static final String ACTION_UNFREEZE = "UNFREEZE";
    public static final String ACTION_CONSUME = "CONSUME";
    public static final String SCOPE_TENANT = "TENANT";
    public static final String SCOPE_ORG = "ORG";
    public static final String SCOPE_DEPT = "DEPT";
    public static final String SCOPE_USER = "USER";


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private String scopeType;

    private Long scopeId;

    private String period;

    private String action;

    private Long beforeTokens;

    private Long delta;

    private Long afterTokens;

    private String reason;

    private Long operatorId;

    private String operatorName;

    private String operatorRole;

    private LocalDateTime createdAt;
}
