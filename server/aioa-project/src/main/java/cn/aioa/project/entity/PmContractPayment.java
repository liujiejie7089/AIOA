package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 合同收付款明细（计划 / 实收实付）。表 {@code pm_contract_payment}（V73）。
 *
 * <p>设计依据 {@code docs/40 §6.3}。<b>BR-09</b>：{@link #ST_CONFIRMED} 时必须在**同一事务**内
 * 自动生成一条 {@code pm_expense}（{@code contract_payment_id} 溯源）——单一事实源，禁止两边各记一遍；
 * 已确认的收付款不可删，只能红冲。</p>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_contract_payment")
public class PmContractPayment {

    /** 状态：计划。 */
    public static final String ST_PLANNED = "PLANNED";
    /** 状态：已确认（实收/实付）。 */
    public static final String ST_CONFIRMED = "CONFIRMED";
    /** 状态：已红冲。 */
    public static final String ST_REVERSED = "REVERSED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long contractId;

    /** 第几期（合同内自增）。 */
    private Integer seq;

    /** 计划金额。 */
    private BigDecimal planAmount;

    /** 计划收付款日。 */
    private LocalDate planDate;

    private BigDecimal actualAmount;

    private LocalDate actualDate;

    /** PLANNED / CONFIRMED / REVERSED，见本类常量。 */
    private String status;

    /** 若为里程碑付款条件，指向 pm_milestone。 */
    private Long milestoneId;

    private Long voucherFileId;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
