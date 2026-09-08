package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 词元账本流水：一次 run 只记一笔（run_id 唯一，天然幂等）。
 * biz_type: CHAT 会话 / SKILL 技能 / KB 入库 / PURCHASE 购买 / REFUND 退回。
 */
@Data
@TableName("token_ledger")
public class TokenLedger {

    public static final String BIZ_CHAT = "CHAT";
    public static final String BIZ_SKILL = "SKILL";
    public static final String BIZ_KB = "KB";
    public static final String BIZ_PURCHASE = "PURCHASE";
    public static final String BIZ_REFUND = "REFUND";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    private String runId;

    private String bizType;

    private String bizTitle;

    private Integer promptTokens;

    private Integer completionTokens;

    private Integer totalTokens;

    /** 记账后剩余额度，用于对账 */
    private Long balanceAfter;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
