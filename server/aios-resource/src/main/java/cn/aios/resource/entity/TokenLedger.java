package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 词元账本流水：一次 run 只记一笔（run_id 唯一，天然幂等）。
 * biz_type: CHAT 会话 / SKILL 技能 / KB 入库 / PURCHASE 购买 / REFUND 退回。
 *
 * <p><b>归属三列（2026-11-03，docs/71）</b>：{@code userId} 的语义冻结为「账本归属人」
 * （= {@code bearerUserId}，实际使用者）；{@code chargeUserId} 是平台侧承担者；
 * {@code companyCharged} 标注这笔用量是否由公司收费。三者拆开的唯一原因是
 * 「A 用 B 注册的账号」这种共享场景下，使用者与付费人不是同一个人。</p>
 *
 * <p>{@code companyCharged} 允许为 NULL：历史账本不知道当时用的是谁的账号，
 * 补 0 等于谎报「个人自付」，故留 NULL 表示「未标注」，统计里单列一档。</p>
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

    /** 本次用的哪个模型账号；NULL = 走平台默认通道（model_config / 环境变量） */
    private Long credentialId;

    /** 实际使用者（发起对话的人） */
    private Long bearerUserId;

    /** 平台侧承担者：PERSONAL = 账号持有人；COMPANY = 0 表示公司池 */
    private Long chargeUserId;

    /** PERSONAL / COMPANY；NULL = 历史未标注 */
    private String chargeOwnerType;

    /** 1 公司收费 / 0 个人自付 / NULL 未标注 —— 「是否公司收费」的唯一事实源 */
    private Integer companyCharged;

    private String providerKey;

    private String modelName;

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
