package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 经营数据看板 —— 趋势柱（V1.2 新增）。
 * 近 N 期数值序列，hot=1 表示当期高亮；numValue 单位为万元（前端按 period 自行标注）。
 */
@Data
@TableName("biz_kpi_trend")
public class BizKpiTrend {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String period;

    /** X 轴标签，如 4月 */
    private String pointLabel;

    private BigDecimal numValue;

    /** 1=当期高亮 */
    private Integer hot;

    private Integer sortNo;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
