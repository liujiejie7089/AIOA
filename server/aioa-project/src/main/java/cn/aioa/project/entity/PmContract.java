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
 * 项目合同。表 {@code pm_contract}（V73）。设计依据 {@code docs/40 §6.3}。
 *
 * <p>用户关键词「合同（<b>采购</b>，<b>收款</b>）」→ {@link #direction}：
 * {@link #DIR_OUT} 付款合同（采购）/ {@link #DIR_IN} 收款合同（我方开票）。</p>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_contract")
public class PmContract {

    /** 方向：收款合同（我方开票）。 */
    public static final String DIR_IN = "IN";
    /** 方向：付款合同（采购）。 */
    public static final String DIR_OUT = "OUT";

    /** 分类：采购。 */
    public static final String CAT_PURCHASE = "PURCHASE";
    /** 分类：销售收款。 */
    public static final String CAT_SALES = "SALES";
    /** 分类：服务。 */
    public static final String CAT_SERVICE = "SERVICE";
    /** 分类：其他。 */
    public static final String CAT_OTHER = "OTHER";

    /** 状态：草稿。 */
    public static final String ST_DRAFT = "DRAFT";
    /** 状态：审批中。 */
    public static final String ST_PENDING = "PENDING_APPROVAL";
    /** 状态：已签。 */
    public static final String ST_SIGNED = "SIGNED";
    /** 状态：履行中。 */
    public static final String ST_EXECUTING = "EXECUTING";
    /** 状态：已结。 */
    public static final String ST_CLOSED = "CLOSED";
    /** 状态：已终止。 */
    public static final String ST_TERMINATED = "TERMINATED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** 合同编号（租户内唯一，软删释放）。 */
    private String contractNo;

    private String name;

    /** IN 收款 / OUT 付款（采购），见本类常量。 */
    private String direction;

    /** PURCHASE / SALES / SERVICE / OTHER。 */
    private String category;

    /** 对方单位。 */
    private String partyName;

    private BigDecimal amount;

    /** 见本类状态常量。 */
    private String status;

    /** 复用审批引擎（biz_type=PM_CONTRACT）。 */
    private Long approvalOrderId;

    private LocalDate signedAt;

    private LocalDate startDate;

    private LocalDate endDate;

    /** 合同扫描件 sys_file.id。 */
    private Long fileId;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
