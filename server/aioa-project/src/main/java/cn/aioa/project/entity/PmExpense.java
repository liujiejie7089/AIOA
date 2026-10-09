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
 * 项目经费收支流水。表 {@code pm_expense}（V73）。
 *
 * <p>设计依据 {@code docs/40 §6.3} + {@code docs/43 §4}。用户关键词：
 * 「财务流水（成本记录 / 人员费用 / 各项目成本 / 分摊 / 不固定 / 增长 / 费用明细 / <b>不能修改</b>）」。</p>
 *
 * <p><b>追加式账目（append-only）—— 本表没有「修改」语义</b>：
 * 服务层**不提供 update 端点**。写错只能**红冲**：新增一条反向流水，其
 * {@link #reversalOf} 指向被冲销的行；原行永不改、永不删。这样整本账可完整审计。</p>
 *
 * <p>字段与关键词的对应：「成本记录 / 费用明细」= 一行一条流水（{@link #amount} + {@link #occurredAt}）；
 * 「人员费用」= {@link #category} 取 {@code LABOR}；「各项目成本」= 按 {@link #projectId} 聚合；
 * 「分摊」= {@link #allocRatio}；「不固定 / 增长」= 多行随时间累积，不设单值字段。</p>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_expense")
public class PmExpense {

    /** 方向：收入。 */
    public static final String DIR_IN = "IN";
    /** 方向：支出。 */
    public static final String DIR_OUT = "OUT";

    /** 分类：合同款。 */
    public static final String CAT_CONTRACT = "CONTRACT";
    /** 分类：人工（人员费用）。 */
    public static final String CAT_LABOR = "LABOR";
    /** 分类：采购。 */
    public static final String CAT_PURCHASE = "PURCHASE";
    /** 分类：差旅。 */
    public static final String CAT_TRAVEL = "TRAVEL";
    /** 分类：其他。 */
    public static final String CAT_OTHER = "OTHER";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** IN 收入 / OUT 支出，见本类常量。 */
    private String direction;

    /** CONTRACT / LABOR / PURCHASE / TRAVEL / OTHER，见本类常量。 */
    private String category;

    private BigDecimal amount;

    /** 分摊比例(%)；NULL=全额计入本项目（不分摊）。 */
    private BigDecimal allocRatio;

    /** 发生日期（费用明细的时间维度）。 */
    private LocalDate occurredAt;

    /** 来源：合同收付款确认后自动生成（BR-09）；非合同行为 NULL。 */
    private Long contractPaymentId;

    /** 凭证 sys_file.id。 */
    private Long voucherFileId;

    /** 红冲：指向被冲销的流水 id（本行是反向行时非 NULL）。 */
    private Long reversalOf;

    private String remark;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
